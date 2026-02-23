"""
ui/dialogs/nfm_dialog.py — NFM-specific settings dialog.

Controls deviation for narrow-band FM reception (standard 5 kHz vs
PMR446 2.5 kHz).
"""

from __future__ import annotations

import wx
from config.settings import Settings

DEVIATION_OPTIONS = [
    (5000, N_("5 kHz (Standard)")),
    (2500, N_("2.5 kHz (PMR446)")),
]


class NFMDialog(wx.Dialog):
    """Modal NFM settings dialog with standard OK / Cancel."""

    def __init__(self, parent: wx.Window, settings: Settings) -> None:
        super().__init__(
            parent,
            title=_("NFM Settings"),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self.SetName("NFM Settings")
        self._settings = settings
        self._build_ui()
        self.Fit()
        self.SetMinSize(self.GetSize())
        self.Centre()

    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        panel = wx.Panel(self)
        main_sizer = wx.BoxSizer(wx.VERTICAL)

        grid = wx.FlexGridSizer(cols=2, vgap=8, hgap=8)
        grid.AddGrowableCol(1, 1)

        # Deviation
        grid.Add(
            wx.StaticText(panel, label=_("Deviation:")),
            0, wx.ALIGN_CENTER_VERTICAL,
        )
        dev_labels = [_(lbl) for _val, lbl in DEVIATION_OPTIONS]
        self._dev_choice = wx.Choice(
            panel, choices=dev_labels, name="Deviation",
        )
        dev_idx = 0
        for i, (val, _lbl) in enumerate(DEVIATION_OPTIONS):
            if val == self._settings.nfm_deviation:
                dev_idx = i
                break
        self._dev_choice.SetSelection(dev_idx)
        grid.Add(self._dev_choice, 1, wx.EXPAND)

        # CTCSS notch filter
        grid.Add((0, 0))  # empty cell to align checkbox in column 1
        self._ctcss_notch_cb = wx.CheckBox(
            panel,
            label=_("Remove CTCSS tone from audio"),
            name="CTCSS Notch",
        )
        self._ctcss_notch_cb.SetValue(self._settings.nfm_ctcss_notch)
        grid.Add(self._ctcss_notch_cb, 1, wx.EXPAND)

        main_sizer.Add(grid, 0, wx.EXPAND | wx.ALL, 8)
        panel.SetSizer(main_sizer)

        # Dialog-level sizer: panel + standard OK/Cancel buttons
        dlg_sizer = wx.BoxSizer(wx.VERTICAL)
        dlg_sizer.Add(panel, 1, wx.EXPAND)

        btn_sizer = wx.StdDialogButtonSizer()
        ok_btn = wx.Button(self, wx.ID_OK)
        ok_btn.SetDefault()
        btn_sizer.AddButton(ok_btn)
        btn_sizer.AddButton(wx.Button(self, wx.ID_CANCEL))
        btn_sizer.Realize()
        dlg_sizer.Add(btn_sizer, 0, wx.EXPAND | wx.ALL, 8)

        self.SetSizer(dlg_sizer)
        self.Bind(wx.EVT_BUTTON, self._on_ok, id=wx.ID_OK)

    def _on_ok(self, _event: wx.CommandEvent) -> None:
        idx = self._dev_choice.GetSelection()
        if 0 <= idx < len(DEVIATION_OPTIONS):
            self._settings.nfm_deviation = DEVIATION_OPTIONS[idx][0]

        self._settings.nfm_ctcss_notch = self._ctcss_notch_cb.GetValue()
        self._settings.save()
        self.EndModal(wx.ID_OK)
