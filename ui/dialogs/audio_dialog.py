"""
ui/dialogs/audio_dialog.py — Audio device and recording settings dialog.

Allows selection of the sounddevice output device and configuration of
the recording path.  Also provides a record toggle button.
"""

from __future__ import annotations

import os
from typing import Optional

import wx
from accessibility import speech
from config.settings import Settings
from core.audio import AudioOutput


class AudioDialog(wx.Dialog):
    """Modal audio settings and recording control dialog."""

    def __init__(
        self,
        parent: wx.Window,
        settings: Settings,
        audio: AudioOutput,
    ) -> None:
        super().__init__(
            parent,
            title=_("Audio Settings"),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self.SetName("Audio Settings")
        self._settings = settings
        self._audio = audio
        self._recording_path: str = ""
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

        # Output device (WASAPI only)
        devices = AudioOutput.list_devices()
        device_names = [_("Default")]
        for d in devices:
            if d.get("max_output_channels", 0) > 0:
                device_names.append(d.get("name", str(d)))
        grid.Add(wx.StaticText(panel, label=_("Output Device:")), 0, wx.ALIGN_CENTER_VERTICAL)
        self._device_choice = wx.Choice(panel, choices=device_names, name="Audio output device")
        current = self._settings.audio_device or ""
        if current and current in device_names:
            self._device_choice.SetStringSelection(current)
        else:
            self._device_choice.SetSelection(0)
        grid.Add(self._device_choice, 1, wx.EXPAND)

        # Buffer size
        _buf_sizes = [512, 1024, 2048, 4096, 8192, 16384]
        _buf_labels = [str(s) for s in _buf_sizes]
        grid.Add(wx.StaticText(panel, label=_("Audio Buffer (samples):")), 0, wx.ALIGN_CENTER_VERTICAL)
        self._buf_choice = wx.Choice(panel, choices=_buf_labels, name="Audio buffer size")
        self._buf_sizes = _buf_sizes
        cur_buf = self._settings.audio_buffer_size
        self._buf_choice.SetSelection(_buf_sizes.index(cur_buf) if cur_buf in _buf_sizes else 3)
        grid.Add(self._buf_choice, 1, wx.EXPAND)

        # Recording path
        grid.Add(wx.StaticText(panel, label=_("Recording Folder:")), 0, wx.ALIGN_CENTER_VERTICAL)
        path_row = wx.BoxSizer(wx.HORIZONTAL)
        self._path_ctrl = wx.TextCtrl(
            panel, value=self._settings.recording_path, name="Recording folder path"
        )
        browse_btn = wx.Button(panel, label=_("Browse..."), name="Browse recording folder")
        browse_btn.Bind(wx.EVT_BUTTON, self._on_browse)
        path_row.Add(self._path_ctrl, 1, wx.EXPAND | wx.RIGHT, 4)
        path_row.Add(browse_btn, 0)
        grid.Add(path_row, 1, wx.EXPAND)

        sizer.Add(grid, 0, wx.EXPAND | wx.ALL, 12)

        # Record button
        self._record_btn = wx.ToggleButton(
            panel, label=_("Start Recording (R)"), name="Record toggle"
        )
        self._record_btn.Bind(wx.EVT_TOGGLEBUTTON, self._on_record_toggle)
        sizer.Add(self._record_btn, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)

        # Recording status
        self._rec_status = wx.StaticText(
            panel, label=_("Not recording."), name="Recording status"
        )
        sizer.Add(self._rec_status, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)

        panel.SetSizer(sizer)

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
        self.Bind(wx.EVT_CHAR_HOOK, self._on_key)

    # ------------------------------------------------------------------

    def _on_browse(self, _event: wx.CommandEvent) -> None:
        dlg = wx.DirDialog(self, _("Choose recording folder"), style=wx.DD_DEFAULT_STYLE)
        if dlg.ShowModal() == wx.ID_OK:
            self._path_ctrl.SetValue(dlg.GetPath())
        dlg.Destroy()

    def _on_record_toggle(self, event: wx.CommandEvent) -> None:
        if self._record_btn.GetValue():
            path = self._audio.start_recording(path="")
            if path:
                self._recording_path = path
                self._rec_status.SetLabel(
                    _("Recording: {filename}").format(filename=os.path.basename(path))
                )
                speech.output(
                    _("Recording started. File: {filename}").format(
                        filename=os.path.basename(path)
                    )
                )
            else:
                self._record_btn.SetValue(False)
                speech.output(_("Could not start recording."))
        else:
            self._audio.stop_recording()
            self._rec_status.SetLabel(_("Not recording."))
            speech.output(_("Recording stopped."))

    def _on_ok(self, _event: wx.CommandEvent) -> None:
        sel = self._device_choice.GetStringSelection()
        self._settings.audio_device = None if sel == _("Default") else sel
        self._settings.recording_path = self._path_ctrl.GetValue().strip()
        idx = self._buf_choice.GetSelection()
        if 0 <= idx < len(self._buf_sizes):
            self._settings.audio_buffer_size = self._buf_sizes[idx]
        self._settings.save()
        self.EndModal(wx.ID_OK)

    def _on_key(self, event: wx.KeyEvent) -> None:
        code = event.GetKeyCode()
        if code == ord("R") and not isinstance(self.FindFocus(), wx.TextCtrl):
            self._record_btn.SetValue(not self._record_btn.GetValue())
            self._on_record_toggle(event)
        else:
            event.Skip()
