"""config/locale_utils.py — Locale-dependent radio defaults."""

from __future__ import annotations


def detect_deemphasis_tau() -> float:
    """Return the correct de-emphasis time constant for the user's region.

    50 µs — Europe, UK, Australia, most of the world.
    75 µs — Americas, Japan, South Korea.
    """
    import locale
    try:
        loc = locale.getdefaultlocale()[0] or ""
    except Exception:  # noqa: BLE001
        loc = ""
    loc = loc.lower().replace("-", "_")
    # 75 µs regions (prefix match)
    if any(loc.startswith(p) for p in (
        "en_us", "en_ca", "fr_ca", "es_mx", "es_ar", "es_cl", "es_co",
        "es_ve", "es_pe", "es_ec", "pt_br", "ja", "ko",
    )):
        return 75e-6
    return 50e-6
