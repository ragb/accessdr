"""
config/bands.py — Frequency band definitions (the default band plan).

Each entry maps a human-readable name to a full band spec:
``(min_freq_hz, max_freq_hz, mode, bandwidth_hz, step_hz, group)`` with an
optional trailing dict of per-mode overrides
(``nfm_deviation`` / ``wfm_deemphasis`` / ``squelch``), e.g. PMR446's narrow
2.5 kHz deviation.

``group`` is the service category used to build the Bands tree
(see :data:`GROUP_ORDER`). Defining bandwidth/step/overrides per band
(rather than deriving them from the mode) lets each band carry its own
raster and quirks.

Band names and group names are marked with ``N_()`` for xgettext
extraction; they are stored verbatim as band (scene) data.
"""

from typing import Dict, List, Tuple

# (min_hz, max_hz, mode, bandwidth_hz, step_hz, group[, {overrides}])
BandEntry = Tuple

# Service categories, in the order they appear in the Bands tree.
GROUP_ORDER: List[str] = [
    N_("Broadcast"),
    N_("Shortwave"),
    N_("Amateur"),
    N_("Aircraft / Marine"),
    N_("PMR / CB"),
    N_("Weather / Other"),
]

_BC = N_("Broadcast")
_SW = N_("Shortwave")
_HAM = N_("Amateur")
_AM = N_("Aircraft / Marine")
_CB = N_("PMR / CB")
_OT = N_("Weather / Other")

BANDS: Dict[str, BandEntry] = {
    # --- MW ---
    N_("AM Radio"):   (   530_000,   1_710_000, "AM",  10_000,   9_000, _BC),
    # --- HF: ham + shortwave broadcast, ascending by frequency ---
    N_("160m Ham"):   (  1_800_000,   2_000_000, "LSB",  2_700,   1_000, _HAM),
    N_("90m SW"):     (  3_200_000,   3_400_000, "AM",   6_000,   5_000, _SW),
    N_("80m Ham"):    (  3_500_000,   4_000_000, "LSB",  2_700,   1_000, _HAM),
    N_("75m SW"):     (  3_900_000,   4_000_000, "AM",   6_000,   5_000, _SW),
    N_("60m SW"):     (  4_750_000,   5_060_000, "AM",   6_000,   5_000, _SW),
    N_("49m SW"):     (  5_900_000,   6_200_000, "AM",   6_000,   5_000, _SW),
    N_("40m Ham"):    (  7_000_000,   7_300_000, "LSB",  2_700,   1_000, _HAM),
    N_("41m SW"):     (  7_200_000,   7_450_000, "AM",   6_000,   5_000, _SW),
    N_("31m SW"):     (  9_400_000,   9_900_000, "AM",   6_000,   5_000, _SW),
    N_("30m Ham"):    ( 10_100_000,  10_150_000, "CW",     500,     100, _HAM),
    N_("25m SW"):     ( 11_600_000,  12_100_000, "AM",   6_000,   5_000, _SW),
    N_("22m SW"):     ( 13_570_000,  13_870_000, "AM",   6_000,   5_000, _SW),
    N_("20m Ham"):    ( 14_000_000,  14_350_000, "USB",  2_700,   1_000, _HAM),
    N_("19m SW"):     ( 15_100_000,  15_830_000, "AM",   6_000,   5_000, _SW),
    N_("16m SW"):     ( 17_480_000,  17_900_000, "AM",   6_000,   5_000, _SW),
    N_("17m Ham"):    ( 18_068_000,  18_168_000, "USB",  2_700,   1_000, _HAM),
    N_("15m Ham"):    ( 21_000_000,  21_450_000, "USB",  2_700,   1_000, _HAM),
    N_("13m SW"):     ( 21_450_000,  21_850_000, "AM",   6_000,   5_000, _SW),
    N_("12m Ham"):    ( 24_890_000,  24_990_000, "USB",  2_700,   1_000, _HAM),
    N_("CB 27m"):     ( 26_965_000,  27_405_000, "AM",   6_000,  10_000, _CB),
    N_("10m Ham"):    ( 28_000_000,  29_700_000, "USB",  2_700,   1_000, _HAM),
    # --- VHF / UHF ---
    N_("6m Ham"):     ( 50_000_000,  54_000_000, "USB",  2_700,   1_000, _HAM),
    N_("FM Radio"):   ( 87_500_000, 108_000_000, "WFM", 200_000, 100_000, _BC),
    N_("Airband"):    (108_000_000, 137_000_000, "AM",   10_000,  25_000, _AM),
    N_("2m Ham"):     (144_000_000, 148_000_000, "NFM",  12_500,  12_500, _HAM),
    N_("Marine"):     (156_000_000, 174_000_000, "NFM",  12_500,  25_000, _AM),
    N_("NOAA WX"):    (162_400_000, 162_550_000, "NFM",  12_500,  25_000, _OT),
    N_("70cm Ham"):   (420_000_000, 450_000_000, "NFM",  12_500,  12_500, _HAM),
    N_("PMR446"):     (446_000_000, 446_200_000, "NFM",  12_500,  12_500, _CB,
                       {"nfm_deviation": 2_500}),
    N_("UHF CB"):     (462_550_000, 467_725_000, "NFM",  12_500,  12_500, _CB),
    N_("GSM Up"):     (890_000_000, 915_000_000, "NFM",  12_500, 200_000, _OT),
    N_("GSM Down"):   (935_000_000, 960_000_000, "NFM",  12_500, 200_000, _OT),
    N_("DECT"):       (1_880_000_000, 1_900_000_000, "NFM", 12_500, 1_728_000, _OT),
}
