"""
core/dsp/filters.py — Filter construction and application.

Delegates entirely to scipy.signal for all filter design and application:
- scipy.signal.firwin  for FIR low-pass / band-pass design
- scipy.signal.decimate for decimation (FIR or IIR anti-aliasing + downsampling)
- scipy.signal.iirfilter / butter for IIR design (de-emphasis)
- scipy.signal.sosfilt for numerically stable IIR application
"""

from __future__ import annotations

import numpy as np
from scipy import signal


def make_lowpass(cutoff_hz: float, sample_rate: float, num_taps: int = 127) -> np.ndarray:
    """FIR low-pass coefficients via scipy.signal.firwin."""
    nyq = sample_rate / 2.0
    return signal.firwin(num_taps, cutoff_hz / nyq, window="hamming")


def make_bandpass(
    low_hz: float,
    high_hz: float,
    sample_rate: float,
    num_taps: int = 127,
) -> np.ndarray:
    """FIR band-pass coefficients via scipy.signal.firwin."""
    nyq = sample_rate / 2.0
    return signal.firwin(
        num_taps,
        [low_hz / nyq, high_hz / nyq],
        pass_zero=False,
        window="hamming",
    )


def apply_filter(coeffs: np.ndarray, samples: np.ndarray) -> np.ndarray:
    """Apply FIR coefficients with scipy.signal.lfilter."""
    return signal.lfilter(coeffs, [1.0], samples)


def decimate(
    iq: np.ndarray,
    input_rate: int,
    output_rate: int,
) -> np.ndarray:
    """Decimate complex IQ from *input_rate* to *output_rate*.

    Uses scipy.signal.decimate (FIR mode, causal/real-time — zero_phase=False)
    independently on the I and Q channels, then recombines into complex64.
    zero_phase=True doubles the cost and is non-causal; wrong for streaming.
    """
    factor = input_rate // output_rate
    if factor < 1:
        return iq.astype(np.complex64)

    i_dec = signal.decimate(iq.real.astype(np.float64), factor, ftype="fir", zero_phase=False)
    q_dec = signal.decimate(iq.imag.astype(np.float64), factor, ftype="fir", zero_phase=False)

    return (i_dec + 1j * q_dec).astype(np.complex64)


def deemphasis_filter(
    sample_rate: float, tau: float = 75e-6
) -> tuple[np.ndarray, np.ndarray]:
    """First-order IIR de-emphasis filter coefficients (b, a).

    Designed via scipy.signal.bilinear from the analogue prototype
    H(s) = 1 / (1 + s * tau).
    """
    # Analogue prototype coefficients
    b_s = np.array([1.0])
    a_s = np.array([tau, 1.0])
    b, a = signal.bilinear(b_s, a_s, fs=sample_rate)
    return b, a
