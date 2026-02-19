"""
core/dsp/demodulator.py — Stateful demodulators for common radio modes.

Each mode is encapsulated in a Demodulator subclass that:
  - pre-computes all filter coefficients once at construction
  - carries lfilter zi (initial conditions) between calls so there are no
    transient discontinuities at chunk boundaries (the main cause of crackle)

Public API
----------
    dem = make_demodulator("WFM", baseband_rate=240_000, audio_rate=48_000)
    audio_f32 = dem.process(iq_complex64)  # called repeatedly per chunk
"""

from __future__ import annotations

import logging
import numpy as np
from abc import ABC, abstractmethod
from scipy import signal as sp_signal

from .filters import make_lowpass, make_bandpass, deemphasis_filter

logger = logging.getLogger(__name__)

AUDIO_RATE = 48_000


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------

class Demodulator(ABC):
    """Abstract base — subclasses implement process()."""

    def __init__(self, baseband_rate: int, audio_rate: int) -> None:
        self.baseband_rate = baseband_rate
        self.audio_rate = audio_rate
        self._resample_up, self._resample_down = _resample_ratio(baseband_rate, audio_rate)

    @abstractmethod
    def process(self, iq: np.ndarray) -> np.ndarray:
        """Demodulate *iq* (complex64) → float32 audio at audio_rate."""

    def _resample(self, audio: np.ndarray) -> np.ndarray:
        """Resample from baseband_rate to audio_rate (polyphase, integer ratio)."""
        if self._resample_up == self._resample_down:
            return audio.astype(np.float32)
        return sp_signal.resample_poly(audio, self._resample_up, self._resample_down).astype(np.float32)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resample_ratio(in_rate: int, out_rate: int):
    from math import gcd
    g = gcd(in_rate, out_rate)
    return out_rate // g, in_rate // g


def _fm_discriminant(iq: np.ndarray) -> np.ndarray:
    """Instantaneous frequency via conjugate-product polar discriminant."""
    delayed = np.empty_like(iq)
    delayed[0] = iq[0]
    delayed[1:] = iq[:-1]
    return np.angle(iq * np.conj(delayed))


def _make_zi(b, a, n: int) -> np.ndarray:
    """Initial filter state (zi) for lfilter — length max(len(a),len(b))-1."""
    return sp_signal.lfilter_zi(b, a) * 0.0


# ---------------------------------------------------------------------------
# WFM
# ---------------------------------------------------------------------------

class WFMDemodulator(Demodulator):
    """Wide-band FM demodulator with automatic MPX stereo decoding.

    Stereo decoding is active whenever a 19 kHz pilot tone is detected above
    _PILOT_THRESHOLD.  When stereo, process() returns a (N, 2) float32 array
    with left in column 0 and right in column 1.  When mono, it returns (N,).

    MPX signal structure (IEC 60268-3 / NRSC-4):
      0–15 kHz   — L+R (mono sum)
      19 kHz     — stereo pilot (always present on stereo stations)
      23–53 kHz  — (L-R) DSB-SC centred at 38 kHz
    """

    # Pilot RMS threshold in FM-discriminant units (rad/sample).
    # Typical broadcast pilot is ~0.05–0.15; threshold of 0.004 is safe.
    _PILOT_THRESHOLD = 0.004

    def __init__(self, baseband_rate: int, audio_rate: int) -> None:
        super().__init__(baseband_rate, audio_rate)
        rate = baseband_rate

        # Shared de-emphasis filter (75 µs, standard for WFM)
        self._deemph_b, self._deemph_a = deemphasis_filter(rate, tau=75e-6)

        # L+R extraction: LPF 0–15 kHz
        self._lpr_b = make_lowpass(15_000, rate, num_taps=127)
        self._lpr_a = np.array([1.0])

        # 19 kHz pilot BPF — narrow bandwidth needs many taps for selectivity
        # 1023 taps at 240 kHz → transition BW ≈ 1.9 kHz (clears 15 kHz mono
        # content and 23 kHz L-R subcarrier)
        self._pilot_b = make_bandpass(18_000, 20_000, rate, num_taps=1023)
        self._pilot_a = np.array([1.0])

        # L-R DSB-SC subcarrier BPF (23–53 kHz)
        self._lmr_b = make_bandpass(23_000, 53_000, rate, num_taps=511)
        self._lmr_a = np.array([1.0])

        # Post-demodulation LPF: removes 76 kHz image after product detection
        self._lmr_lp_b = make_lowpass(15_000, rate, num_taps=127)
        self._lmr_lp_a = np.array([1.0])

        # Filter states — zero-initialised, carried between chunks
        self._zi_lpr     = sp_signal.lfilter_zi(self._lpr_b,    self._lpr_a)    * 0.0
        self._zi_pilot   = sp_signal.lfilter_zi(self._pilot_b,  self._pilot_a)  * 0.0
        self._zi_lmr     = sp_signal.lfilter_zi(self._lmr_b,    self._lmr_a)    * 0.0
        self._zi_lmr_lp  = sp_signal.lfilter_zi(self._lmr_lp_b, self._lmr_lp_a)* 0.0
        self._zi_deemph_l = sp_signal.lfilter_zi(self._deemph_b, self._deemph_a)* 0.0
        self._zi_deemph_r = sp_signal.lfilter_zi(self._deemph_b, self._deemph_a)* 0.0

        self.stereo_detected: bool = False

    def process(self, iq: np.ndarray) -> np.ndarray:
        # FM discriminant → MPX baseband (rad/sample)
        mpx = _fm_discriminant(iq)

        # Extract L+R (mono sum, 0–15 kHz)
        lpr, self._zi_lpr = sp_signal.lfilter(
            self._lpr_b, self._lpr_a, mpx, zi=self._zi_lpr)

        # Extract 19 kHz pilot
        pilot, self._zi_pilot = sp_signal.lfilter(
            self._pilot_b, self._pilot_a, mpx, zi=self._zi_pilot)

        # Stereo detection: pilot RMS above threshold
        pilot_rms = float(np.sqrt(np.mean(pilot ** 2))) if len(pilot) > 0 else 0.0
        self.stereo_detected = pilot_rms > self._PILOT_THRESHOLD
        logger.debug("pilot_rms=%.4f stereo=%s", pilot_rms, self.stereo_detected)

        if self.stereo_detected:
            return self._process_stereo(mpx, lpr, pilot)
        else:
            return self._process_mono(lpr)

    # ------------------------------------------------------------------

    def _process_stereo(
        self, mpx: np.ndarray, lpr: np.ndarray, pilot: np.ndarray
    ) -> np.ndarray:
        # Generate a unit-amplitude 38 kHz reference by squaring the analytic
        # pilot signal.  pilot_analytic = A·e^(j·2π·19k·t + φ), so squaring
        # gives A²·e^(j·2π·38k·t + 2φ) which, after normalisation, is the
        # coherent carrier needed for DSB-SC demodulation.
        pilot_analytic = sp_signal.hilbert(pilot)
        ref = pilot_analytic ** 2
        ref_norm_real = (ref / (np.abs(ref) + 1e-10)).real   # cos(2π·38k·t)

        # Extract L-R DSB-SC subcarrier (23–53 kHz)
        lmr_band, self._zi_lmr = sp_signal.lfilter(
            self._lmr_b, self._lmr_a, mpx, zi=self._zi_lmr)

        # Product demodulation → baseband L-R + 76 kHz image
        lmr_product = lmr_band * ref_norm_real * 2.0

        # LPF to remove the 76 kHz image
        lmr, self._zi_lmr_lp = sp_signal.lfilter(
            self._lmr_lp_b, self._lmr_lp_a, lmr_product, zi=self._zi_lmr_lp)

        # Stereo matrix: L = (L+R) + (L-R),  R = (L+R) - (L-R)
        left  = lpr + lmr
        right = lpr - lmr

        # De-emphasis on each channel independently
        left,  self._zi_deemph_l = sp_signal.lfilter(
            self._deemph_b, self._deemph_a, left,  zi=self._zi_deemph_l)
        right, self._zi_deemph_r = sp_signal.lfilter(
            self._deemph_b, self._deemph_a, right, zi=self._zi_deemph_r)

        left_out  = self._resample(left)
        right_out = self._resample(right)
        return np.stack([left_out, right_out], axis=1).astype(np.float32)

    def _process_mono(self, lpr: np.ndarray) -> np.ndarray:
        audio, self._zi_deemph_l = sp_signal.lfilter(
            self._deemph_b, self._deemph_a, lpr, zi=self._zi_deemph_l)
        return self._resample(audio)


# ---------------------------------------------------------------------------
# NFM
# ---------------------------------------------------------------------------

class NFMDemodulator(Demodulator):
    def __init__(self, baseband_rate: int, audio_rate: int) -> None:
        super().__init__(baseband_rate, audio_rate)
        self._lp_b = make_lowpass(8_000, baseband_rate)
        self._lp_a = np.array([1.0])
        self._zi_lp = sp_signal.lfilter_zi(self._lp_b, self._lp_a) * 0.0

    def process(self, iq: np.ndarray) -> np.ndarray:
        disc = _fm_discriminant(iq)
        audio, self._zi_lp = sp_signal.lfilter(
            self._lp_b, self._lp_a, disc, zi=self._zi_lp)
        return self._resample(audio)


# ---------------------------------------------------------------------------
# AM
# ---------------------------------------------------------------------------

class AMDemodulator(Demodulator):
    def __init__(self, baseband_rate: int, audio_rate: int) -> None:
        super().__init__(baseband_rate, audio_rate)
        self._lp_b = make_lowpass(5_000, baseband_rate)
        self._lp_a = np.array([1.0])
        self._zi_lp = sp_signal.lfilter_zi(self._lp_b, self._lp_a) * 0.0
        self._dc_b = np.array([1.0, -1.0])   # simple DC block
        self._dc_a = np.array([1.0, -0.9995])
        self._zi_dc = sp_signal.lfilter_zi(self._dc_b, self._dc_a) * 0.0

    def process(self, iq: np.ndarray) -> np.ndarray:
        envelope = np.abs(iq).astype(np.float64)
        audio, self._zi_dc = sp_signal.lfilter(
            self._dc_b, self._dc_a, envelope, zi=self._zi_dc)
        audio, self._zi_lp = sp_signal.lfilter(
            self._lp_b, self._lp_a, audio, zi=self._zi_lp)
        return self._resample(audio)


# ---------------------------------------------------------------------------
# USB / LSB
# ---------------------------------------------------------------------------

class SSBDemodulator(Demodulator):
    def __init__(self, baseband_rate: int, audio_rate: int, upper: bool) -> None:
        super().__init__(baseband_rate, audio_rate)
        self._upper = upper

    def process(self, iq: np.ndarray) -> np.ndarray:
        i = iq.real.astype(np.float64)
        q_h = sp_signal.hilbert(i).imag
        audio = (i - q_h) if self._upper else (i + q_h)
        return self._resample(audio)


# ---------------------------------------------------------------------------
# CW
# ---------------------------------------------------------------------------

class CWDemodulator(Demodulator):
    def __init__(self, baseband_rate: int, audio_rate: int) -> None:
        super().__init__(baseband_rate, audio_rate)
        self._bp_b = make_bandpass(600, 1_000, baseband_rate)
        self._bp_a = np.array([1.0])
        self._zi_bp = sp_signal.lfilter_zi(self._bp_b, self._bp_a) * 0.0
        self._phase = 0.0

    def process(self, iq: np.ndarray) -> np.ndarray:
        real = iq.real.astype(np.float64)
        filtered, self._zi_bp = sp_signal.lfilter(
            self._bp_b, self._bp_a, real, zi=self._zi_bp)
        envelope = np.abs(sp_signal.hilbert(filtered))
        t = np.arange(len(envelope)) / self.baseband_rate
        # Stateful phase to avoid discontinuity between chunks
        phase_vec = 2.0 * np.pi * 700.0 * t + self._phase
        self._phase = float(phase_vec[-1]) % (2.0 * np.pi)
        tone = envelope * np.sin(phase_vec)
        return self._resample(tone)


# ---------------------------------------------------------------------------
# DSB
# ---------------------------------------------------------------------------

class DSBDemodulator(Demodulator):
    def __init__(self, baseband_rate: int, audio_rate: int) -> None:
        super().__init__(baseband_rate, audio_rate)
        self._lp_b = make_lowpass(5_000, baseband_rate)
        self._lp_a = np.array([1.0])
        self._zi_lp = sp_signal.lfilter_zi(self._lp_b, self._lp_a) * 0.0

    def process(self, iq: np.ndarray) -> np.ndarray:
        audio = iq.real.astype(np.float64)
        audio, self._zi_lp = sp_signal.lfilter(
            self._lp_b, self._lp_a, audio, zi=self._zi_lp)
        return self._resample(audio)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

_MODE_MAP = {
    "WFM": WFMDemodulator,
    "NFM": NFMDemodulator,
    "AM":  AMDemodulator,
    "USB": lambda br, ar: SSBDemodulator(br, ar, upper=True),
    "LSB": lambda br, ar: SSBDemodulator(br, ar, upper=False),
    "CW":  CWDemodulator,
    "DSB": DSBDemodulator,
}


def make_demodulator(mode: str, baseband_rate: int, audio_rate: int = AUDIO_RATE) -> Demodulator:
    """Return a fresh stateful Demodulator for *mode*."""
    cls = _MODE_MAP.get(mode.upper())
    if cls is None:
        raise ValueError(f"Unknown mode: {mode!r}")
    return cls(baseband_rate, audio_rate)


# ---------------------------------------------------------------------------
# Thin compatibility shim (used by old call sites if any)
# ---------------------------------------------------------------------------

def demodulate(
    iq: np.ndarray,
    mode: str,
    baseband_rate: int,
    audio_rate: int = AUDIO_RATE,
) -> np.ndarray:
    """Stateless convenience wrapper — creates a fresh demodulator each call.

    For real-time use, prefer make_demodulator() + dem.process() to preserve
    filter state across chunks.
    """
    dem = make_demodulator(mode, baseband_rate, audio_rate)
    return dem.process(iq)
