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

import numpy as np
from abc import ABC, abstractmethod
from scipy import signal as sp_signal

from .filters import make_lowpass, make_bandpass, deemphasis_filter

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
    def __init__(self, baseband_rate: int, audio_rate: int) -> None:
        super().__init__(baseband_rate, audio_rate)
        self._deemph_b, self._deemph_a = deemphasis_filter(baseband_rate, tau=75e-6)
        self._lp_b = make_lowpass(15_000, baseband_rate)
        self._lp_a = np.array([1.0])
        # Carry filter state between chunks
        self._zi_deemph = sp_signal.lfilter_zi(self._deemph_b, self._deemph_a) * 0.0
        self._zi_lp = sp_signal.lfilter_zi(self._lp_b, self._lp_a) * 0.0

    def process(self, iq: np.ndarray) -> np.ndarray:
        disc = _fm_discriminant(iq)
        audio, self._zi_deemph = sp_signal.lfilter(
            self._deemph_b, self._deemph_a, disc, zi=self._zi_deemph)
        audio, self._zi_lp = sp_signal.lfilter(
            self._lp_b, self._lp_a, audio, zi=self._zi_lp)
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
