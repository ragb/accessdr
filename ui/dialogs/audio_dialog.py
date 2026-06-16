"""
ui/dialogs/audio_dialog.py — Audio device settings dialog.

Allows selection of the sounddevice output device and buffer size.
"""

from __future__ import annotations

from typing import Optional

import wx
from config.settings import Settings
from core.audio import AudioOutput


class AudioDialog(wx.Dialog):
    """Modal audio settings dialog."""

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

        # Squelch hang time (tail held open after a signal drops; 0 = instant cut)
        grid.Add(wx.StaticText(panel, label=_("Squelch Hang (ms):")), 0, wx.ALIGN_CENTER_VERTICAL)
        self._hang_spin = wx.SpinCtrl(
            panel, min=0, max=3000, value=str(int(self._settings.squelch_hang_ms)),
            name="Squelch hang time milliseconds",
        )
        grid.Add(self._hang_spin, 1, wx.EXPAND)

        # Squelch hysteresis (how far below the open threshold it closes)
        grid.Add(wx.StaticText(panel, label=_("Squelch Hysteresis (dB):")), 0, wx.ALIGN_CENTER_VERTICAL)
        self._hyst_spin = wx.SpinCtrl(
            panel, min=0, max=20, value=str(int(self._settings.squelch_hysteresis_db)),
            name="Squelch hysteresis dB",
        )
        grid.Add(self._hyst_spin, 1, wx.EXPAND)

        sizer.Add(grid, 0, wx.EXPAND | wx.ALL, 12)

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

    # ------------------------------------------------------------------

    def _on_ok(self, _event: wx.CommandEvent) -> None:
        sel = self._device_choice.GetStringSelection()
        self._settings.audio_device = None if sel == _("Default") else sel
        idx = self._buf_choice.GetSelection()
        if 0 <= idx < len(self._buf_sizes):
            self._settings.audio_buffer_size = self._buf_sizes[idx]
        self._settings.squelch_hang_ms = float(self._hang_spin.GetValue())
        self._settings.squelch_hysteresis_db = float(self._hyst_spin.GetValue())
        # Apply live so the change is audible without a restart.
        self._audio.squelch_hang_ms = self._settings.squelch_hang_ms
        self._audio.squelch_hysteresis_db = self._settings.squelch_hysteresis_db
        self._settings.save()
        self.EndModal(wx.ID_OK)
