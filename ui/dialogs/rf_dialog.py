"""
ui/dialogs/rf_dialog.py — RF Settings dialog.

Allows the user to select SDR device, set gain, sample rate, and PPM
correction.  Changes are applied immediately and persisted to settings.
"""

from __future__ import annotations

from typing import Callable, Optional

import wx
from accessibility import speech
from config.settings import Settings
from core.sdr_device import enumerate_devices

SAMPLE_RATES = [250_000, 1_024_000, 1_536_000, 1_792_000, 2_048_000,
                2_400_000, 2_560_000, 2_880_000, 3_200_000]


class RFDialog(wx.Frame):
    """Modeless RF settings frame."""

    def __init__(
        self,
        parent: wx.Window,
        settings: Settings,
        on_change: Optional[Callable[[Settings], None]] = None,
    ) -> None:
        super().__init__(
            parent,
            title=_("RF Settings"),
            style=wx.DEFAULT_FRAME_STYLE | wx.FRAME_FLOAT_ON_PARENT,
        )
        self.SetName("RF Settings dialog")
        self._settings = settings
        self._on_change = on_change
        self._build_ui()
        self.SetSize(400, 340)
        self.Centre()
        speech.speak(_("RF Settings dialog opened."))

    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)
        grid = wx.FlexGridSizer(cols=2, vgap=8, hgap=8)
        grid.AddGrowableCol(1, 1)

        # Device selector
        devices = enumerate_devices()
        device_labels = [d.get("label", str(d)) for d in devices] or [_("Default / Auto")]
        grid.Add(wx.StaticText(panel, label=_("SDR Device:")), 0, wx.ALIGN_CENTER_VERTICAL)
        self._device_choice = wx.Choice(panel, choices=device_labels, name="SDR Device")
        idx = min(self._settings.device_index, len(device_labels) - 1)
        self._device_choice.SetSelection(idx)
        grid.Add(self._device_choice, 1, wx.EXPAND)

        # Sample rate
        rate_labels = [f"{r // 1000} kHz" for r in SAMPLE_RATES]
        grid.Add(wx.StaticText(panel, label=_("Sample Rate:")), 0, wx.ALIGN_CENTER_VERTICAL)
        self._rate_choice = wx.Choice(panel, choices=rate_labels, name="Sample Rate")
        try:
            rate_idx = SAMPLE_RATES.index(self._settings.sample_rate)
        except ValueError:
            rate_idx = 5           # default 2.4 MSPS
        self._rate_choice.SetSelection(rate_idx)
        grid.Add(self._rate_choice, 1, wx.EXPAND)

        # Gain slider
        grid.Add(wx.StaticText(panel, label=_("RF Gain (dB):")), 0, wx.ALIGN_CENTER_VERTICAL)
        gain_panel = wx.Panel(panel)
        gain_row = wx.BoxSizer(wx.HORIZONTAL)
        self._gain_slider = wx.Slider(
            gain_panel, value=int(self._settings.gain),
            minValue=0, maxValue=50,
            style=wx.SL_HORIZONTAL,
            name="RF Gain slider",
        )
        self._gain_label = wx.StaticText(gain_panel, label=f"{self._settings.gain:.0f} dB")
        gain_row.Add(self._gain_slider, 1, wx.EXPAND)
        gain_row.Add(self._gain_label, 0, wx.LEFT | wx.ALIGN_CENTER_VERTICAL, 6)
        gain_panel.SetSizer(gain_row)
        grid.Add(gain_panel, 1, wx.EXPAND)

        # PPM correction
        grid.Add(wx.StaticText(panel, label=_("PPM Correction:")), 0, wx.ALIGN_CENTER_VERTICAL)
        self._ppm_spin = wx.SpinCtrl(
            panel, value=str(self._settings.ppm),
            min=-150, max=150, name="PPM Correction"
        )
        grid.Add(self._ppm_spin, 1, wx.EXPAND)

        sizer.Add(grid, 1, wx.EXPAND | wx.ALL, 12)

        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        apply_btn = wx.Button(panel, label=_("Apply"), name="Apply RF settings")
        close_btn = wx.Button(panel, wx.ID_CLOSE, label=_("Close"))
        btn_row.Add(apply_btn, 0, wx.RIGHT, 8)
        btn_row.Add(close_btn, 0)
        sizer.Add(btn_row, 0, wx.ALIGN_RIGHT | wx.ALL, 12)

        panel.SetSizer(sizer)

        # Bindings
        self._gain_slider.Bind(wx.EVT_SLIDER, self._on_gain_slide)
        apply_btn.Bind(wx.EVT_BUTTON, self._on_apply)
        close_btn.Bind(wx.EVT_BUTTON, lambda e: self.Close())
        self.Bind(wx.EVT_CHAR_HOOK, self._on_key)

    def _on_gain_slide(self, event: wx.CommandEvent) -> None:
        val = self._gain_slider.GetValue()
        self._gain_label.SetLabel(f"{val} dB")
        speech.speak(_("Gain {val} dB").format(val=val))

    def _on_apply(self, _event: wx.CommandEvent) -> None:
        self._settings.device_index = self._device_choice.GetSelection()
        rate_idx = self._rate_choice.GetSelection()
        if 0 <= rate_idx < len(SAMPLE_RATES):
            self._settings.sample_rate = SAMPLE_RATES[rate_idx]
        self._settings.gain = float(self._gain_slider.GetValue())
        self._settings.ppm = self._ppm_spin.GetValue()
        self._settings.save()

        if self._on_change:
            self._on_change(self._settings)

        speech.speak(
            _("RF settings applied. Gain {gain:.0f} dB, "
              "Sample rate {rate} kHz, PPM {ppm}.").format(
                gain=self._settings.gain,
                rate=self._settings.sample_rate // 1000,
                ppm=self._settings.ppm,
            )
        )

    def _on_key(self, event: wx.KeyEvent) -> None:
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self.Close()
        else:
            event.Skip()
