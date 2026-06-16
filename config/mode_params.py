"""
config/mode_params.py — declarative per-mode settings registry.

Each demodulation mode declares the settings it supports. The same
attribute names are used on the global ``Settings`` (concrete values) and
as optional overrides on a band (``Scene``) or a ``Channel`` (None means
"inherit the global setting"), so one generic editor and one apply step
work everywhere.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple


@dataclass
class ModeParam:
    key: str                       # attribute name on Settings/Scene/Channel
    label: str
    kind: str                      # "choice" | "bool" | "int"
    choices: Optional[List[Tuple[str, str]]] = None   # (value, label) for choice
    min: int = 0
    max: int = 0


MODE_PARAMS: dict[str, List[ModeParam]] = {
    "WFM": [
        ModeParam("wfm_deemphasis", N_("De-emphasis"), "choice",
                  [("auto", N_("Auto")), ("50", "50 µs"), ("75", "75 µs")]),
        ModeParam("wfm_stereo_mode", N_("Stereo"), "choice",
                  [("auto", N_("Auto")), ("mono", N_("Mono")), ("stereo", N_("Stereo"))]),
        ModeParam("wfm_hiblend_enabled", N_("HF noise cut (hi-blend)"), "bool"),
        ModeParam("wfm_rds_enabled", N_("RDS decoding"), "bool"),
    ],
    "NFM": [
        ModeParam("nfm_deviation", N_("Deviation (Hz)"), "int", min=1_000, max=10_000),
        ModeParam("nfm_ctcss_notch", N_("Remove CTCSS tone"), "bool"),
    ],
    # AM / USB / LSB / CW / DSB have no mode-specific settings (yet).
}


def params_for(mode: str) -> List[ModeParam]:
    """Settings parameters for *mode* (empty if the mode has none)."""
    return MODE_PARAMS.get(mode, [])
