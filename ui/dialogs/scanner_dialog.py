"""
ui/dialogs/scanner_dialog.py — Frequency scanner dialog.

Presents start/end frequency and step fields, squelch threshold, a
results list, and playback controls (Hold, Skip, Stop).
Scan results are spoken as they arrive.
"""

from __future__ import annotations

from typing import Callable, List, Optional

import wx
from accessibility import speech
from core.scanner import Scanner, ScanResult


def _fmt_freq(hz: int) -> str:
    """Format frequency in MHz to 3 decimal places."""
    return f"{hz / 1e6:.3f} MHz"


class ScannerDialog(wx.Frame):
    """Modeless scanner control and results frame."""

    def __init__(
        self,
        parent: wx.Window,
        scanner: Scanner,
    ) -> None:
        super().__init__(
            parent,
            title="Frequency Scanner",
            style=wx.DEFAULT_FRAME_STYLE | wx.FRAME_FLOAT_ON_PARENT,
        )
        self.SetName("Frequency Scanner dialog")
        self._scanner = scanner
        self._scanner.on_signal_found = self._on_signal_found
        self._scanner.on_scan_complete = self._on_scan_complete
        self._build_ui()
        self.SetSize(520, 560)
        self.Centre()
        speech.speak("Scanner dialog opened.")

    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        # --- Parameters ---
        param_box = wx.StaticBox(panel, label="Scan Parameters")
        param_sizer = wx.StaticBoxSizer(param_box, wx.VERTICAL)
        grid = wx.FlexGridSizer(cols=2, vgap=6, hgap=8)
        grid.AddGrowableCol(1)

        grid.Add(wx.StaticText(panel, label="Start (MHz):"), 0, wx.ALIGN_CENTER_VERTICAL)
        self._start = wx.TextCtrl(panel, value="88.0", name="Scan start frequency MHz")
        grid.Add(self._start, 1, wx.EXPAND)

        grid.Add(wx.StaticText(panel, label="Stop (MHz):"), 0, wx.ALIGN_CENTER_VERTICAL)
        self._stop = wx.TextCtrl(panel, value="108.0", name="Scan stop frequency MHz")
        grid.Add(self._stop, 1, wx.EXPAND)

        grid.Add(wx.StaticText(panel, label="Step (kHz):"), 0, wx.ALIGN_CENTER_VERTICAL)
        self._step = wx.TextCtrl(panel, value="100", name="Scan step kHz")
        grid.Add(self._step, 1, wx.EXPAND)

        grid.Add(wx.StaticText(panel, label="Squelch (dBm):"), 0, wx.ALIGN_CENTER_VERTICAL)
        self._squelch = wx.SpinCtrl(
            panel, value="-60", min=-120, max=0, name="Scan squelch threshold dBm"
        )
        grid.Add(self._squelch, 1, wx.EXPAND)

        param_sizer.Add(grid, 0, wx.EXPAND | wx.ALL, 6)
        sizer.Add(param_sizer, 0, wx.EXPAND | wx.ALL, 8)

        # --- Controls ---
        ctrl_row = wx.BoxSizer(wx.HORIZONTAL)
        self._start_btn = wx.Button(panel, label="Start Scan", name="Start scan")
        self._hold_btn = wx.Button(panel, label="Hold (H)", name="Hold on frequency")
        self._skip_btn = wx.Button(panel, label="Skip (K)", name="Skip frequency")
        self._stop_btn = wx.Button(panel, label="Stop (Esc)", name="Stop scan")
        for btn in (self._start_btn, self._hold_btn, self._skip_btn, self._stop_btn):
            ctrl_row.Add(btn, 0, wx.RIGHT, 6)
        sizer.Add(ctrl_row, 0, wx.ALL, 8)

        # --- Results ---
        res_box = wx.StaticBox(panel, label="Results")
        res_sizer = wx.StaticBoxSizer(res_box, wx.VERTICAL)
        self._results_list = wx.ListCtrl(
            panel,
            style=wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.BORDER_SUNKEN,
            name="Scan results list",
        )
        self._results_list.InsertColumn(0, "Frequency", width=160)
        self._results_list.InsertColumn(1, "Strength (dBm)", width=140)
        res_sizer.Add(self._results_list, 1, wx.EXPAND | wx.ALL, 4)

        clear_btn = wx.Button(panel, label="Clear Results", name="Clear scan results")
        clear_btn.Bind(wx.EVT_BUTTON, self._on_clear)
        res_sizer.Add(clear_btn, 0, wx.ALL, 4)
        sizer.Add(res_sizer, 1, wx.EXPAND | wx.ALL, 8)

        # Status
        self._status = wx.StaticText(panel, label="Idle", name="Scanner status")
        sizer.Add(self._status, 0, wx.ALL, 8)

        panel.SetSizer(sizer)

        # Bindings
        self._start_btn.Bind(wx.EVT_BUTTON, self._on_start)
        self._hold_btn.Bind(wx.EVT_BUTTON, lambda e: self._scanner.hold())
        self._skip_btn.Bind(wx.EVT_BUTTON, lambda e: self._scanner.skip())
        self._stop_btn.Bind(wx.EVT_BUTTON, self._on_stop)
        self.Bind(wx.EVT_CHAR_HOOK, self._on_key)

    # ------------------------------------------------------------------

    def _on_start(self, _event: wx.CommandEvent) -> None:
        try:
            start_hz = int(float(self._start.GetValue()) * 1_000_000)
            stop_hz = int(float(self._stop.GetValue()) * 1_000_000)
            step_hz = int(float(self._step.GetValue()) * 1_000)
            squelch = float(self._squelch.GetValue())
        except ValueError:
            speech.speak("Invalid scan parameters.")
            return

        self._results_list.DeleteAllItems()
        self._status.SetLabel("Scanning…")
        self._scanner.start(start_hz, stop_hz, step_hz, squelch)
        speech.speak(
            f"Scan started from {_fmt_freq(start_hz)} to {_fmt_freq(stop_hz)}, "
            f"step {step_hz // 1000} kHz."
        )

    def _on_stop(self, _event: wx.CommandEvent) -> None:
        self._scanner.stop()
        self._status.SetLabel("Stopped.")
        speech.speak("Scan stopped.")

    def _on_clear(self, _event: wx.CommandEvent) -> None:
        self._results_list.DeleteAllItems()

    def _on_signal_found(self, result: ScanResult) -> None:
        """Called (via wx.CallAfter) when scanner finds a signal."""
        idx = self._results_list.InsertItem(
            self._results_list.GetItemCount(), _fmt_freq(result.freq_hz)
        )
        self._results_list.SetItem(idx, 1, f"{result.strength_db:.1f}")
        speech.speak(
            f"Signal found at {_fmt_freq(result.freq_hz)}, {result.strength_db:.0f} dBm."
        )

    def _on_scan_complete(self, results: list) -> None:
        count = len(results)
        self._status.SetLabel(f"Complete — {count} signal(s) found.")
        speech.speak(f"Scan complete. {count} signal{'s' if count != 1 else ''} found.")

    def _on_key(self, event: wx.KeyEvent) -> None:
        code = event.GetKeyCode()
        if code == wx.WXK_ESCAPE:
            self._on_stop(event)
        elif code == ord("H"):
            self._scanner.hold()
        elif code == ord("K"):
            self._scanner.skip()
        else:
            event.Skip()
