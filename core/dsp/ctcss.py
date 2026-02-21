"""
core/dsp/ctcss.py — CTCSS (Continuous Tone-Coded Squelch System) detector.

Uses the Goertzel algorithm to efficiently detect sub-audible tones
(67.0–254.1 Hz) on NFM channels.  The inner loop is vectorised with numpy
so it runs at C speed despite checking all 50 standard tones.

All 50 standard CTCSS tones per EIA/TIA-603 are supported.
"""

from __future__ import annotations

import numpy as np

# All 50 standard CTCSS tones (Hz) per EIA/TIA-603
CTCSS_TONES = [
    67.0, 69.3, 71.9, 74.4, 77.0, 79.7, 82.5, 85.4, 88.5, 91.5,
    94.8, 97.4, 100.0, 103.5, 107.2, 110.9, 114.8, 118.8, 123.0,
    127.3, 131.8, 136.5, 141.3, 146.2, 151.4, 156.7, 159.8, 162.2,
    165.5, 167.9, 171.3, 173.8, 177.3, 179.9, 183.5, 186.2, 189.9,
    192.8, 196.6, 199.5, 203.5, 206.5, 210.7, 218.1, 225.7, 229.1,
    233.6, 241.8, 250.3, 254.1,
]

# Minimum consecutive detections before reporting a tone (hysteresis)
_CONFIRM_COUNT = 3


def _goertzel_power(block: np.ndarray, freqs: np.ndarray,
                    sample_rate: int, block_size: int) -> np.ndarray:
    """Compute generalised Goertzel power for multiple frequencies at once.

    Uses non-integer k (exact target frequency) for sub-bin resolution,
    critical because CTCSS tones are spaced ~2-3 Hz apart while DFT bin
    spacing at 100 ms blocks is 10 Hz.

    Vectorised with numpy — the Python loop is over samples (not tones).
    """
    n_freqs = len(freqs)
    # Non-integer k → exact frequency targeting (generalised Goertzel)
    w = 2.0 * np.pi * freqs / sample_rate
    coeff = 2.0 * np.cos(w)  # shape (n_freqs,)

    s1 = np.zeros(n_freqs, dtype=np.float64)
    s2 = np.zeros(n_freqs, dtype=np.float64)

    for sample in block:
        s0 = float(sample) + coeff * s1 - s2
        s2 = s1
        s1 = s0

    return s1 * s1 + s2 * s2 - coeff * s1 * s2


class CTCSSDetector:
    """Goertzel-based CTCSS tone detector for demodulated NFM audio."""

    def __init__(self, sample_rate: int) -> None:
        self._sample_rate = sample_rate
        self._detected_tone: float | None = None

        # Block size: ~100 ms of audio (enough cycles of lowest tone 67 Hz)
        self._block_size = int(sample_rate * 0.1)
        self._buffer = np.empty(0, dtype=np.float64)

        # Pre-compute frequency array for vectorised Goertzel
        self._freqs = np.array(CTCSS_TONES, dtype=np.float64)

        # Hysteresis state
        self._candidate: float | None = None
        self._confirm: int = 0

    @property
    def detected_tone(self) -> float | None:
        """Currently detected CTCSS tone frequency, or None."""
        return self._detected_tone

    def process(self, audio: np.ndarray) -> None:
        """Feed demodulated audio. Updates detected_tone property."""
        self._buffer = np.concatenate([self._buffer, audio.astype(np.float64)])

        while len(self._buffer) >= self._block_size:
            block = self._buffer[:self._block_size]
            self._buffer = self._buffer[self._block_size:]
            self._analyse_block(block)

    def _analyse_block(self, block: np.ndarray) -> None:
        """Run Goertzel on one block for all CTCSS tones."""
        # Total power for threshold comparison
        total_power = float(np.sum(np.square(block)))
        if total_power < 1e-10:
            self._update_hysteresis(None)
            return

        powers = _goertzel_power(
            block, self._freqs, self._sample_rate, self._block_size,
        )

        best_idx = int(np.argmax(powers))
        best_power = float(powers[best_idx])

        # CTCSS tones are typically 10-15% of deviation — require meaningful power
        if best_power > total_power * 0.005:
            self._update_hysteresis(CTCSS_TONES[best_idx])
        else:
            self._update_hysteresis(None)

    def _update_hysteresis(self, tone: float | None) -> None:
        """Require N consecutive detections before reporting."""
        if tone == self._candidate:
            self._confirm = min(self._confirm + 1, _CONFIRM_COUNT + 1)
        else:
            self._candidate = tone
            self._confirm = 1 if tone is not None else 0

        if self._confirm >= _CONFIRM_COUNT:
            self._detected_tone = self._candidate
        elif tone is None:
            self._detected_tone = None
