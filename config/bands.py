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
    # --- LW / MW ---
    N_("AM Broadcast"):      (  530_000,   1_710_000, "AM"),
    # --- HF: amateur (ham) + shortwave broadcast, ascending by frequency ---
    N_("160m Amateur"):      (  1_800_000,   2_000_000, "LSB"),
    N_("90m SW"):            (  3_200_000,   3_400_000, "AM"),
    N_("80m Amateur"):       (  3_500_000,   4_000_000, "LSB"),
    N_("75m SW"):            (  3_900_000,   4_000_000, "AM"),
    N_("60m SW"):            (  4_750_000,   5_060_000, "AM"),
    N_("49m SW"):            (  5_900_000,   6_200_000, "AM"),
    N_("40m Amateur"):       (  7_000_000,   7_300_000, "LSB"),
    N_("41m SW"):            (  7_200_000,   7_450_000, "AM"),
    N_("31m SW"):            (  9_400_000,   9_900_000, "AM"),
    N_("30m Amateur"):       ( 10_100_000,  10_150_000, "CW"),
    N_("25m SW"):            ( 11_600_000,  12_100_000, "AM"),
    N_("22m SW"):            ( 13_570_000,  13_870_000, "AM"),
    N_("20m Amateur"):       ( 14_000_000,  14_350_000, "USB"),
    N_("19m SW"):            ( 15_100_000,  15_830_000, "AM"),
    N_("16m SW"):            ( 17_480_000,  17_900_000, "AM"),
    N_("17m Amateur"):       ( 18_068_000,  18_168_000, "USB"),
    N_("15m Amateur"):       ( 21_000_000,  21_450_000, "USB"),
    N_("13m SW"):            ( 21_450_000,  21_850_000, "AM"),
    N_("12m Amateur"):       ( 24_890_000,  24_990_000, "USB"),
    N_("CB 27 MHz"):         ( 26_965_000,  27_405_000, "AM"),
    N_("10m Amateur"):       ( 28_000_000,  29_700_000, "USB"),
    # --- VHF / UHF ---
    N_("6m Amateur"):        ( 50_000_000,  54_000_000, "USB"),
    N_("FM Broadcast"):      (87_500_000, 108_000_000, "WFM"),
    N_("Air Band"):          (108_000_000, 137_000_000, "AM"),
    N_("2m Amateur"):        (144_000_000, 148_000_000, "NFM"),
    N_("Marine VHF"):        (156_000_000, 174_000_000, "NFM"),
    N_("NOAA Weather"):      (162_400_000, 162_550_000, "NFM"),
    N_("70cm Amateur"):      (420_000_000, 450_000_000, "NFM"),
    N_("PMR446"):            (446_000_000, 446_200_000, "NFM"),
    N_("UHF CB"):            (462_550_000, 467_725_000, "NFM"),
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
