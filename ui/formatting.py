"""ui/formatting.py — Shared formatting helpers for display strings."""

from __future__ import annotations


def fmt_freq(hz: int) -> str:
    """Format Hz as MHz string with enough precision to show the last digit.

    Examples: 98.100 MHz, 98.1005 MHz, 98.10050 MHz, 98.100500 MHz.
    Always shows at least 3 decimal places (kHz resolution).
    """
    mhz = hz / 1_000_000
    if hz % 1000 == 0:
        return f"{mhz:.3f} MHz"
    if hz % 100 == 0:
        return f"{mhz:.4f} MHz"
    if hz % 10 == 0:
        return f"{mhz:.5f} MHz"
    return f"{mhz:.6f} MHz"
