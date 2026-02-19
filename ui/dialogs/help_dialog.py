"""
ui/dialogs/help_dialog.py — Keyboard shortcut reference dialog.

Opens as a modeless (non-blocking) frame so radio audio continues.
The full shortcut list is also spoken aloud when the dialog opens.
"""

from __future__ import annotations

import wx
from accessibility import speech

SHORTCUTS = [
    (N_("--- Main Window ---"), ""),
    (N_("Start / Stop radio"), "Space  (or toolbar button)"),
    (N_("Tune up by step"), "Up Arrow"),
    (N_("Tune down by step"), "Down Arrow"),
    (N_("Tune up by 10× step"), "Ctrl+Up"),
    (N_("Tune down by 10× step"), "Ctrl+Down"),
    (N_("Cycle step size"), "S"),
    (N_("Mute / Unmute"), "M"),
    (N_("Read signal strength"), "I"),
    ("", ""),
    (N_("--- Demodulation modes ---"), ""),
    (N_("Wide FM"), "W"),
    (N_("Narrow FM"), "N"),
    ("AM", "A"),
    ("USB", "U"),
    ("LSB", "L"),
    ("CW", "C"),
    ("DSB", "D"),
    ("", ""),
    (N_("--- Spectrum / Sonification ---"), ""),
    (N_("Speak top peaks"), "F"),
    (N_("Sonification snapshot sweep"), "Space  (in Spectrum dialog)"),
    ("", ""),
    (N_("--- Dialogs ---"), ""),
    (N_("RF Settings"), "Ctrl+R"),
    (N_("Spectrum & Sonification"), "Ctrl+S"),
    (N_("Scanner"), "Ctrl+N"),
    (N_("Bookmarks"), "Ctrl+B"),
    (N_("Audio Settings"), "Ctrl+D"),
    (N_("Help (this window)"), "F1"),
    ("", ""),
    (N_("--- Scanner (when open) ---"), ""),
    (N_("Hold on frequency"), "H"),
    (N_("Skip to next"), "K"),
    (N_("Stop scan"), "Escape"),
    ("", ""),
    (N_("--- General ---"), ""),
    (N_("Open Bands menu"), "Alt+R  (Radio menu)"),
    (N_("Save bookmark"), "Ctrl+Shift+B"),
    (N_("Quit"), "Alt+F4"),
]


class HelpDialog(wx.Frame):
    """Modeless keyboard shortcut reference."""

    def __init__(self, parent: wx.Window) -> None:
        super().__init__(
            parent,
            title=_("Keyboard Shortcuts — AccessDR"),
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

        lbl = wx.StaticText(panel, label=_("AccessDR Keyboard Shortcuts"))
        lbl.SetFont(lbl.GetFont().Bold())
        sizer.Add(lbl, 0, wx.ALL, 8)

        # List control with two columns
        self._list = wx.ListCtrl(
            panel,
            style=wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.BORDER_SUNKEN,
            name="Shortcut list",
        )
        self._list.InsertColumn(0, _("Action"), width=300)
        self._list.InsertColumn(1, _("Key(s)"), width=200)

        for action, key in SHORTCUTS:
            idx = self._list.InsertItem(self._list.GetItemCount(), _(action) if action else "")
            self._list.SetItem(idx, 1, key)

        sizer.Add(self._list, 1, wx.EXPAND | wx.ALL, 8)

        close_btn = wx.Button(panel, wx.ID_CLOSE, label=_("Close"))
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
        lines = [_("Keyboard Shortcuts for AccessDR.")]
        for action, key in SHORTCUTS:
            if action and key:
                lines.append(f"{_(action)}: {key}")
        speech.speak("  ".join(lines), interrupt=False)
