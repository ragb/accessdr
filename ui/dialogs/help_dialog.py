"""
ui/dialogs/help_dialog.py — Keyboard shortcut reference dialog.

Opens as a modeless (non-blocking) frame so radio audio continues.
The full shortcut list is also spoken aloud when the dialog opens.
"""

from __future__ import annotations

import wx
from accessibility import speech

SHORTCUTS = [
    ("--- Main Window ---", ""),
    ("Start / Stop radio", "Space  (or toolbar button)"),
    ("Tune up by step", "Up Arrow"),
    ("Tune down by step", "Down Arrow"),
    ("Tune up by 10× step", "Ctrl+Up"),
    ("Tune down by 10× step", "Ctrl+Down"),
    ("Cycle step size", "S"),
    ("Mute / Unmute", "M"),
    ("Read signal strength", "I"),
    ("", ""),
    ("--- Demodulation modes ---", ""),
    ("Wide FM", "W"),
    ("Narrow FM", "N"),
    ("AM", "A"),
    ("USB", "U"),
    ("LSB", "L"),
    ("CW", "C"),
    ("DSB", "D"),
    ("", ""),
    ("--- Spectrum / Sonification ---", ""),
    ("Speak top peaks", "F"),
    ("Sonification snapshot sweep", "Space  (in Spectrum dialog)"),
    ("", ""),
    ("--- Dialogs ---", ""),
    ("RF Settings", "Ctrl+R"),
    ("Spectrum & Sonification", "Ctrl+S"),
    ("Scanner", "Ctrl+N"),
    ("Bookmarks", "Ctrl+B"),
    ("Audio Settings", "Ctrl+D"),
    ("Help (this window)", "F1"),
    ("", ""),
    ("--- Scanner (when open) ---", ""),
    ("Hold on frequency", "H"),
    ("Skip to next", "K"),
    ("Stop scan", "Escape"),
    ("", ""),
    ("--- General ---", ""),
    ("Open Bands menu", "Alt+R  (Radio menu)"),
    ("Save bookmark", "Ctrl+Shift+B"),
    ("Quit", "Alt+F4"),
]


class HelpDialog(wx.Frame):
    """Modeless keyboard shortcut reference."""

    def __init__(self, parent: wx.Window) -> None:
        super().__init__(
            parent,
            title="Keyboard Shortcuts — AccessDR",
            style=wx.DEFAULT_FRAME_STYLE | wx.FRAME_FLOAT_ON_PARENT,
        )
        self.SetName("Keyboard Shortcuts dialog")
        self._build_ui()
        self.SetSize(560, 520)
        self.Centre()
        self._announce()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        lbl = wx.StaticText(panel, label="AccessDR Keyboard Shortcuts")
        lbl.SetFont(lbl.GetFont().Bold())
        sizer.Add(lbl, 0, wx.ALL, 8)

        # List control with two columns
        self._list = wx.ListCtrl(
            panel,
            style=wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.BORDER_SUNKEN,
            name="Shortcut list",
        )
        self._list.InsertColumn(0, "Action", width=300)
        self._list.InsertColumn(1, "Key(s)", width=200)

        for action, key in SHORTCUTS:
            idx = self._list.InsertItem(self._list.GetItemCount(), action)
            self._list.SetItem(idx, 1, key)

        sizer.Add(self._list, 1, wx.EXPAND | wx.ALL, 8)

        close_btn = wx.Button(panel, wx.ID_CLOSE, label="Close")
        close_btn.SetName("Close help dialog")
        close_btn.Bind(wx.EVT_BUTTON, lambda e: self.Close())
        sizer.Add(close_btn, 0, wx.ALIGN_RIGHT | wx.ALL, 8)

        panel.SetSizer(sizer)
        self.Bind(wx.EVT_CHAR_HOOK, self._on_key)

    def _on_key(self, event: wx.KeyEvent) -> None:
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self.Close()
        else:
            event.Skip()

    def _announce(self) -> None:
        lines = ["Keyboard Shortcuts for AccessDR."]
        for action, key in SHORTCUTS:
            if action and key:
                lines.append(f"{action}: {key}")
        speech.speak("  ".join(lines), interrupt=False)
