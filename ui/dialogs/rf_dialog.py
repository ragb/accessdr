"""
ui/dialogs/rf_dialog.py — RF Settings dialog.

Allows the user to select SDR device, set gain, sample rate, PPM correction,
AGC, offset tuning, and IF bandwidth.  Changes are applied immediately and
persisted to settings.
"""

from __future__ import annotations

from typing import Callable, List, Optional

import wx
from accessibility import speech
from config.settings import Settings
from core.sdr_device import enumerate_devices

SAMPLE_RATES = [250_000, 1_024_000, 1_536_000, 1_792_000, 2_048_000,
                2_400_000, 2_560_000, 2_880_000, 3_200_000]

IF_BW_OPTIONS = [
    (0, N_("Auto")),
    (250_000, "250 kHz"),
    (500_000, "500 kHz"),
    (1_000_000, "1 MHz"),
    (1_500_000, "1.5 MHz"),
    (2_000_000, "2 MHz"),
]


class RFDialog(wx.Frame):
    """Modeless RF settings frame."""

    def __init__(
        self,
        parent: wx.Window,
        settings: Settings,
        on_change: Optional[Callable[[Settings], None]] = None,
        valid_gains: Optional[List[float]] = None,
    ) -> None:
        super().__init__(
            parent,
            title=_("RF Settings"),
            style=wx.DEFAULT_FRAME_STYLE | wx.FRAME_FLOAT_ON_PARENT,
        )
        self.SetName("RF Settings dialog")
        self._settings = settings
        self._on_change = on_change
        self._valid_gains = valid_gains or []
        self._build_ui()
        self.SetSize(400, 480)
        self.Centre()
        speech.output(_("RF Settings dialog opened."))

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

        # Gain — use valid gain values from hardware if available
        grid.Add(wx.StaticText(panel, label=_("RF Gain (dB):")), 0, wx.ALIGN_CENTER_VERTICAL)
        if self._valid_gains:
            gain_labels = [f"{g:.1f} dB" for g in self._valid_gains]
            self._gain_choice = wx.Choice(panel, choices=gain_labels, name="RF Gain")
            # Select closest valid gain
            best = min(range(len(self._valid_gains)),
                       key=lambda i: abs(self._valid_gains[i] - self._settings.gain))
            self._gain_choice.SetSelection(best)
            self._gain_choice.Bind(wx.EVT_CHOICE, self._on_gain_choice)
            grid.Add(self._gain_choice, 1, wx.EXPAND)
            self._gain_slider = None
            self._gain_label = None
        else:
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
            self._gain_slider.Bind(wx.EVT_SLIDER, self._on_gain_slide)
            grid.Add(gain_panel, 1, wx.EXPAND)
            self._gain_choice = None

        # PPM correction
        grid.Add(wx.StaticText(panel, label=_("PPM Correction:")), 0, wx.ALIGN_CENTER_VERTICAL)
        self._ppm_spin = wx.SpinCtrl(
            panel, value=str(self._settings.ppm),
            min=-150, max=150, name="PPM Correction"
        )
        grid.Add(self._ppm_spin, 1, wx.EXPAND)

        # AGC checkbox
        grid.Add(wx.StaticText(panel, label=""), 0)  # empty label cell
        self._agc_cb = wx.CheckBox(panel, label=_("RTL AGC"), name="RTL AGC")
        self._agc_cb.SetValue(self._settings.agc_mode)
        self._agc_cb.Bind(wx.EVT_CHECKBOX, self._on_agc_toggle)
        grid.Add(self._agc_cb, 1, wx.EXPAND)

        # Disable gain control when AGC is active (gain is automatic)
        if self._settings.agc_mode:
            self._set_gain_enabled(False)

        # Offset tuning checkbox
        grid.Add(wx.StaticText(panel, label=""), 0)
        self._offset_cb = wx.CheckBox(
            panel, label=_("Offset Tuning (remove DC spike)"),
            name="Offset Tuning",
        )
        self._offset_cb.SetValue(self._settings.offset_tuning)
        self._offset_cb.Bind(wx.EVT_CHECKBOX, self._on_offset_toggle)
        grid.Add(self._offset_cb, 1, wx.EXPAND)

        # IF Bandwidth
        bw_labels = [_(lbl) if lbl == N_("Auto") else lbl for _bw, lbl in IF_BW_OPTIONS]
        grid.Add(wx.StaticText(panel, label=_("IF Bandwidth:")), 0, wx.ALIGN_CENTER_VERTICAL)
        self._ifbw_choice = wx.Choice(panel, choices=bw_labels, name="IF Bandwidth")
        # Select current value
        bw_idx = 0
        for i, (bw, _lbl) in enumerate(IF_BW_OPTIONS):
            if bw == self._settings.tuner_bandwidth:
                bw_idx = i
                break
        self._ifbw_choice.SetSelection(bw_idx)
        self._ifbw_choice.Bind(wx.EVT_CHOICE, self._on_ifbw_change)
        grid.Add(self._ifbw_choice, 1, wx.EXPAND)

        sizer.Add(grid, 1, wx.EXPAND | wx.ALL, 12)

        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        apply_btn = wx.Button(panel, label=_("Apply"), name="Apply RF settings")
        close_btn = wx.Button(panel, wx.ID_CLOSE, label=_("Close"))
        btn_row.Add(apply_btn, 0, wx.RIGHT, 8)
        btn_row.Add(close_btn, 0)
        sizer.Add(btn_row, 0, wx.ALIGN_RIGHT | wx.ALL, 12)

        panel.SetSizer(sizer)

        # Bindings
        apply_btn.Bind(wx.EVT_BUTTON, self._on_apply)
        close_btn.Bind(wx.EVT_BUTTON, lambda e: self.Close())
        self.Bind(wx.EVT_CHAR_HOOK, self._on_key)

    def _on_gain_choice(self, event: wx.CommandEvent) -> None:
        idx = event.GetSelection()
        if 0 <= idx < len(self._valid_gains):
            val = self._valid_gains[idx]
            speech.output(_("Gain {val} dB").format(val=f"{val:.1f}"))

    def _on_gain_slide(self, event: wx.CommandEvent) -> None:
        val = self._gain_slider.GetValue()
        self._gain_label.SetLabel(f"{val} dB")
        speech.output(_("Gain {val} dB").format(val=val))

    def _on_agc_toggle(self, event: wx.CommandEvent) -> None:
        on = self._agc_cb.GetValue()
        self._set_gain_enabled(not on)
        msg = _("RTL AGC enabled") if on else _("RTL AGC disabled")
        speech.output(msg)

    def _set_gain_enabled(self, enabled: bool) -> None:
        """Enable or disable the gain control (dropdown or slider)."""
        if self._gain_choice is not None:
            self._gain_choice.Enable(enabled)
        if self._gain_slider is not None:
            self._gain_slider.Enable(enabled)

    def _on_offset_toggle(self, event: wx.CommandEvent) -> None:
        on = self._offset_cb.GetValue()
        msg = _("Offset tuning enabled") if on else _("Offset tuning disabled")
        speech.output(msg)

    def _on_ifbw_change(self, event: wx.CommandEvent) -> None:
        idx = event.GetSelection()
        if 0 <= idx < len(IF_BW_OPTIONS):
            bw_val, label = IF_BW_OPTIONS[idx]
            display = _(label) if label == N_("Auto") else label
            speech.output(_("IF Bandwidth {bw}").format(bw=display))

    def _on_apply(self, _event: wx.CommandEvent) -> None:
        self._settings.device_index = self._device_choice.GetSelection()
        rate_idx = self._rate_choice.GetSelection()
        if 0 <= rate_idx < len(SAMPLE_RATES):
            self._settings.sample_rate = SAMPLE_RATES[rate_idx]

        if self._gain_choice is not None:
            idx = self._gain_choice.GetSelection()
            if 0 <= idx < len(self._valid_gains):
                self._settings.gain = self._valid_gains[idx]
        elif self._gain_slider is not None:
            self._settings.gain = float(self._gain_slider.GetValue())

        self._settings.ppm = self._ppm_spin.GetValue()
        self._settings.agc_mode = self._agc_cb.GetValue()
        self._settings.offset_tuning = self._offset_cb.GetValue()

        ifbw_idx = self._ifbw_choice.GetSelection()
        if 0 <= ifbw_idx < len(IF_BW_OPTIONS):
            self._settings.tuner_bandwidth = IF_BW_OPTIONS[ifbw_idx][0]

        self._settings.save()

        if self._on_change:
            self._on_change(self._settings)

        speech.output(
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
