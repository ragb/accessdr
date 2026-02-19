"""
accessibility/sonification.py — Spectrum-to-audio tone mapping.

Converts FFT magnitude bins into a stereo sweeping tone that gives blind
users an audible overview of the spectrum without needing a visual
waterfall display.

Mapping
-------
- **Pan (L→R)** encodes frequency position — left ear = low end of the
  spectrum, right ear = high end.  Equal-power panning via cos/sin.
- **Pitch** encodes signal power — stronger signals produce a higher
  pitch, weak signals / noise floor produce a low pitch or silence.
  The mapping is logarithmic (octaves) for perceptual uniformity.
- **Amplitude** is a fixed level (MAX_AMP) above the noise floor and
  zero below it, so noise stays silent and signals are clearly audible.

Design
------
- The audio callback is fully vectorised with NumPy — no per-sample
  Python loops, so it runs safely inside the sounddevice audio thread.
- Phase is carried between callback blocks for glitch-free audio.
- Snapshot mode plays exactly one full L→R sweep then stops.

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

MAX_AMP = 0.25          # peak output amplitude (0–1)

# Amplitude is normalised relative to the spectrum's own noise floor so
# that the mapping adapts to any absolute power scale coming from the FFT.
# The bottom NOISE_PERCENTILE of bins defines silence; bins DYNAMIC_RANGE_DB
# above that floor reach MAX_AMP.
_NOISE_PERCENTILE = 20    # percent of bins used to estimate noise floor
_DYNAMIC_RANGE_DB = 30.0  # dB above noise floor that maps to full amplitude


class Sonification:
    """Sweeps across FFT bins, generating a pitched tone per bin."""

    def __init__(
        self,
        min_pitch: int = 200,
        max_pitch: int = 4000,
        sweep_speed: float = 1.0,
    ) -> None:
        self.min_pitch  = min_pitch
        self.max_pitch  = max_pitch
        self.sweep_speed = sweep_speed          # seconds per full sweep

        self._spectrum: Optional[np.ndarray] = None
        self._lock       = threading.Lock()
        self._stream: Optional["sd.OutputStream"] = None
        self._phase      = 0.0                 # fractional cycle, carried across blocks
        self._sweep_pos  = 0.0                 # 0.0–1.0 across spectrum
        self._running    = False
        self._is_snapshot = False              # True → stop after one full sweep

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
        self.stop()
        self._is_snapshot = False
        self._sweep_pos   = 0.0
        self._phase       = 0.0
        self._running     = True
        self._open_stream()

    def snapshot(self) -> None:
        """Play a single full sweep of the current spectrum then stop."""
        if not _SD_AVAILABLE:
            return
        self.stop()
        self._is_snapshot = True
        self._sweep_pos   = 0.0
        self._phase       = 0.0
        self._running     = True
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

    @property
    def sweep_pos(self) -> float:
        """Current sweep position (0.0–1.0), or -1.0 if not sweeping."""
        if not self._running:
            return -1.0
        return self._sweep_pos

    def update_settings(
        self,
        min_pitch: Optional[int] = None,
        max_pitch: Optional[int] = None,
        sweep_speed: Optional[float] = None,
    ) -> None:
        if min_pitch  is not None:
            self.min_pitch   = min_pitch
        if max_pitch  is not None:
            self.max_pitch   = max_pitch
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
                channels=2,
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
        """sounddevice callback — runs in audio thread, fully vectorised.

        Mapping: pan = frequency position, pitch = signal power.
        """
        with self._lock:
            spectrum = self._spectrum

        outdata[:] = 0.0

        if spectrum is None or not self._running:
            raise sd.CallbackStop()

        bins          = len(spectrum)
        sweep_samples = max(1, int(SAMPLE_RATE * self.sweep_speed))

        # Raw sweep positions for this block (may cross 1.0 for snapshot)
        pos_raw = self._sweep_pos + np.arange(frames, dtype=np.float64) / sweep_samples

        # Snapshot: play exactly until the position first reaches 1.0
        stop_after = False
        if self._is_snapshot:
            wrap_mask = pos_raw >= 1.0
            if np.any(wrap_mask):
                cut = int(np.argmax(wrap_mask))
                if cut == 0:
                    self._running = False
                    raise sd.CallbackStop()
                pos_raw    = pos_raw[:cut]
                stop_after = True

        n        = len(pos_raw)
        pos_norm = pos_raw % 1.0   # wrap to [0, 1)

        # Update sweep position for the next block
        self._sweep_pos = float(pos_raw[-1] % 1.0) if n > 0 else self._sweep_pos

        # --- Interpolate power at current sweep position ---
        noise_floor = float(np.percentile(spectrum, _NOISE_PERCENTILE))

        bin_f  = pos_norm * (bins - 1)
        bin_lo = bin_f.astype(np.intp)
        bin_hi = np.clip(bin_lo + 1, 0, bins - 1)
        frac   = bin_f - bin_lo
        amp_db = spectrum[bin_lo] * (1.0 - frac) + spectrum[bin_hi] * frac

        # --- Amplitude: ramp quickly from silence to MAX_AMP over a few dB ---
        # A 3 dB soft knee avoids clicks at the noise-floor boundary.
        _KNEE_DB = 3.0
        amp = np.clip((amp_db - noise_floor) / _KNEE_DB, 0.0, 1.0) * MAX_AMP

        # --- Pitch: power → frequency (logarithmic, perceptually uniform) ---
        power_norm = np.clip(
            (amp_db - noise_floor) / _DYNAMIC_RANGE_DB, 0.0, 1.0,
        )
        log_ratio = math.log(max(self.max_pitch, self.min_pitch + 1) / self.min_pitch)
        freq = self.min_pitch * np.exp(log_ratio * power_norm)

        # --- Pan: equal-power L/R from sweep position ---
        gain_l = np.cos(pos_norm * (np.pi / 2.0))
        gain_r = np.sin(pos_norm * (np.pi / 2.0))

        # --- Phase accumulation (continuous across blocks, no clicks) ---
        phase_inc = freq / SAMPLE_RATE
        phases    = self._phase + np.cumsum(phase_inc)
        self._phase = float(phases[-1]) % 1.0

        # Warm timbre: fundamental + soft 2nd & 3rd harmonics (organ-like)
        two_pi = 2.0 * np.pi
        raw = (np.sin(two_pi * phases)
               + 0.3 * np.sin(2.0 * two_pi * phases)
               + 0.1 * np.sin(3.0 * two_pi * phases))
        tone = (amp / 1.4 * raw).astype(np.float32)
        outdata[:n, 0] = gain_l.astype(np.float32) * tone
        outdata[:n, 1] = gain_r.astype(np.float32) * tone

        if stop_after:
            self._running = False
            raise sd.CallbackStop()

    def _stream_finished(self) -> None:
        self._stream = None
