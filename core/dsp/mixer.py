"""
core/dsp/mixer.py — Phase-continuous NCO mixer for software VFO offset.

Shifts a complex IQ signal by *offset_hz* using multiplication by
exp(-j·2π·offset·t).  Phase is carried across consecutive calls so there
are no discontinuity clicks at chunk boundaries.
"""

from __future__ import annotations

import numpy as np


class Mixer:
    """Complex NCO mixer with phase-continuous output."""

    def __init__(self, sample_rate: float) -> None:
        self._sample_rate = sample_rate
        self._phase: float = 0.0          # radians, carried across chunks

    def process(self, iq: np.ndarray, offset_hz: float) -> np.ndarray:
        """Shift *iq* by *-offset_hz*.  Fast-path when offset is zero."""
        if offset_hz == 0.0:
            return iq

        n = len(iq)
        t = np.arange(n, dtype=np.float64) / self._sample_rate
        phase = self._phase + (-2.0 * np.pi * offset_hz) * t
        lo = np.exp(1j * phase).astype(np.complex64)

        # Advance phase for next chunk, keep in (-π, π] to avoid float drift
        self._phase = float(phase[-1] + (-2.0 * np.pi * offset_hz) / self._sample_rate)
        self._phase %= (2.0 * np.pi)
        if self._phase > np.pi:
            self._phase -= 2.0 * np.pi

        return iq * lo

    def reset(self) -> None:
        """Zero the phase accumulator (call on hard jumps like C key)."""
        self._phase = 0.0
