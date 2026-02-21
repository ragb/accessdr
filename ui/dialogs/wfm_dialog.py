"""
ui/dialogs/wfm_dialog.py — WFM-specific settings dialog.

Controls de-emphasis, stereo mode, hi-blend, and RDS decoding for
wide-band FM reception.
"""

from __future__ import annotations

import wx
from config.settings import Settings

DEEMPHASIS_OPTIONS = [
    ("auto", N_("Auto (detect region)")),
    ("50",   N_("50 µs (Europe)")),
    ("75",   N_("75 µs (Americas)")),
]

STEREO_OPTIONS = [
    ("auto",   N_("Auto")),
    ("mono",   N_("Force Mono")),
    ("stereo", N_("Force Stereo")),
]


class WFMDialog(wx.Dialog):
    """Modal WFM settings dialog with standard OK / Cancel."""

    def __init__(self, parent: wx.Window, settings: Settings) -> None:
        super().__init__(
            parent,
            title=_("WFM Settings"),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self.SetName("WFM Settings")
        self._settings = settings
        self._build_ui()
        self.Fit()
        self.SetMinSize(self.GetSize())
        self.Centre()

    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        panel = wx.Panel(self)
        main_sizer = wx.BoxSizer(wx.VERTICAL)

        # --- Audio processing section ---
        audio_box = wx.StaticBox(panel, label=_("Audio Processing"))
        audio_sizer = wx.StaticBoxSizer(audio_box, wx.VERTICAL)
        audio_grid = wx.FlexGridSizer(cols=2, vgap=8, hgap=8)
        audio_grid.AddGrowableCol(1, 1)

        # De-emphasis
        audio_grid.Add(
            wx.StaticText(panel, label=_("De-emphasis:")),
            0, wx.ALIGN_CENTER_VERTICAL,
        )
        deemph_labels = [_(lbl) for _val, lbl in DEEMPHASIS_OPTIONS]
        self._deemph_choice = wx.Choice(
            panel, choices=deemph_labels, name="De-emphasis",
        )
        deemph_idx = 0
        for i, (val, _lbl) in enumerate(DEEMPHASIS_OPTIONS):
            if val == self._settings.wfm_deemphasis:
                deemph_idx = i
                break
        self._deemph_choice.SetSelection(deemph_idx)
        audio_grid.Add(self._deemph_choice, 1, wx.EXPAND)

        # Stereo mode
        audio_grid.Add(
            wx.StaticText(panel, label=_("Stereo:")),
            0, wx.ALIGN_CENTER_VERTICAL,
        )
        stereo_labels = [_(lbl) for _val, lbl in STEREO_OPTIONS]
        self._stereo_choice = wx.Choice(
            panel, choices=stereo_labels, name="Stereo mode",
        )
        stereo_idx = 0
        for i, (val, _lbl) in enumerate(STEREO_OPTIONS):
            if val == self._settings.wfm_stereo_mode:
                stereo_idx = i
                break
        self._stereo_choice.SetSelection(stereo_idx)
        audio_grid.Add(self._stereo_choice, 1, wx.EXPAND)

        # Hi-blend checkbox
        audio_grid.Add(wx.StaticText(panel, label=""), 0)
        self._hiblend_cb = wx.CheckBox(
            panel,
            label=_("Reduce treble on weak signals"),
            name="Hi-blend",
        )
        self._hiblend_cb.SetValue(self._settings.wfm_hiblend_enabled)
        audio_grid.Add(self._hiblend_cb, 1, wx.EXPAND)

        audio_sizer.Add(audio_grid, 0, wx.EXPAND | wx.ALL, 6)
        main_sizer.Add(audio_sizer, 0, wx.EXPAND | wx.ALL, 8)

        # --- Data section ---
        data_box = wx.StaticBox(panel, label=_("Data"))
        data_sizer = wx.StaticBoxSizer(data_box, wx.VERTICAL)
        data_grid = wx.FlexGridSizer(cols=2, vgap=8, hgap=8)
        data_grid.AddGrowableCol(1, 1)

        # RDS checkbox
        data_grid.Add(wx.StaticText(panel, label=""), 0)
        self._rds_cb = wx.CheckBox(
            panel,
            label=_("Decode RDS station info"),
            name="RDS decoding",
        )
        self._rds_cb.SetValue(self._settings.wfm_rds_enabled)
        data_grid.Add(self._rds_cb, 1, wx.EXPAND)

        data_sizer.Add(data_grid, 0, wx.EXPAND | wx.ALL, 6)
        main_sizer.Add(data_sizer, 0, wx.EXPAND | wx.ALL, 8)

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
        idx = self._deemph_choice.GetSelection()
        if 0 <= idx < len(DEEMPHASIS_OPTIONS):
            self._settings.wfm_deemphasis = DEEMPHASIS_OPTIONS[idx][0]

        idx = self._stereo_choice.GetSelection()
        if 0 <= idx < len(STEREO_OPTIONS):
            self._settings.wfm_stereo_mode = STEREO_OPTIONS[idx][0]

        self._settings.wfm_hiblend_enabled = self._hiblend_cb.GetValue()
        self._settings.wfm_rds_enabled = self._rds_cb.GetValue()

        self._settings.save()
        self.EndModal(wx.ID_OK)
