"""
core/dsp/noise_blanker.py — Impulse noise blanker for raw IQ data.

Suppresses impulse noise (ignition, power line interference) by replacing
samples whose magnitude exceeds a configurable threshold above the RMS
level with linearly interpolated values from surrounding clean samples.
Operates on raw IQ before decimation for maximum effectiveness.
"""

from __future__ import annotations

import numpy as np


class NoiseBlanker:
    """Impulse noise blanker operating on complex IQ samples.

    Uses a sliding-window median for the baseline (more robust than plain
    RMS against bursts) and replaces blanked samples with linear interpolation
    from the nearest clean neighbours rather than hard zeros.
    """

    def __init__(self, threshold: float = 5.0) -> None:
        self._threshold = threshold  # multiplier above median magnitude
        self._enabled = False

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, val: bool) -> None:
        self._enabled = bool(val)

    @property
    def threshold(self) -> float:
        return self._threshold

    @threshold.setter
    def threshold(self, val: float) -> None:
        self._threshold = max(1.0, float(val))

    def process(self, iq: np.ndarray) -> np.ndarray:
        """Replace impulse-noise samples with interpolated values."""
        if not self._enabled:
            return iq
        mag = np.abs(iq)
        # Median is more robust than RMS against impulse bursts
        baseline = np.median(mag)
        if baseline < 1e-10:
            return iq
        limit = baseline * self._threshold
        mask = mag > limit
        if not np.any(mask):
            return iq

        iq = iq.copy()
        # Find indices of blanked samples
        bad = np.flatnonzero(mask)
        # Find indices of clean samples
        good = np.flatnonzero(~mask)
        if len(good) < 2:
            # Nearly all samples bad — just zero
            iq[mask] = 0.0
            return iq
        # Interpolate blanked samples from nearest clean neighbours
        iq.real[bad] = np.interp(bad, good, iq.real[good])
        iq.imag[bad] = np.interp(bad, good, iq.imag[good])
        return iq
