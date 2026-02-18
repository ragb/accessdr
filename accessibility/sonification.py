"""
accessibility/sonification.py — Spectrum-to-audio tone mapping.

Converts FFT magnitude bins into a sweeping tone that pitch-encodes
frequency position and amplitude-encodes signal strength, giving blind
users an audible overview of the spectrum without needing a visual
waterfall display.

Usage
-----
    son = Sonification(min_pitch=200, max_pitch=4000)
    son.set_spectrum(bins_db)   # called from DSP thread via wx.CallAfter
    son.start_sweep()           # begin continuous L→R sweep
    son.snapshot()              # single on-demand sweep
    son.stop()                  # stop all sonification audio
"""

from __future__ import annotations

import logging
import math
import threading
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

try:
    import sounddevice as sd
    _SD_AVAILABLE = True
except Exception:                  # noqa: BLE001
    _SD_AVAILABLE = False
    logger.warning("sounddevice not available — sonification disabled")

SAMPLE_RATE = 44_100               # Hz for sonification stream


class Sonification:
    """Sweeps across FFT bins, generating a pitched tone per bin."""

    def __init__(
        self,
        min_pitch: int = 200,
        max_pitch: int = 4000,
        sweep_speed: float = 1.0,
    ) -> None:
        self.min_pitch = min_pitch
        self.max_pitch = max_pitch
        self.sweep_speed = sweep_speed          # seconds per full sweep

        self._spectrum: Optional[np.ndarray] = None
        self._lock = threading.Lock()
        self._stream: Optional["sd.OutputStream"] = None
        self._phase = 0.0
        self._sweep_pos = 0.0                  # 0.0–1.0 across spectrum
        self._running = False
        self._snapshot_remaining = 0           # samples left in snapshot

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def set_spectrum(self, bins_db: np.ndarray) -> None:
        """Update the current spectrum (dB array, length = FFT size).

        Called from the DSP thread via wx.CallAfter — thread-safe via lock.
        """
        with self._lock:
            self._spectrum = bins_db.copy()

    def start_sweep(self) -> None:
        """Begin continuous automatic sweep (left → right, repeating)."""
        if not _SD_AVAILABLE:
            return
        self._running = True
        self._sweep_pos = 0.0
        self._open_stream()

    def snapshot(self) -> None:
        """Play a single sweep of the current spectrum then stop."""
        if not _SD_AVAILABLE:
            return
        samples_needed = int(SAMPLE_RATE * self.sweep_speed)
        self._snapshot_remaining = samples_needed
        self._sweep_pos = 0.0
        self._running = True
        self._open_stream()

    def stop(self) -> None:
        """Stop sonification audio immediately."""
        self._running = False
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:      # noqa: BLE001
                pass
            self._stream = None

    def update_settings(
        self,
        min_pitch: Optional[int] = None,
        max_pitch: Optional[int] = None,
        sweep_speed: Optional[float] = None,
    ) -> None:
        if min_pitch is not None:
            self.min_pitch = min_pitch
        if max_pitch is not None:
            self.max_pitch = max_pitch
        if sweep_speed is not None:
            self.sweep_speed = sweep_speed

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _open_stream(self) -> None:
        if self._stream is not None:
            return                 # already running
        if not _SD_AVAILABLE:
            return
        try:
            self._stream = sd.OutputStream(
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="float32",
                blocksize=512,
                callback=self._audio_callback,
                finished_callback=self._stream_finished,
            )
            self._stream.start()
        except Exception as exc:   # noqa: BLE001
            logger.error("Could not open sonification stream: %s", exc)
            self._stream = None

    def _audio_callback(
        self,
        outdata: np.ndarray,
        frames: int,
        time,                      # noqa: ANN001
        status,                    # noqa: ANN001
    ) -> None:
        """sounddevice callback — runs in audio thread."""
        with self._lock:
            spectrum = self._spectrum

        n = frames
        out = np.zeros(n, dtype=np.float32)

        if spectrum is not None and self._running:
            bins = len(spectrum)
            sweep_samples = int(SAMPLE_RATE * self.sweep_speed)
            samples_per_bin = max(1, sweep_samples // bins)

            for i in range(n):
                # Current bin index
                bin_idx = int(self._sweep_pos * bins) % bins
                amp_db = float(spectrum[bin_idx])

                # Map dB (-120..0) to amplitude 0..1
                amp = max(0.0, min(1.0, (amp_db + 120.0) / 120.0)) * 0.3

                # Pitch: linear interpolation across pitch range
                t = bin_idx / max(bins - 1, 1)
                freq = self.min_pitch + t * (self.max_pitch - self.min_pitch)

                # Generate sine sample
                out[i] = amp * math.sin(2.0 * math.pi * self._phase)
                self._phase += freq / SAMPLE_RATE
                if self._phase > 1.0:
                    self._phase -= 1.0

                # Advance sweep position
                self._sweep_pos += 1.0 / sweep_samples
                if self._sweep_pos >= 1.0:
                    self._sweep_pos = 0.0
                    if self._snapshot_remaining > 0:
                        self._running = False
                        break

                if self._snapshot_remaining > 0:
                    self._snapshot_remaining -= 1
                    if self._snapshot_remaining == 0:
                        self._running = False
                        break

        outdata[:, 0] = out

    def _stream_finished(self) -> None:
        if not self._running and self._stream is not None:
            try:
                self._stream.close()
            except Exception:      # noqa: BLE001
                pass
            self._stream = None
