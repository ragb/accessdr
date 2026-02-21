"""
ui/dialogs/spectrum_dialog.py — Spectrum settings dialog.

Controls FFT settings, sonification parameters, and speech readout options.
"""

from __future__ import annotations

from typing import Optional

import wx
from accessibility.sonification import Sonification
from config.settings import Settings


class SpectrumDialog(wx.Dialog):
    """Modal spectrum and sonification settings dialog."""

    def __init__(
        self,
        parent: wx.Window,
        settings: Settings,
        sonification: Sonification,
    ) -> None:
        super().__init__(
            parent,
            title=_("Spectrum Settings"),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self.SetName("Spectrum Settings")
        self._settings = settings
        self._son = sonification
        self._build_ui()
        self.Fit()
        self.SetMinSize(self.GetSize())
        self.Centre()

    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        panel = wx.Panel(self)
        main_sizer = wx.BoxSizer(wx.VERTICAL)

        # --- FFT section ---
        fft_box = wx.StaticBox(panel, label=_("FFT Settings"))
        fft_sizer = wx.StaticBoxSizer(fft_box, wx.VERTICAL)
        fft_grid = wx.FlexGridSizer(cols=2, vgap=6, hgap=8)
        fft_grid.AddGrowableCol(1)

        fft_sizes = [256, 512, 1024, 2048, 4096]
        fft_labels = [str(s) for s in fft_sizes]
        fft_grid.Add(wx.StaticText(panel, label=_("FFT Size:")), 0, wx.ALIGN_CENTER_VERTICAL)
        self._fft_choice = wx.Choice(panel, choices=fft_labels, name="FFT Size")
        try:
            fft_idx = fft_sizes.index(self._settings.fft_size)
        except ValueError:
            fft_idx = 2
        self._fft_choice.SetSelection(fft_idx)
        fft_grid.Add(self._fft_choice, 1, wx.EXPAND)

        fft_sizer.Add(fft_grid, 0, wx.EXPAND | wx.ALL, 6)
        main_sizer.Add(fft_sizer, 0, wx.EXPAND | wx.ALL, 8)

        # --- Sonification section ---
        son_box = wx.StaticBox(panel, label=_("Sonification"))
        son_sizer = wx.StaticBoxSizer(son_box, wx.VERTICAL)
        son_grid = wx.FlexGridSizer(cols=2, vgap=6, hgap=8)
        son_grid.AddGrowableCol(1)

        son_grid.Add(wx.StaticText(panel, label=_("Weak signal pitch (Hz):")), 0, wx.ALIGN_CENTER_VERTICAL)
        self._min_pitch = wx.SpinCtrl(
            panel, value=str(self._settings.sonification_min_hz),
            min=100, max=2000, name="Weak signal pitch Hz"
        )
        son_grid.Add(self._min_pitch, 1, wx.EXPAND)

        son_grid.Add(wx.StaticText(panel, label=_("Strong signal pitch (Hz):")), 0, wx.ALIGN_CENTER_VERTICAL)
        self._max_pitch = wx.SpinCtrl(
            panel, value=str(self._settings.sonification_max_hz),
            min=500, max=8000, name="Strong signal pitch Hz"
        )
        son_grid.Add(self._max_pitch, 1, wx.EXPAND)

        son_grid.Add(wx.StaticText(panel, label=_("Sweep speed (s):")), 0, wx.ALIGN_CENTER_VERTICAL)
        self._sweep_speed = wx.SpinCtrlDouble(
            panel, value=str(self._settings.sonification_sweep_speed),
            min=0.5, max=30.0, inc=0.5, name="Sweep speed seconds"
        )
        son_grid.Add(self._sweep_speed, 1, wx.EXPAND)

        son_grid.Add(
            wx.StaticText(panel, label=_("Spectrum averaging (ms):")),
            0, wx.ALIGN_CENTER_VERTICAL,
        )
        self._spec_avg = wx.SpinCtrlDouble(
            panel, value=str(self._settings.spectrum_averaging_ms),
            min=0.0, max=500.0, inc=10.0, name="Spectrum averaging ms"
        )
        son_grid.Add(self._spec_avg, 1, wx.EXPAND)

        son_grid.Add(
            wx.StaticText(panel, label=_("Pitch smoothing (ms):")),
            0, wx.ALIGN_CENTER_VERTICAL,
        )
        self._pitch_smooth = wx.SpinCtrlDouble(
            panel, value=str(self._settings.pitch_smoothing_ms),
            min=0.0, max=200.0, inc=5.0, name="Pitch smoothing ms"
        )
        son_grid.Add(self._pitch_smooth, 1, wx.EXPAND)

        son_sizer.Add(son_grid, 0, wx.EXPAND | wx.ALL, 6)
        main_sizer.Add(son_sizer, 0, wx.EXPAND | wx.ALL, 8)

        # --- Speech readout section ---
        sp_box = wx.StaticBox(panel, label=_("Speech Readout"))
        sp_sizer = wx.StaticBoxSizer(sp_box, wx.VERTICAL)
        sp_grid = wx.FlexGridSizer(cols=2, vgap=6, hgap=8)
        sp_grid.AddGrowableCol(1)

        sp_grid.Add(wx.StaticText(panel, label=_("Peak count (F key):")), 0, wx.ALIGN_CENTER_VERTICAL)
        self._peak_count = wx.SpinCtrl(
            panel, value=str(self._settings.speech_peak_count),
            min=1, max=10, name="Peak count"
        )
        sp_grid.Add(self._peak_count, 1, wx.EXPAND)

        sp_grid.Add(
            wx.StaticText(panel, label=_("Auto-announce threshold (dBm):")),
            0, wx.ALIGN_CENTER_VERTICAL,
        )
        self._announce_thresh = wx.SpinCtrl(
            panel, value=str(int(self._settings.auto_announce_threshold)),
            min=-120, max=0, name="Auto-announce threshold dBm"
        )
        sp_grid.Add(self._announce_thresh, 1, wx.EXPAND)

        sp_sizer.Add(sp_grid, 0, wx.EXPAND | wx.ALL, 6)
        main_sizer.Add(sp_sizer, 0, wx.EXPAND | wx.ALL, 8)

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

    # ------------------------------------------------------------------

    def _on_ok(self, _event: wx.CommandEvent) -> None:
        fft_sizes = [256, 512, 1024, 2048, 4096]
        idx = self._fft_choice.GetSelection()
        if 0 <= idx < len(fft_sizes):
            self._settings.fft_size = fft_sizes[idx]

        self._settings.sonification_min_hz = self._min_pitch.GetValue()
        self._settings.sonification_max_hz = self._max_pitch.GetValue()
        self._settings.sonification_sweep_speed = self._sweep_speed.GetValue()
        self._settings.spectrum_averaging_ms = self._spec_avg.GetValue()
        self._settings.pitch_smoothing_ms = self._pitch_smooth.GetValue()
        self._settings.speech_peak_count = self._peak_count.GetValue()
        self._settings.auto_announce_threshold = float(self._announce_thresh.GetValue())
        self._settings.save()

        self._son.update_settings(
            min_pitch=self._settings.sonification_min_hz,
            max_pitch=self._settings.sonification_max_hz,
            sweep_speed=self._settings.sonification_sweep_speed,
            spectrum_averaging_ms=self._settings.spectrum_averaging_ms,
            pitch_smoothing_ms=self._settings.pitch_smoothing_ms,
        )

        self.EndModal(wx.ID_OK)
