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
- Probe mode plays a continuous tone at a fixed position for the
  spectrum cursor feature.

Usage
-----
    son = Sonification(min_pitch=200, max_pitch=4000)
    son.set_spectrum(bins_db)   # called from DSP thread via wx.CallAfter
    son.start_sweep()           # begin continuous L→R sweep
    son.snapshot()              # single on-demand sweep
    son.start_probe(0.5)        # probe tone at position 0.5
    son.update_probe(0.7)       # move probe to position 0.7
    son.stop_probe()            # stop probe tone
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

SAMPLE_RATE = 48_000               # Hz for sonification stream (must match WASAPI)

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
        spectrum_averaging_ms: float = 80.0,
        pitch_smoothing_ms: float = 30.0,
    ) -> None:
        self.min_pitch  = min_pitch
        self.max_pitch  = max_pitch
        self.sweep_speed = sweep_speed          # seconds per full sweep
        self.spectrum_averaging_ms = spectrum_averaging_ms
        self.pitch_smoothing_ms = pitch_smoothing_ms

        self._spectrum: Optional[np.ndarray] = None
        self._spectrum_avg: Optional[np.ndarray] = None  # EMA-smoothed spectrum
        self._lock       = threading.Lock()
        self._stream: Optional["sd.OutputStream"] = None
        self._phase      = 0.0                 # fractional cycle, carried across blocks
        self._sweep_pos  = 0.0                 # 0.0–1.0 across spectrum
        self._running    = False
        self._is_snapshot = False              # True → stop after one full sweep
        self._amp_smooth = 0.0                 # smoothed amplitude carried between blocks
        self._freq_smooth = 0.0                # smoothed pitch carried between blocks

        self._device = None                    # output device (name or index)
        self._on_finish_cb = None              # called (from audio thread) when sweep ends

        # Probe mode (spectrum cursor)
        self._probe_active = False
        self._probe_pos    = 0.5               # 0.0–1.0 position
        self._probe_target = 0.5               # smooth-interpolation target

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def set_device(self, device) -> None:
        """Set the output device (name, index, or None for default)."""
        self._device = device

    def set_on_finish(self, callback) -> None:
        """Register a callback invoked when a sweep/snapshot finishes."""
        self._on_finish_cb = callback

    def set_spectrum(self, bins_db: np.ndarray) -> None:
        """Update the current spectrum (dB array, length = FFT size).

        Applies exponential moving average across frames for stability.
        Called from the DSP thread via wx.CallAfter — thread-safe via lock.
        """
        with self._lock:
            self._spectrum = bins_db.copy()
            # EMA smoothing: alpha derived from averaging time constant.
            # Typical DSP chunk interval is ~25 ms at 2.4 MSPS / 65536 samples.
            tc = max(1.0, self.spectrum_averaging_ms)
            alpha = min(1.0, 25.0 / tc)  # ~25 ms per frame estimate
            if self._spectrum_avg is None or len(self._spectrum_avg) != len(bins_db):
                self._spectrum_avg = bins_db.copy()
            else:
                self._spectrum_avg += alpha * (bins_db - self._spectrum_avg)

    def start_sweep(self) -> None:
        """Begin continuous automatic sweep (left → right, repeating)."""
        if not _SD_AVAILABLE:
            return
        self.stop()
        self._is_snapshot = False
        self._sweep_pos   = 0.0
        self._phase       = 0.0
        self._amp_smooth  = 0.0
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
        self._amp_smooth  = 0.0
        self._running     = True
        self._open_stream()

    def start_probe(self, position: float) -> None:
        """Start probe mode: play a continuous tone at *position* (0.0–1.0)."""
        if not _SD_AVAILABLE:
            return
        self.stop()
        self._probe_pos    = max(0.0, min(1.0, position))
        self._probe_target = self._probe_pos
        self._probe_active = True
        self._phase        = 0.0
        self._amp_smooth   = 0.0
        self._running      = True
        self._is_snapshot  = False
        self._open_stream()

    def update_probe(self, position: float) -> None:
        """Move the probe to a new position (smoothly interpolated)."""
        self._probe_target = max(0.0, min(1.0, position))

    def stop_probe(self) -> None:
        """Stop probe mode audio."""
        self._probe_active = False
        self.stop()

    def stop(self) -> None:
        """Stop sonification audio immediately."""
        self._running = False
        self._probe_active = False
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
        spectrum_averaging_ms: Optional[float] = None,
        pitch_smoothing_ms: Optional[float] = None,
    ) -> None:
        if min_pitch  is not None:
            self.min_pitch   = min_pitch
        if max_pitch  is not None:
            self.max_pitch   = max_pitch
        if sweep_speed is not None:
            self.sweep_speed = sweep_speed
        if spectrum_averaging_ms is not None:
            self.spectrum_averaging_ms = spectrum_averaging_ms
        if pitch_smoothing_ms is not None:
            self.pitch_smoothing_ms = pitch_smoothing_ms

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _open_stream(self) -> None:
        if self._stream is not None:
            return                 # already running
        if not _SD_AVAILABLE:
            return
        try:
            kwargs: dict = dict(
                samplerate=SAMPLE_RATE,
                channels=2,
                dtype="float32",
                blocksize=512,
                callback=self._audio_callback,
                finished_callback=self._stream_finished,
            )
            if self._device is not None:
                kwargs["device"] = self._device
            self._stream = sd.OutputStream(**kwargs)
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
            spectrum = self._spectrum_avg if self._spectrum_avg is not None else self._spectrum

        outdata[:] = 0.0

        if spectrum is None or not self._running:
            raise sd.CallbackStop()

        # --- Probe mode: fixed-position tone for spectrum cursor ---
        if self._probe_active:
            self._render_probe(outdata, frames, spectrum)
            return

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

        # --- Amplitude: gradual ramp from silence to MAX_AMP over dynamic range ---
        # Maps power above noise floor to amplitude using sqrt for perceptual
        # uniformity (weak signals still audible, strong signals louder).
        above_floor = np.clip(
            (amp_db - noise_floor) / _DYNAMIC_RANGE_DB, 0.0, 1.0,
        )
        amp_raw = np.sqrt(above_floor) * MAX_AMP

        # One-pole IIR smoothing to prevent clicks at bin boundaries.
        # ~3 ms time constant at 44100 Hz ≈ alpha 0.0075 per sample.
        _SMOOTH_ALPHA = 1.0 - math.exp(-1.0 / (SAMPLE_RATE * 0.003))
        amp = np.empty_like(amp_raw)
        amp[0] = self._amp_smooth + _SMOOTH_ALPHA * (amp_raw[0] - self._amp_smooth)
        for i in range(1, n):
            amp[i] = amp[i - 1] + _SMOOTH_ALPHA * (amp_raw[i] - amp[i - 1])
        self._amp_smooth = float(amp[-1]) if n > 0 else self._amp_smooth

        # --- Pitch: power → frequency (logarithmic, perceptually uniform) ---
        power_norm = np.clip(
            (amp_db - noise_floor) / _DYNAMIC_RANGE_DB, 0.0, 1.0,
        )
        log_ratio = math.log(max(self.max_pitch, self.min_pitch + 1) / self.min_pitch)
        freq_raw = self.min_pitch * np.exp(log_ratio * power_norm)

        # Pitch smoothing IIR (same as probe mode)
        _pitch_tc = max(0.001, self.pitch_smoothing_ms / 1000.0)
        _PITCH_ALPHA = 1.0 - math.exp(-1.0 / (SAMPLE_RATE * _pitch_tc))
        freq = np.empty_like(freq_raw)
        freq[0] = self._freq_smooth + _PITCH_ALPHA * (freq_raw[0] - self._freq_smooth)
        for i in range(1, n):
            freq[i] = freq[i - 1] + _PITCH_ALPHA * (freq_raw[i] - freq[i - 1])
        self._freq_smooth = float(freq[-1]) if n > 0 else self._freq_smooth

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

    def _render_probe(
        self,
        outdata: np.ndarray,
        frames: int,
        spectrum: np.ndarray,
    ) -> None:
        """Render probe-mode audio: continuous tone at a fixed position."""
        bins = len(spectrum)
        n = frames

        # Smoothly interpolate position toward target (~10 ms time constant)
        _POS_ALPHA = 1.0 - math.exp(-1.0 / (SAMPLE_RATE * 0.010))
        pos_arr = np.empty(n, dtype=np.float64)
        pos_arr[0] = self._probe_pos + _POS_ALPHA * (self._probe_target - self._probe_pos)
        for i in range(1, n):
            pos_arr[i] = pos_arr[i - 1] + _POS_ALPHA * (self._probe_target - pos_arr[i - 1])
        self._probe_pos = float(pos_arr[-1])

        # Interpolate power at probe position
        noise_floor = float(np.percentile(spectrum, _NOISE_PERCENTILE))
        bin_f  = pos_arr * (bins - 1)
        bin_lo = bin_f.astype(np.intp)
        bin_hi = np.clip(bin_lo + 1, 0, bins - 1)
        frac   = bin_f - bin_lo
        amp_db = spectrum[bin_lo] * (1.0 - frac) + spectrum[bin_hi] * frac

        # Amplitude
        above_floor = np.clip(
            (amp_db - noise_floor) / _DYNAMIC_RANGE_DB, 0.0, 1.0,
        )
        amp_raw = np.sqrt(above_floor) * MAX_AMP

        _SMOOTH_ALPHA = 1.0 - math.exp(-1.0 / (SAMPLE_RATE * 0.003))
        amp = np.empty_like(amp_raw)
        amp[0] = self._amp_smooth + _SMOOTH_ALPHA * (amp_raw[0] - self._amp_smooth)
        for i in range(1, n):
            amp[i] = amp[i - 1] + _SMOOTH_ALPHA * (amp_raw[i] - amp[i - 1])
        self._amp_smooth = float(amp[-1])

        # Pitch
        power_norm = np.clip(
            (amp_db - noise_floor) / _DYNAMIC_RANGE_DB, 0.0, 1.0,
        )
        log_ratio = math.log(max(self.max_pitch, self.min_pitch + 1) / self.min_pitch)
        freq_raw = self.min_pitch * np.exp(log_ratio * power_norm)

        # Pitch smoothing IIR (configurable time constant)
        _pitch_tc = max(0.001, self.pitch_smoothing_ms / 1000.0)
        _PITCH_ALPHA = 1.0 - math.exp(-1.0 / (SAMPLE_RATE * _pitch_tc))
        freq = np.empty_like(freq_raw)
        freq[0] = self._freq_smooth + _PITCH_ALPHA * (freq_raw[0] - self._freq_smooth)
        for i in range(1, n):
            freq[i] = freq[i - 1] + _PITCH_ALPHA * (freq_raw[i] - freq[i - 1])
        self._freq_smooth = float(freq[-1])

        # Pan
        gain_l = np.cos(pos_arr * (np.pi / 2.0))
        gain_r = np.sin(pos_arr * (np.pi / 2.0))

        # Phase accumulation
        phase_inc = freq / SAMPLE_RATE
        phases    = self._phase + np.cumsum(phase_inc)
        self._phase = float(phases[-1]) % 1.0

        two_pi = 2.0 * np.pi
        raw = (np.sin(two_pi * phases)
               + 0.3 * np.sin(2.0 * two_pi * phases)
               + 0.1 * np.sin(3.0 * two_pi * phases))
        tone = (amp / 1.4 * raw).astype(np.float32)
        outdata[:n, 0] = gain_l.astype(np.float32) * tone
        outdata[:n, 1] = gain_r.astype(np.float32) * tone

    def _stream_finished(self) -> None:
        self._stream = None
        cb = self._on_finish_cb
        if cb is not None:
            try:
                cb()
            except Exception:  # noqa: BLE001
                pass
