"""ui/formatting.py — Shared formatting helpers for display strings.

Frequency display convention
----------------------------
Frequencies are displayed in **kHz** below 30 MHz and **MHz** at or above
30 MHz.  This follows the standard ITU / amateur-radio convention where
the 30 MHz mark is the boundary between the HF (High Frequency, 3-30 MHz)
and VHF (Very High Frequency, 30-300 MHz) bands:

- HF and below (< 30 MHz) — stated in kHz.
  Examples: 530 kHz (AM broadcast), 7200 kHz (40 m amateur), 14230 kHz.
- VHF and above (>= 30 MHz) — stated in MHz.
  Examples: 98.100 MHz (FM broadcast), 144.200 MHz (2 m amateur).

This is the universal practice in ITU Radio Regulations, IARU band plans,
aviation/maritime references, and virtually all SDR software.
"""

from __future__ import annotations

import re

_HF_VHF_BOUNDARY = 30_000_000  # 30 MHz — ITU HF/VHF boundary


def fmt_freq(hz: int) -> str:
    """Format Hz with auto-selected unit based on the 30 MHz HF/VHF boundary.

    Below 30 MHz → kHz (integer if exact, else up to 3 decimals).
    At or above 30 MHz → MHz (at least 3 decimals, up to 6 for sub-kHz).

    Examples: "530 kHz", "7200 kHz", "14230.5 kHz", "98.100 MHz".
    """
    if hz < _HF_VHF_BOUNDARY:
        khz = hz / 1_000
        if hz % 1000 == 0:
            return f"{khz:.0f} kHz"
        if hz % 100 == 0:
            return f"{khz:.1f} kHz"
        if hz % 10 == 0:
            return f"{khz:.2f} kHz"
        return f"{khz:.3f} kHz"
    else:
        mhz = hz / 1_000_000
        if hz % 1000 == 0:
            return f"{mhz:.3f} MHz"
        if hz % 100 == 0:
            return f"{mhz:.4f} MHz"
        if hz % 10 == 0:
            return f"{mhz:.5f} MHz"
        return f"{mhz:.6f} MHz"


def freq_unit(hz: int) -> str:
    """Return the display unit for a given frequency: ``"kHz"`` or ``"MHz"``."""
    return "kHz" if hz < _HF_VHF_BOUNDARY else "MHz"


def freq_number(hz: int) -> str:
    """Return the numeric part of the formatted frequency (no unit suffix).

    Matches the unit that :func:`freq_unit` would choose, so this value can
    pre-fill a dialog whose prompt already shows that unit.
    """
    if hz < _HF_VHF_BOUNDARY:
        khz = hz / 1_000
        if hz % 1000 == 0:
            return f"{khz:.0f}"
        if hz % 100 == 0:
            return f"{khz:.1f}"
        if hz % 10 == 0:
            return f"{khz:.2f}"
        return f"{khz:.3f}"
    else:
        mhz = hz / 1_000_000
        if hz % 1000 == 0:
            return f"{mhz:.3f}"
        if hz % 100 == 0:
            return f"{mhz:.4f}"
        if hz % 10 == 0:
            return f"{mhz:.5f}"
        return f"{mhz:.6f}"


_FREQ_RE = re.compile(
    r"^\s*([0-9]+(?:\.[0-9]*)?)\s*(mhz|khz|hz)?\s*$",
    re.IGNORECASE,
)


def parse_freq(text: str, default_unit: str = "mhz") -> int:
    """Parse a user-entered frequency string and return Hz.

    *text* may contain an explicit unit suffix (``MHz``, ``kHz``, ``Hz``).
    When no suffix is present the *default_unit* is used.

    Raises :class:`ValueError` on unparseable input.
    """
    m = _FREQ_RE.match(text)
    if not m:
        raise ValueError(f"Cannot parse frequency: {text!r}")
    value = float(m.group(1))
    unit = (m.group(2) or default_unit).lower()
    if unit == "mhz":
        return int(value * 1_000_000)
    if unit == "khz":
        return int(value * 1_000)
    if unit == "hz":
        return int(value)
    raise ValueError(f"Unknown unit: {unit!r}")
