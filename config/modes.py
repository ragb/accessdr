"""config/modes.py — Demodulation mode, bandwidth, and tuning step constants."""

from __future__ import annotations

MODES = ["WFM", "NFM", "AM", "USB", "LSB", "CW", "DSB"]

MODE_KEYS = {
    "W": "WFM", "N": "NFM", "A": "AM",
    "U": "USB", "L": "LSB", "C": "CW", "D": "DSB",
}

STEPS = [1, 10, 100, 1_000, 10_000, 100_000, 1_000_000]

STEP_LABELS = [
    N_("1 Hz"), N_("10 Hz"), N_("100 Hz"), N_("1 kHz"),
    N_("10 kHz"), N_("100 kHz"), N_("1 MHz"),
]

BW_OPTIONS = {
    "WFM":  [(200_000, "200 kHz"), (180_000, "180 kHz"), (150_000, "150 kHz")],
    "NFM":  [(12_500, "12.5 kHz"), (25_000, "25 kHz")],
    "AM":   [(6_000, "6 kHz"), (10_000, "10 kHz")],
    "USB":  [(2_700, "2.7 kHz"), (3_000, "3 kHz")],
    "LSB":  [(2_700, "2.7 kHz"), (3_000, "3 kHz")],
    "CW":   [(500, "500 Hz"), (250, "250 Hz"), (1_000, "1 kHz")],
    "DSB":  [(6_000, "6 kHz"), (10_000, "10 kHz")],
}

AUDIO_RATE = 48_000

BASEBAND_RATE = 240_000  # default; overridden per-session by baseband_rate_for()


def baseband_rate_for(sample_rate: int) -> int:
    """Pick a baseband rate with an exact integer decimation factor.

    Returns sample_rate / factor where factor yields a rate in 200–400 kHz
    that is closest to 240 kHz (the ideal baseband width for WFM).
    """
    best = None
    for factor in range(2, 21):
        if sample_rate % factor == 0:
            bb = sample_rate // factor
            if 200_000 <= bb <= 400_000:
                if best is None or abs(bb - 240_000) < abs(best - 240_000):
                    best = bb
    if best is not None:
        return best
    # Fallback: closest integer factor to 240 kHz target
    factor = max(1, round(sample_rate / 240_000))
    if sample_rate % factor == 0:
        return sample_rate // factor
    return sample_rate  # no decimation
