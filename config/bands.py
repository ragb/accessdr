"""
config/bands.py — Frequency band definitions.

Each entry maps a human-readable name to (min_freq_hz, max_freq_hz, default_mode).
Band names are marked with ``N_()`` for xgettext extraction; use ``_(name)``
at display time (e.g. when building menus).
"""

from typing import Dict, Tuple

# (min_hz, max_hz, default_mode)
BandEntry = Tuple[int, int, str]

BANDS: Dict[str, BandEntry] = {
    N_("AM Broadcast"):      (  530_000,   1_710_000, "AM"),
    N_("FM Broadcast"):      (87_500_000, 108_000_000, "WFM"),
    N_("Air Band"):          (108_000_000, 137_000_000, "AM"),
    N_("2m Amateur"):        (144_000_000, 148_000_000, "NFM"),
    N_("NOAA Weather"):      (162_400_000, 162_550_000, "NFM"),
    N_("Marine VHF"):        (156_000_000, 174_000_000, "NFM"),
    N_("UHF CB"):            (462_550_000, 467_725_000, "NFM"),
    N_("70cm Amateur"):      (420_000_000, 450_000_000, "NFM"),
    N_("PMR446"):            (446_000_000, 446_200_000, "NFM"),
    N_("GSM 900 Uplink"):    (890_000_000, 915_000_000, "NFM"),
    N_("GSM 900 Downlink"):  (935_000_000, 960_000_000, "NFM"),
    N_("DECT"):              (1_880_000_000, 1_900_000_000, "NFM"),
}

# Ordered list for menu building
BAND_NAMES = list(BANDS.keys())


def get_band(name: str) -> BandEntry:
    """Return (min_hz, max_hz, mode) for the named band."""
    return BANDS[name]


def centre_frequency(name: str) -> int:
    """Return the centre frequency of a band in Hz."""
    lo, hi, _ = BANDS[name]
    return (lo + hi) // 2
