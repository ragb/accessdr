"""ui/cursor_controller.py — Spectrum cursor and software VFO offset.

Manages the spectrum cursor state machine (Ctrl-hold probe tone,
arrow-key movement), VFO offset tracking, and the demod marker on
the spectrum panel.  Owns the wx.Timer for polling Ctrl/arrow state.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Callable, Optional

import numpy as np
import wx

from accessibility import speech
from core.signal_utils import s_meter
from ui.formatting import fmt_freq

if TYPE_CHECKING:
    from config.settings import Settings
    from accessibility.sonification import Sonification
    from core.dsp.pipeline import DSPPipeline
    from ui.spectrum_controller import SpectrumController
    from ui.spectrum_panel import SpectrumPanel


class CursorController:
    """Spectrum cursor state machine and software VFO offset management."""

    def __init__(
        self,
        parent: wx.Window,
        settings: Settings,
        sonification: Sonification,
        spectrum_panel: SpectrumPanel,
        spectrum_ctrl: SpectrumController,
        *,
        tune_cb: Callable[[int], None],
        duck_cb: Callable[[float], None],
        freq_ctrl: wx.TextCtrl,
        is_active_cb: Callable[[], bool] = lambda: True,
    ) -> None:
        self._parent = parent
        self._settings = settings
        self._sonification = sonification
        self._panel = spectrum_panel
        self._spectrum = spectrum_ctrl
        self._tune_cb = tune_cb
        self._duck_cb = duck_cb
        self._freq_ctrl = freq_ctrl
        # The cursor/probe only operate where the spectrum is shown (VFO mode).
        self._is_active_cb = is_active_cb

        # Cursor state
        self._cursor_pos: float = 0.5
        self._cursor_active: bool = False
        self._ctrl_was_down: bool = False
        self._cursor_last_time: float = 0.0

        # Software VFO offset
        self._demod_offset: float = 0.0
        self._pipeline: Optional[DSPPipeline] = None

        # Timer for Ctrl/arrow polling
        self._timer = wx.Timer(parent)
        parent.Bind(wx.EVT_TIMER, self._on_timer, self._timer)
        self._timer.Start(50)

    # ------------------------------------------------------------------
    # Pipeline binding (set after radio start, cleared on stop)
    # ------------------------------------------------------------------

    def set_pipeline(self, pipeline: Optional[DSPPipeline]) -> None:
        self._pipeline = pipeline
        if pipeline is None:
            self._demod_offset = 0.0

    # ------------------------------------------------------------------
    # Read-only properties
    # ------------------------------------------------------------------

    @property
    def demod_offset(self) -> float:
        return self._demod_offset

    @property
    def cursor_active(self) -> bool:
        return self._cursor_active

    @property
    def cursor_pos(self) -> float:
        return self._cursor_pos

    # ------------------------------------------------------------------
    # Cursor frequency / power helpers
    # ------------------------------------------------------------------

    def cursor_freq(self) -> int:
        """Convert cursor position (0.0-1.0) to Hz within zoomed range."""
        start_hz, end_hz = self._spectrum.spectrum_range()
        span = end_hz - start_hz
        return int(start_hz + self._cursor_pos * span)

    def cursor_db(self, last_spectrum: Optional[np.ndarray]) -> float:
        """Interpolate spectrum power at the cursor position (dBFS)."""
        if last_spectrum is None:
            return -100.0
        zoomed = self._spectrum.zoom_slice(last_spectrum)
        n = len(zoomed)
        if n < 2:
            return -100.0
        bin_f = self._cursor_pos * (n - 1)
        lo = int(bin_f)
        hi = min(lo + 1, n - 1)
        frac = bin_f - lo
        return float(zoomed[lo] * (1.0 - frac) + zoomed[hi] * frac)

    # ------------------------------------------------------------------
    # Probe tone lifecycle
    # ------------------------------------------------------------------

    def start_probe(self) -> None:
        """Start the cursor probe tone at the current position."""
        if self._cursor_active:
            return
        self._cursor_active = True
        self._cursor_last_time = time.monotonic()
        self._settings.sonification_enabled = True
        self._duck_cb(0.1)
        self._sonification.start_probe(self._cursor_pos)

    def stop_probe(self) -> None:
        """Stop the cursor probe tone."""
        if not self._cursor_active:
            return
        self._cursor_active = False
        self._sonification.stop_probe()
        self._duck_cb(1.0)

    # ------------------------------------------------------------------
    # Timer — polls Ctrl and arrow keys
    # ------------------------------------------------------------------

    def _on_timer(self, _event: wx.TimerEvent) -> None:
        """50 ms tick: poll Ctrl for probe start/stop, arrows for movement."""
        if wx.GetActiveWindow() is not self._parent or not self._is_active_cb():
            if self._cursor_active:
                self.stop_probe()
            self._ctrl_was_down = False
            return

        ctrl_down = wx.GetKeyState(wx.WXK_CONTROL)

        if ctrl_down and not self._ctrl_was_down:
            self.start_probe()
        elif not ctrl_down and self._ctrl_was_down:
            self.stop_probe()
        self._ctrl_was_down = ctrl_down

        if not self._cursor_active:
            return

        left = wx.GetKeyState(wx.WXK_LEFT)
        right = wx.GetKeyState(wx.WXK_RIGHT)
        direction = (-1 if left else 0) + (1 if right else 0)

        now = time.monotonic()
        dt = now - self._cursor_last_time
        self._cursor_last_time = now

        if direction != 0:
            speed = self._settings.cursor_speed
            self._cursor_pos += direction * speed * dt
            self._cursor_pos = max(0.0, min(1.0, self._cursor_pos))

        self._sonification.update_probe(self._cursor_pos)
        self._panel.set_cursor(self._cursor_pos)
        if self._settings.demod_follows_cursor:
            self._update_offset_from_cursor()

    # ------------------------------------------------------------------
    # Discrete cursor movement
    # ------------------------------------------------------------------

    def step_cursor(self, direction: int) -> None:
        """Move the cursor by one discrete step and announce position."""
        step = self._settings.cursor_speed * 0.1
        self._cursor_pos += direction * step
        self._cursor_pos = max(0.0, min(1.0, self._cursor_pos))
        self._panel.set_cursor(self._cursor_pos)
        if self._settings.demod_follows_cursor:
            self._update_offset_from_cursor()
        self.speak_cursor()

    def speak_cursor(self, last_spectrum: Optional[np.ndarray] = None) -> None:
        """Speak the cursor's current frequency and power."""
        freq_hz = self.cursor_freq()
        db = self.cursor_db(last_spectrum)
        s_unit = s_meter(db)
        speech.output(
            _("{freq}, {db:.0f} dBFS, {s_unit}").format(
                freq=fmt_freq(freq_hz), db=db, s_unit=s_unit,
            )
        )

    def reset_cursor(self) -> None:
        """Reset the spectrum cursor to the centre and clear demod offset."""
        self._cursor_pos = 0.5
        self._panel.set_cursor(self._cursor_pos)
        self.reset_offset()
        speech.output(_("Cursor centred, offset cleared."))

    def tune_to_cursor(self) -> None:
        """Tune the LO to the cursor frequency and reset offset."""
        freq_hz = self.cursor_freq()
        self.reset_offset()
        self._cursor_pos = 0.5
        self._panel.set_cursor(self._cursor_pos)
        self._tune_cb(freq_hz)

    def on_spectrum_click(self, pos: float) -> None:
        """Handle mouse click on spectrum panel — move cursor to position."""
        self._cursor_pos = pos
        self._panel.set_cursor(pos)
        if self._settings.demod_follows_cursor:
            self._update_offset_from_cursor()

    # ------------------------------------------------------------------
    # Software VFO offset
    # ------------------------------------------------------------------

    def listening_freq(self) -> int:
        """Return the actual listening frequency (LO + demod offset)."""
        return int(self._settings.frequency + self._demod_offset)

    def set_demod_offset(self, hz: float) -> None:
        """Set the demod offset, clamping to +/- half capture bandwidth."""
        max_offset = self._settings.sample_rate / 2.0
        self._demod_offset = max(-max_offset, min(max_offset, hz))
        if self._pipeline is not None:
            self._pipeline.demod_offset = self._demod_offset
        self._update_demod_marker()
        listen = self.listening_freq()
        self._freq_ctrl.SetValue(fmt_freq(listen))

    def reset_offset(self) -> None:
        """Zero the demod offset and reset mixer phase."""
        self._demod_offset = 0.0
        if self._pipeline is not None:
            self._pipeline.demod_offset = 0.0
        self._update_demod_marker()
        self._freq_ctrl.SetValue(fmt_freq(self._settings.frequency))

    def _update_offset_from_cursor(self) -> None:
        """Convert cursor position to demod offset Hz."""
        start_hz, end_hz = self._spectrum.spectrum_range()
        span = end_hz - start_hz
        cursor_hz = start_hz + self._cursor_pos * span
        offset = cursor_hz - self._settings.frequency
        self.set_demod_offset(offset)

    def _update_demod_marker(self) -> None:
        """Sync the spectrum panel demod marker to the current offset."""
        if self._demod_offset == 0.0:
            self._panel.set_demod_marker(None)
        else:
            start_hz, end_hz = self._spectrum.spectrum_range()
            span = end_hz - start_hz
            if span > 0:
                pos = (self._settings.frequency + self._demod_offset - start_hz) / span
                pos = max(0.0, min(1.0, pos))
                self._panel.set_demod_marker(pos)
            else:
                self._panel.set_demod_marker(None)

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def stop(self) -> None:
        """Stop the timer and probe — call on window close."""
        self._timer.Stop()
        self.stop_probe()
