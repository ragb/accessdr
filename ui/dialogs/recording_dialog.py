"""
ui/dialogs/recording_dialog.py — Recording settings dialog.

Configures recording format (WAV, FLAC, OGG, MP3) and output folder.
Compressed formats require ffmpeg on the system PATH.
"""

from __future__ import annotations

import wx
from config.settings import Settings
from core.audio import available_formats, ffmpeg_available


class RecordingDialog(wx.Dialog):
    """Modal recording settings dialog."""

    def __init__(self, parent: wx.Window, settings: Settings) -> None:
        super().__init__(
            parent,
            title=_("Recording Settings"),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self.SetName("Recording Settings")
        self._settings = settings
        self._build_ui()
        self.Fit()
        self.SetMinSize(self.GetSize())
        self.Centre()

    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)
        grid = wx.FlexGridSizer(cols=2, vgap=8, hgap=8)
        grid.AddGrowableCol(1)

        # Format dropdown
        fmts = available_formats()
        fmt_labels = [f.upper() for f in fmts]
        grid.Add(
            wx.StaticText(panel, label=_("Format:")),
            0, wx.ALIGN_CENTER_VERTICAL,
        )
        self._fmt_choice = wx.Choice(
            panel, choices=fmt_labels, name="Recording format",
        )
        cur = self._settings.recording_format
        if cur in fmts:
            self._fmt_choice.SetSelection(fmts.index(cur))
        else:
            self._fmt_choice.SetSelection(0)
        self._fmts = fmts
        grid.Add(self._fmt_choice, 1, wx.EXPAND)

        # Recording folder
        grid.Add(
            wx.StaticText(panel, label=_("Recording Folder:")),
            0, wx.ALIGN_CENTER_VERTICAL,
        )
        path_row = wx.BoxSizer(wx.HORIZONTAL)
        self._path_ctrl = wx.TextCtrl(
            panel, value=self._settings.recording_path,
            name="Recording folder path",
        )
        browse_btn = wx.Button(
            panel, label=_("Browse..."), name="Browse recording folder",
        )
        browse_btn.Bind(wx.EVT_BUTTON, self._on_browse)
        path_row.Add(self._path_ctrl, 1, wx.EXPAND | wx.RIGHT, 4)
        path_row.Add(browse_btn, 0)
        grid.Add(path_row, 1, wx.EXPAND)

        sizer.Add(grid, 0, wx.EXPAND | wx.ALL, 12)

        # Info text when ffmpeg not available
        if not ffmpeg_available():
            info = wx.StaticText(
                panel,
                label=_(
                    "Install ffmpeg and add it to PATH to enable"
                    " FLAC, OGG, and MP3 formats."
                ),
            )
            info.Wrap(400)
            sizer.Add(info, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)

        panel.SetSizer(sizer)

        # Dialog-level sizer
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

    # ------------------------------------------------------------------

    def _on_browse(self, _event: wx.CommandEvent) -> None:
        dlg = wx.DirDialog(
            self, _("Choose recording folder"), style=wx.DD_DEFAULT_STYLE,
        )
        if dlg.ShowModal() == wx.ID_OK:
            self._path_ctrl.SetValue(dlg.GetPath())
        dlg.Destroy()

    def _on_ok(self, _event: wx.CommandEvent) -> None:
        idx = self._fmt_choice.GetSelection()
        if 0 <= idx < len(self._fmts):
            self._settings.recording_format = self._fmts[idx]
        self._settings.recording_path = self._path_ctrl.GetValue().strip()
        self._settings.save()
        self.EndModal(wx.ID_OK)
