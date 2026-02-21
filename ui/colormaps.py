"""
ui/colormaps.py — CVD-safe colormap LUTs for waterfall display.

Three perceptually-designed colormaps stored as (256, 3) uint8 numpy arrays.
No matplotlib dependency — control points are hardcoded and interpolated
at import time.
"""

from __future__ import annotations

import numpy as np

# Control points: (position_0_to_1, R, G, B) — sampled from reference colormaps.

_VIRIDIS_POINTS = [
    (0.00, 68, 1, 84),
    (0.10, 72, 36, 117),
    (0.20, 65, 68, 135),
    (0.30, 53, 95, 141),
    (0.40, 42, 120, 142),
    (0.50, 33, 145, 140),
    (0.60, 34, 168, 132),
    (0.70, 68, 190, 112),
    (0.80, 122, 209, 81),
    (0.90, 189, 223, 38),
    (1.00, 253, 231, 37),
]

_MAGMA_POINTS = [
    (0.00, 0, 0, 4),
    (0.10, 18, 13, 50),
    (0.20, 56, 15, 99),
    (0.30, 97, 17, 122),
    (0.40, 137, 27, 118),
    (0.50, 175, 47, 107),
    (0.60, 209, 79, 89),
    (0.70, 231, 119, 75),
    (0.80, 246, 165, 84),
    (0.90, 253, 212, 131),
    (1.00, 252, 253, 191),
]


def _build_lut(points: list[tuple[float, int, int, int]]) -> np.ndarray:
    """Interpolate control points into a (256, 3) uint8 lookup table."""
    positions = [p[0] for p in points]
    x = np.linspace(0.0, 1.0, 256)
    lut = np.empty((256, 3), dtype=np.uint8)
    for ch in range(3):
        vals = [p[ch + 1] for p in points]
        lut[:, ch] = np.clip(np.interp(x, positions, vals), 0, 255).astype(np.uint8)
    return lut


_VIRIDIS_LUT = _build_lut(_VIRIDIS_POINTS)
_MAGMA_LUT = _build_lut(_MAGMA_POINTS)
_GRAYSCALE_LUT = np.column_stack([np.arange(256, dtype=np.uint8)] * 3)

COLORMAP_NAMES: list[str] = ["Viridis", "Magma", "Grayscale"]

_COLORMAPS: dict[str, np.ndarray] = {
    "Viridis": _VIRIDIS_LUT,
    "Magma": _MAGMA_LUT,
    "Grayscale": _GRAYSCALE_LUT,
}


def get_colormap(name: str) -> np.ndarray:
    """Return a (256, 3) uint8 colormap LUT. Falls back to Viridis."""
    return _COLORMAPS.get(name, _VIRIDIS_LUT)
