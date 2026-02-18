"""
core/dsp/spectrum.py — FFT computation, averaging, and peak detection.

Called from the DSP thread on each IQ chunk. Results are dispatched to
the UI via wx.CallAfter so they never touch wx from a background thread.
"""

from __future__ import annotations

import numpy as np
from typing import List, Tuple


class SpectrumAnalyser:
    """Maintains a running averaged FFT of IQ samples."""

    def __init__(self, fft_size: int = 1024, avg_count: int = 4) -> None:
        self.fft_size = fft_size
        self.avg_count = avg_count
        self._accumulator: np.ndarray = np.zeros(fft_size, dtype=np.float64)
        self._count = 0

    def process(self, iq: np.ndarray) -> np.ndarray:
        """Feed IQ samples; returns averaged magnitude spectrum in dBFS.

        The returned array has *fft_size* elements, DC-centred
        (np.fft.fftshift applied).
        """
        if len(iq) < self.fft_size:
            # Pad with zeros if chunk is smaller than FFT window
            iq = np.concatenate([iq, np.zeros(self.fft_size - len(iq), dtype=iq.dtype)])

        chunk = iq[: self.fft_size]
        window = np.blackman(self.fft_size).astype(np.float32)

        # Apply window to real and imaginary parts separately
        windowed = chunk * window
        spectrum = np.fft.fft(windowed, n=self.fft_size)
        spectrum = np.fft.fftshift(spectrum)

        power = np.abs(spectrum) ** 2
        # Avoid log(0)
        power = np.maximum(power, 1e-20)
        db = 10.0 * np.log10(power)

        # Exponential moving average
        alpha = 1.0 / self.avg_count
        self._accumulator = (1.0 - alpha) * self._accumulator + alpha * db
        self._count += 1

        return self._accumulator.astype(np.float32)

    def reset(self) -> None:
        self._accumulator[:] = 0.0
        self._count = 0

    # ------------------------------------------------------------------
    # Peak detection
    # ------------------------------------------------------------------

    @staticmethod
    def find_peaks(
        spectrum_db: np.ndarray,
        centre_hz: int,
        sample_rate: int,
        n_peaks: int = 5,
        min_db: float = -100.0,
    ) -> List[Tuple[int, float]]:
        """Return up to *n_peaks* (frequency_hz, db) pairs, strongest first.

        Parameters
        ----------
        spectrum_db:
            DC-centred dBFS array of length *fft_size*.
        centre_hz:
            Centre tuning frequency of the SDR.
        sample_rate:
            SDR sample rate in sps (determines Hz/bin).
        n_peaks:
            Maximum number of peaks to return.
        min_db:
            Ignore bins below this threshold.
        """
        fft_size = len(spectrum_db)
        hz_per_bin = sample_rate / fft_size

        # Simple local maxima detection
        from scipy.signal import find_peaks as sp_find_peaks
        indices, _ = sp_find_peaks(spectrum_db, height=min_db, distance=5)

        if len(indices) == 0:
            return []

        # Sort by amplitude descending
        sorted_idx = indices[np.argsort(spectrum_db[indices])[::-1]]
        top_idx = sorted_idx[:n_peaks]

        results = []
        for idx in top_idx:
            offset_hz = int((idx - fft_size / 2) * hz_per_bin)
            freq_hz = centre_hz + offset_hz
            db_val = float(spectrum_db[idx])
            results.append((freq_hz, db_val))

        return results

    @staticmethod
    def signal_strength(spectrum_db: np.ndarray) -> float:
        """Return peak dB value as a proxy for signal strength."""
        return float(np.max(spectrum_db))
