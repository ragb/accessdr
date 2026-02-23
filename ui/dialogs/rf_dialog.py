"""
ui/dialogs/rf_dialog.py — RF Settings dialog.

Allows the user to select SDR device, set gain, sample rate, PPM correction,
AGC, offset tuning, and IF bandwidth.  Changes are applied on OK and
persisted to settings.
"""

from __future__ import annotations

from typing import List, Optional

import wx
from accessibility import speech
from config.settings import Settings
from core.sdr_device import enumerate_devices

SAMPLE_RATES = [250_000, 1_024_000, 1_536_000, 1_792_000, 2_048_000,
                2_400_000, 2_560_000, 2_880_000, 3_200_000]

BUFFER_SIZES = [16_384, 32_768, 65_536, 131_072, 262_144]
BUFFER_LABELS = ["16K", "32K", "64K", "128K", "256K"]

IF_BW_OPTIONS = [
    (0, N_("Auto")),
    (250_000, "250 kHz"),
    (500_000, "500 kHz"),
    (1_000_000, "1 MHz"),
    (1_500_000, "1.5 MHz"),
    (2_000_000, "2 MHz"),
]


class RFDialog(wx.Dialog):
    """Modal RF settings dialog with standard OK / Cancel."""

    def __init__(
        self,
        parent: wx.Window,
        settings: Settings,
        valid_gains: Optional[List[float]] = None,
    ) -> None:
        super().__init__(
            parent,
            title=_("RF Settings"),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self.SetName("RF Settings")
        self._settings = settings
        self._valid_gains = valid_gains or []
        self._build_ui()
        self.Fit()
        self.SetMinSize(self.GetSize())
        self.Centre()

    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)
        grid = wx.FlexGridSizer(cols=2, vgap=8, hgap=8)
        grid.AddGrowableCol(1, 1)

        # --- Device ---
        devices = enumerate_devices()
        self._local_labels = [d.get("label", str(d)) for d in devices] or [_("Default / Auto")]
        self._local_count = len(self._local_labels)
        self._remote_labels = []
        for srv in self._settings.rtl_tcp_servers:
            name = srv.get("name", srv.get("host", "?"))
            host = srv.get("host", "?")
            port = srv.get("port", 1234)
            self._remote_labels.append(f"{name} ({host}:{port})")
        all_labels = self._local_labels + self._remote_labels
        grid.Add(wx.StaticText(panel, label=_("SDR Device:")), 0, wx.ALIGN_CENTER_VERTICAL)
        self._device_choice = wx.Choice(panel, choices=all_labels, name="SDR Device")
        active = self._settings.rtl_tcp_active
        if 0 <= active < len(self._remote_labels):
            self._device_choice.SetSelection(self._local_count + active)
        else:
            idx = min(self._settings.device_index, self._local_count - 1)
            self._device_choice.SetSelection(idx)
        grid.Add(self._device_choice, 1, wx.EXPAND)

        # --- Gain / AGC ---
        grid.Add(wx.StaticText(panel, label=_("RF Gain (dB):")), 0, wx.ALIGN_CENTER_VERTICAL)
        if self._valid_gains:
            gain_labels = [f"{g:.1f} dB" for g in self._valid_gains]
            self._gain_choice = wx.Choice(panel, choices=gain_labels, name="RF Gain")
            best = min(range(len(self._valid_gains)),
                       key=lambda i: abs(self._valid_gains[i] - self._settings.gain))
            self._gain_choice.SetSelection(best)
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

        grid.Add(wx.StaticText(panel, label=""), 0)
        self._agc_cb = wx.CheckBox(panel, label=_("RTL AGC"), name="RTL AGC")
        self._agc_cb.SetValue(self._settings.agc_mode)
        self._agc_cb.Bind(wx.EVT_CHECKBOX, self._on_agc_toggle)
        grid.Add(self._agc_cb, 1, wx.EXPAND)

        if self._settings.agc_mode:
            self._set_gain_enabled(False)

        # --- Sampling ---
        rate_labels = [f"{r // 1000} kHz" for r in SAMPLE_RATES]
        grid.Add(wx.StaticText(panel, label=_("Sample Rate:")), 0, wx.ALIGN_CENTER_VERTICAL)
        self._rate_choice = wx.Choice(panel, choices=rate_labels, name="Sample Rate")
        try:
            rate_idx = SAMPLE_RATES.index(self._settings.sample_rate)
        except ValueError:
            rate_idx = 5           # default 2.4 MSPS
        self._rate_choice.SetSelection(rate_idx)
        grid.Add(self._rate_choice, 1, wx.EXPAND)

        grid.Add(wx.StaticText(panel, label=_("IQ Buffer Size:")), 0, wx.ALIGN_CENTER_VERTICAL)
        self._buf_choice = wx.Choice(panel, choices=BUFFER_LABELS, name="IQ Buffer Size")
        try:
            buf_idx = BUFFER_SIZES.index(self._settings.sdr_buffer_size)
        except ValueError:
            buf_idx = 2  # default 64K
        self._buf_choice.SetSelection(buf_idx)
        grid.Add(self._buf_choice, 1, wx.EXPAND)

        bw_labels = [_(lbl) if lbl == N_("Auto") else lbl for _bw, lbl in IF_BW_OPTIONS]
        grid.Add(wx.StaticText(panel, label=_("IF Bandwidth:")), 0, wx.ALIGN_CENTER_VERTICAL)
        self._ifbw_choice = wx.Choice(panel, choices=bw_labels, name="IF Bandwidth")
        bw_idx = 0
        for i, (bw, _lbl) in enumerate(IF_BW_OPTIONS):
            if bw == self._settings.tuner_bandwidth:
                bw_idx = i
                break
        self._ifbw_choice.SetSelection(bw_idx)
        grid.Add(self._ifbw_choice, 1, wx.EXPAND)

        # --- Calibration ---
        grid.Add(wx.StaticText(panel, label=_("PPM Correction:")), 0, wx.ALIGN_CENTER_VERTICAL)
        self._ppm_spin = wx.SpinCtrl(
            panel, value=str(self._settings.ppm),
            min=-150, max=150, name="PPM Correction"
        )
        grid.Add(self._ppm_spin, 1, wx.EXPAND)

        grid.Add(wx.StaticText(panel, label=""), 0)
        self._offset_cb = wx.CheckBox(
            panel, label=_("Offset Tuning (remove DC spike)"),
            name="Offset Tuning",
        )
        self._offset_cb.SetValue(self._settings.offset_tuning)
        grid.Add(self._offset_cb, 1, wx.EXPAND)

        grid.Add(wx.StaticText(panel, label=""), 0)
        self._bias_tee_cb = wx.CheckBox(
            panel, label=_("Bias Tee (powers antenna via coax)"),
            name="Bias Tee",
        )
        self._bias_tee_cb.SetValue(self._settings.bias_tee)
        self._bias_tee_cb.Bind(wx.EVT_CHECKBOX, self._on_bias_tee_toggle)
        grid.Add(self._bias_tee_cb, 1, wx.EXPAND)

        # --- Processing ---
        grid.Add(wx.StaticText(panel, label=""), 0)
        self._nb_cb = wx.CheckBox(
            panel, label=_("Noise Blanker"), name="Noise Blanker",
        )
        self._nb_cb.SetValue(self._settings.noise_blanker_enabled)
        grid.Add(self._nb_cb, 1, wx.EXPAND)

        grid.Add(
            wx.StaticText(panel, label=_("NB Threshold:")), 0, wx.ALIGN_CENTER_VERTICAL,
        )
        self._nb_thresh = wx.SpinCtrlDouble(
            panel,
            value=f"{self._settings.noise_blanker_threshold:.1f}",
            min=1.0, max=50.0, inc=1.0,
            name="Noise Blanker Threshold",
        )
        self._nb_thresh.SetDigits(1)
        grid.Add(self._nb_thresh, 1, wx.EXPAND)

        sizer.Add(grid, 1, wx.EXPAND | wx.ALL, 12)
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

    def _on_gain_slide(self, event: wx.CommandEvent) -> None:
        val = self._gain_slider.GetValue()
        self._gain_label.SetLabel(f"{val} dB")

    def _on_agc_toggle(self, event: wx.CommandEvent) -> None:
        on = self._agc_cb.GetValue()
        self._set_gain_enabled(not on)

    def _on_bias_tee_toggle(self, event: wx.CommandEvent) -> None:
        if not self._bias_tee_cb.GetValue():
            return  # unchecking — no confirmation needed
        dlg = wx.MessageDialog(
            self,
            _(
                "Bias Tee supplies 4.5 V DC through the antenna connector.\n\n"
                "WARNING: This can damage devices or antennas that are not\n"
                "designed for bias-T power. Only enable this if you are using\n"
                "an RTL-SDR V3 (or compatible) with a powered LNA, active\n"
                "antenna, or bias-T powered filter.\n\n"
                "Enable Bias Tee?"
            ),
            _("Bias Tee — Danger"),
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING,
        )
        if dlg.ShowModal() != wx.ID_YES:
            self._bias_tee_cb.SetValue(False)
        dlg.Destroy()

    def _set_gain_enabled(self, enabled: bool) -> None:
        if self._gain_choice is not None:
            self._gain_choice.Enable(enabled)
        if self._gain_slider is not None:
            self._gain_slider.Enable(enabled)

    def _on_ok(self, _event: wx.CommandEvent) -> None:
        sel = self._device_choice.GetSelection()
        if sel >= self._local_count:
            self._settings.rtl_tcp_active = sel - self._local_count
        else:
            self._settings.rtl_tcp_active = -1
            self._settings.device_index = sel
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
        self._settings.bias_tee = self._bias_tee_cb.GetValue()

        ifbw_idx = self._ifbw_choice.GetSelection()
        if 0 <= ifbw_idx < len(IF_BW_OPTIONS):
            self._settings.tuner_bandwidth = IF_BW_OPTIONS[ifbw_idx][0]

        self._settings.noise_blanker_enabled = self._nb_cb.GetValue()
        self._settings.noise_blanker_threshold = self._nb_thresh.GetValue()

        buf_idx = self._buf_choice.GetSelection()
        if 0 <= buf_idx < len(BUFFER_SIZES):
            self._settings.sdr_buffer_size = BUFFER_SIZES[buf_idx]

        self._settings.save()
        self.EndModal(wx.ID_OK)
