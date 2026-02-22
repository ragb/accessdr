"""core/signal_utils.py — Signal measurement utilities."""

from __future__ import annotations


def s_meter(db_fs: float) -> str:
    """Return S-unit string for an IQ power level (dBFS, approximate for RTL-SDR)."""
    if db_fs >= -5:
        return "S9+30"
    if db_fs >= -10:
        return "S9+20"
    if db_fs >= -15:
        return "S9+10"
    if db_fs >= -20:
        return "S9"
    if db_fs >= -26:
        return "S8"
    if db_fs >= -32:
        return "S7"
    if db_fs >= -38:
        return "S6"
    if db_fs >= -44:
        return "S5"
    if db_fs >= -50:
        return "S4"
    if db_fs >= -56:
        return "S3"
    if db_fs >= -62:
        return "S2"
    if db_fs >= -68:
        return "S1"
    return "S0"
