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


# ---------------------------------------------------------------------------
# IIR filter design (Butterworth, SOS form for numerical stability)
# ---------------------------------------------------------------------------

def make_lowpass_iir(
    cutoff_hz: float, sample_rate: float, order: int = 4,
) -> np.ndarray:
    """Butterworth lowpass in second-order-sections form."""
    return signal.butter(order, cutoff_hz, btype="low", fs=sample_rate, output="sos")


def make_bandpass_iir(
    low_hz: float, high_hz: float, sample_rate: float, order: int = 4,
) -> np.ndarray:
    """Butterworth bandpass in second-order-sections form.

    *order* is per band-edge; the total filter order is 2 × *order*.
    """
    return signal.butter(order, [low_hz, high_hz], btype="bandpass",
                         fs=sample_rate, output="sos")


def decimate(
    iq: np.ndarray,
    input_rate: int,
    output_rate: int,
) -> np.ndarray:
    """Decimate complex IQ from *input_rate* to *output_rate*.

    Uses ``resample_poly(x, 1, factor)`` which internally decomposes the
    anti-aliasing FIR into a polyphase filter bank — only the output samples
    are actually computed.  For a decimation factor of *N* this is roughly
    *N*× cheaper than ``scipy.signal.decimate`` which filters all input
    samples before discarding N-1 out of every N.
    """
    factor = input_rate // output_rate
    if factor <= 1:
        return iq.astype(np.complex64)

    i_dec = signal.resample_poly(iq.real, 1, factor).astype(np.float32)
    q_dec = signal.resample_poly(iq.imag, 1, factor).astype(np.float32)

    return (i_dec + 1j * q_dec).astype(np.complex64)


class StatefulDecimator:
    """IIR anti-alias + integer downsample with state carried across calls.

    Eliminates the chunk-boundary transients and downsample-phase jumps
    that stateless ``resample_poly`` causes (audible as periodic clicks).
    """

    def __init__(self, factor: int, input_rate: int, order: int = 8) -> None:
        self._factor = factor
        cutoff = input_rate / factor * 0.45  # 90% of output Nyquist
        self._sos = signal.butter(order, cutoff, btype="low", fs=input_rate, output="sos")
        self._zi_i = signal.sosfilt_zi(self._sos) * 0.0
        self._zi_q = signal.sosfilt_zi(self._sos) * 0.0
        self._offset = 0  # downsample phase tracking

    def process(self, iq: np.ndarray) -> np.ndarray:
        """Decimate complex IQ by the configured factor."""
        i_f, self._zi_i = signal.sosfilt(self._sos, iq.real, zi=self._zi_i)
        q_f, self._zi_q = signal.sosfilt(self._sos, iq.imag, zi=self._zi_q)
        i_out = i_f[self._offset :: self._factor].astype(np.float32)
        q_out = q_f[self._offset :: self._factor].astype(np.float32)
        self._offset = (self._offset + len(i_out) * self._factor) - len(iq)
        return (i_out + 1j * q_out).astype(np.complex64)


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
