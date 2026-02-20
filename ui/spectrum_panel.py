"""
ui/spectrum_panel.py — Real-time FFT spectrum display with sweep cursor.

Draws a frequency-vs-power line graph and overlays a vertical cursor
that tracks the sonification sweep position.  Visual-only: not in tab
order, no keyboard interaction.
"""

from __future__ import annotations

from typing import Callable, Optional, TYPE_CHECKING

import numpy as np
import wx

if TYPE_CHECKING:
    from accessibility.sonification import Sonification

# Colours
_BG_COLOUR = wx.Colour(0x1E, 0x1E, 0x1E)
_GRID_COLOUR = wx.Colour(0x55, 0x55, 0x55)
_AXIS_COLOUR = wx.Colour(0xFF, 0xFF, 0xFF)
_LINE_BRIGHT = wx.Colour(0x00, 0xE0, 0x40)   # green — "played" portion
_LINE_DIM = wx.Colour(0x00, 0x80, 0x20)       # dimmer green — ahead of cursor
_CURSOR_COLOUR = wx.Colour(0x00, 0xE0, 0xE0)  # cyan cursor
_ZOOM_LINE_COLOUR = wx.Colour(0xFF, 0xFF, 0x00)  # yellow zoom boundaries
_ZOOM_DIM_COLOUR = wx.Colour(0x10, 0x10, 0x10)  # dim outside zoom (solid, no alpha)
_PROBE_CURSOR_COLOUR = wx.Colour(0xFF, 0x80, 0x00)  # orange probe cursor
_DEMOD_MARKER_COLOUR = wx.Colour(0xFF, 0xFF, 0x00)  # yellow demod marker

_MARGIN_LEFT = 48
_MARGIN_RIGHT = 12
_MARGIN_TOP = 10
_MARGIN_BOTTOM = 28
_REFRESH_MS = 33  # ~30 FPS


class SpectrumPanel(wx.Panel):
    """Double-buffered FFT spectrum display with sonification sweep cursor."""

    def __init__(self, parent: wx.Window, sonification: "Sonification") -> None:
        super().__init__(parent, style=wx.NO_BORDER)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.SetMinSize((-1, 200))
        # Remove from tab order — visual only
        self.Disable()
        self.Enable()
        self.AcceptsFocus = lambda: False

        self._son = sonification
        self._spectrum: Optional[np.ndarray] = None
        self._centre_hz: float = 0.0
        self._sample_rate: float = 2_400_000.0
        self._zoom_level: int = 0
        self._cursor_pos: Optional[float] = None   # None = hidden
        self._demod_marker_pos: Optional[float] = None  # None = hidden
        self._on_cursor_click: Optional[Callable[[float], None]] = None

        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_SIZE, self._on_size)
        self.Bind(wx.EVT_LEFT_DOWN, self._on_mouse_click)

        self._timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_timer, self._timer)
        self._timer.Start(_REFRESH_MS)

    def set_data(
        self,
        spectrum: np.ndarray,
        centre_hz: float,
        sample_rate: float,
    ) -> None:
        """Feed new FFT data (called from UI thread)."""
        self._spectrum = spectrum
        self._centre_hz = centre_hz
        self._sample_rate = sample_rate

    def set_zoom(self, level: int) -> None:
        """Set zoom level (0 = full, higher = narrower view)."""
        self._zoom_level = level

    def set_cursor(self, pos: Optional[float]) -> None:
        """Set the probe cursor position (0.0–1.0), or None to hide."""
        self._cursor_pos = pos

    def set_demod_marker(self, pos: Optional[float]) -> None:
        """Set the demod marker position (0.0–1.0), or None to hide."""
        self._demod_marker_pos = pos

    def set_cursor_click_callback(self, cb: Optional[Callable[[float], None]]) -> None:
        """Register a callback for mouse clicks on the spectrum panel."""
        self._on_cursor_click = cb

    def _on_timer(self, _event: wx.TimerEvent) -> None:
        self.Refresh(eraseBackground=False)

    def _on_size(self, event: wx.SizeEvent) -> None:
        self.Refresh(eraseBackground=False)
        event.Skip()

    def _on_mouse_click(self, event: wx.MouseEvent) -> None:
        """Map mouse click x-coordinate to 0.0–1.0 cursor position."""
        w, _h = self.GetClientSize()
        plot_w = w - _MARGIN_LEFT - _MARGIN_RIGHT
        if plot_w < 10:
            return
        x = event.GetX() - _MARGIN_LEFT
        pos = max(0.0, min(1.0, x / plot_w))
        self._cursor_pos = pos
        if self._on_cursor_click is not None:
            self._on_cursor_click(pos)

    def _on_paint(self, _event: wx.PaintEvent) -> None:
        dc = wx.BufferedPaintDC(self)
        w, h = self.GetClientSize()
        if w < 2 or h < 2:
            return

        dc.SetBackground(wx.Brush(_BG_COLOUR))
        dc.Clear()

        plot_x = _MARGIN_LEFT
        plot_y = _MARGIN_TOP
        plot_w = w - _MARGIN_LEFT - _MARGIN_RIGHT
        plot_h = h - _MARGIN_TOP - _MARGIN_BOTTOM

        if plot_w < 10 or plot_h < 10:
            return

        self._draw_grid(dc, plot_x, plot_y, plot_w, plot_h)

        spectrum = self._spectrum
        if spectrum is None or len(spectrum) < 2:
            dc.SetTextForeground(_AXIS_COLOUR)
            dc.SetFont(wx.Font(10, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
            dc.DrawText("No spectrum data", plot_x + plot_w // 2 - 50, plot_y + plot_h // 2 - 8)
            return

        self._draw_spectrum(dc, spectrum, plot_x, plot_y, plot_w, plot_h)

    def _draw_grid(
        self, dc: wx.DC, px: int, py: int, pw: int, ph: int
    ) -> None:
        dc.SetPen(wx.Pen(_GRID_COLOUR, 1, wx.PENSTYLE_DOT))

        # Horizontal grid lines (power dB) — 5 lines at even intervals
        n_h = 5
        for i in range(n_h + 1):
            y = py + int(i * ph / n_h)
            dc.DrawLine(px, y, px + pw, y)

        # Vertical grid lines — 4 divisions
        n_v = 4
        for i in range(n_v + 1):
            x = px + int(i * pw / n_v)
            dc.DrawLine(x, py, x, py + ph)

        # Axis labels
        dc.SetTextForeground(_AXIS_COLOUR)
        font = wx.Font(8, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL)
        dc.SetFont(font)

        # Y-axis (dB) labels
        db_max = 0.0
        db_min = -80.0
        for i in range(n_h + 1):
            db = db_max - i * (db_max - db_min) / n_h
            y = py + int(i * ph / n_h) - 6
            dc.DrawText(f"{db:.0f}", 2, y)

        # X-axis (frequency) labels
        half_bw = self._sample_rate / 2.0
        for i in range(n_v + 1):
            frac = i / n_v
            freq = (self._centre_hz - half_bw) + frac * self._sample_rate
            x = px + int(frac * pw)
            label = f"{freq / 1e6:.2f}"
            tw, _ = dc.GetTextExtent(label)
            dc.DrawText(label, x - tw // 2, py + ph + 4)

        # X-axis unit
        dc.DrawText("MHz", px + pw + 2, py + ph + 4)

    def _draw_spectrum(
        self,
        dc: wx.DC,
        spectrum: np.ndarray,
        px: int,
        py: int,
        pw: int,
        ph: int,
    ) -> None:
        db_max = 0.0
        db_min = -80.0
        n_bins = len(spectrum)

        # Map bins to pixel coordinates
        xs = px + (np.arange(n_bins) / (n_bins - 1) * pw).astype(int)
        clamped = np.clip(spectrum, db_min, db_max)
        ys = py + ((db_max - clamped) / (db_max - db_min) * ph).astype(int)

        # Build point list
        points = list(zip(xs.tolist(), ys.tolist()))

        # Sweep cursor position
        sweep_pos = self._son.sweep_pos  # -1.0 if not sweeping
        sweeping = sweep_pos >= 0.0

        if sweeping:
            cursor_x = px + int(sweep_pos * pw)

            # Split points at cursor: bright (played) vs dim (ahead)
            split_idx = max(1, int(sweep_pos * len(points)))

            # Draw dim portion (ahead of cursor)
            if split_idx < len(points):
                dim_pts = points[max(0, split_idx - 1):]
                if len(dim_pts) >= 2:
                    dc.SetPen(wx.Pen(_LINE_DIM, 2))
                    dc.DrawLines([wx.Point(x, y) for x, y in dim_pts])

            # Draw bright portion (already played)
            bright_pts = points[:split_idx]
            if len(bright_pts) >= 2:
                dc.SetPen(wx.Pen(_LINE_BRIGHT, 2))
                dc.DrawLines([wx.Point(x, y) for x, y in bright_pts])

            # Draw cursor
            dc.SetPen(wx.Pen(_CURSOR_COLOUR, 2))
            dc.DrawLine(cursor_x, py, cursor_x, py + ph)
        else:
            # No sweep — draw all in bright colour
            if len(points) >= 2:
                dc.SetPen(wx.Pen(_LINE_BRIGHT, 2))
                dc.DrawLines([wx.Point(x, y) for x, y in points])

        # Draw zoom boundaries when zoomed in
        if self._zoom_level > 0:
            factor = 2 ** self._zoom_level
            # Zoom region spans centre ± 1/(2·factor) of the plot width
            left_frac = 0.5 - 0.5 / factor
            right_frac = 0.5 + 0.5 / factor
            left_x = px + int(left_frac * pw)
            right_x = px + int(right_frac * pw)

            # Dim regions outside zoom
            dc.SetBrush(wx.Brush(_ZOOM_DIM_COLOUR))
            dc.SetPen(wx.TRANSPARENT_PEN)
            dc.DrawRectangle(px, py, left_x - px, ph)
            dc.DrawRectangle(right_x, py, px + pw - right_x, ph)

            # Draw boundary lines
            dc.SetPen(wx.Pen(_ZOOM_LINE_COLOUR, 2, wx.PENSTYLE_SHORT_DASH))
            dc.DrawLine(left_x, py, left_x, py + ph)
            dc.DrawLine(right_x, py, right_x, py + ph)

        # Draw demod marker (yellow dashed vertical line)
        if self._demod_marker_pos is not None:
            dx = px + int(self._demod_marker_pos * pw)
            dc.SetPen(wx.Pen(_DEMOD_MARKER_COLOUR, 2, wx.PENSTYLE_SHORT_DASH))
            dc.DrawLine(dx, py, dx, py + ph)
            # "D" label
            dc.SetTextForeground(_DEMOD_MARKER_COLOUR)
            font = wx.Font(8, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD)
            dc.SetFont(font)
            tw, th = dc.GetTextExtent("D")
            dlx = min(dx + 2, px + pw - tw)
            dc.DrawText("D", dlx, py + ph - th - 2)

        # Draw probe cursor (orange vertical line)
        if self._cursor_pos is not None:
            cx = px + int(self._cursor_pos * pw)
            dc.SetPen(wx.Pen(_PROBE_CURSOR_COLOUR, 2))
            dc.DrawLine(cx, py, cx, py + ph)
            # Label with frequency
            half_bw = self._sample_rate / 2.0
            cursor_freq = (self._centre_hz - half_bw) + self._cursor_pos * self._sample_rate
            label = f"{cursor_freq / 1e6:.3f}"
            dc.SetTextForeground(_PROBE_CURSOR_COLOUR)
            font = wx.Font(8, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL)
            dc.SetFont(font)
            tw, th = dc.GetTextExtent(label)
            lx = min(cx + 2, px + pw - tw)
            dc.DrawText(label, lx, py + 2)
