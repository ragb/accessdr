"""
core/dsp/mixer.py — Phase-continuous NCO mixer for software VFO offset.

Shifts a complex IQ signal by *offset_hz* using multiplication by
exp(-j·2π·offset·t).  Phase is carried across consecutive calls so there
are no discontinuity clicks at chunk boundaries.
"""

from __future__ import annotations

import numpy as np


class Mixer:
    """Complex NCO mixer with cached LO table.

    The expensive part of mixing is computing cos/sin for every sample.
    This implementation pre-computes the LO waveform table once when the
    offset frequency (or chunk size) changes, then reuses it across chunks
    — only a cheap scalar rotation is needed per chunk to maintain phase
    continuity.

    For a 32 768-sample chunk this eliminates ~65 536 trig calls per chunk
    and replaces them with two complex array multiplies (~6 float ops each
    per element), which are ~10× faster.
    """

    def __init__(self, sample_rate: float) -> None:
        self._sample_rate = sample_rate
        self._phase: float = 0.0          # radians, carried across chunks
        self._cached_offset: float | None = None
        self._lo_table: np.ndarray | None = None
        self._phase_step: float = 0.0     # total phase advance per chunk

    def process(self, iq: np.ndarray, offset_hz: float) -> np.ndarray:
        """Shift *iq* by *-offset_hz*.  Fast-path when offset is zero."""
        if offset_hz == 0.0:
            return iq

        n = len(iq)

        # Rebuild LO table only when offset or chunk size changes
        if (offset_hz != self._cached_offset
                or self._lo_table is None
                or len(self._lo_table) != n):
            inc = -2.0 * np.pi * offset_hz / self._sample_rate
            # Build table in float64 for accuracy, store as complex64
            self._lo_table = np.exp(
                1j * inc * np.arange(n, dtype=np.float64)
            ).astype(np.complex64)
            self._phase_step = inc * n
            self._cached_offset = offset_hz

        # Rotate cached table by current phase (1 scalar exp, 2 array muls)
        rotation = np.complex64(np.exp(1j * self._phase))
        out = iq * (rotation * self._lo_table)

        # Advance phase for next chunk, keep in (-π, π]
        self._phase += self._phase_step
        self._phase %= (2.0 * np.pi)
        if self._phase > np.pi:
            self._phase -= 2.0 * np.pi

        return out

    def reset(self) -> None:
        """Zero the phase accumulator (call on hard jumps like C key)."""
        self._phase = 0.0
