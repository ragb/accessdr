"""
ui/main_window.py — AccessDR main application window.

Hosts the primary radio controls (frequency, mode, bandwidth, start/stop,
volume, squelch) and coordinates the SDR device, DSP processing, and audio
output.  DSP runs inline in the SDR capture callback; cross-thread
communication to the UI is via wx.CallAfter.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import wx

from accessibility import speech
from accessibility.sonification import Sonification
from config.channels import Channel, ChannelMapStore
from config.modes import (
    AUDIO_RATE, BW_OPTIONS, MODE_KEYS, MODES,
    STEP_LABELS, STEPS,
)
from config.scenes import Scene, SceneStore
from config.settings import Settings
from core.operating_mode import OperatingState, OpMode
from core.audio import AudioOutput
from core.dsp.noise_blanker import NoiseBlanker
from core.dsp.pipeline import PipelineCallbacks
from core.platform_utils import elevate_process_priority
from core.scanner import Scanner
from core.signal_utils import s_meter
from ui.cursor_controller import CursorController
from ui.formatting import fmt_freq, freq_number, freq_unit, parse_freq
from ui.radio_controller import RadioController
from ui.spectrum_controller import SpectrumController
from ui.spectrum_panel import SpectrumPanel

logger = logging.getLogger(__name__)

elevate_process_priority()


class MainWindow(wx.Frame):
    """Primary application window."""

    def __init__(self, parent, title: str) -> None:
        super().__init__(parent, title=title, size=(640, 560))
        self.SetName("AccessDR Main Window")

        # Load persisted settings
        self._settings = Settings.load()

        # Core objects
        self._audio = AudioOutput(
            sample_rate=AUDIO_RATE,
            device=self._settings.audio_device,
            blocksize=self._settings.audio_buffer_size,
        )
        self._audio.volume = self._settings.volume
        self._audio.squelch = self._settings.squelch
        self._audio.muted = self._settings.muted
        self._noise_blanker = NoiseBlanker(self._settings.noise_blanker_threshold)
        self._noise_blanker.enabled = self._settings.noise_blanker_enabled
        self._radio = RadioController(self._settings, self._audio, self._noise_blanker)
        self._radio.set_error_callback(self._on_sdr_error)
        self._sonification = Sonification(
            min_pitch=self._settings.sonification_min_hz,
            max_pitch=self._settings.sonification_max_hz,
            sweep_speed=self._settings.sonification_sweep_speed,
            spectrum_averaging_ms=self._settings.spectrum_averaging_ms,
            pitch_smoothing_ms=self._settings.pitch_smoothing_ms,
        )
        self._sonification.set_on_finish(self._on_sweep_finished)
        self._sync_sonification_device()
        self._scanner = Scanner(
            set_frequency_cb=self._tune,
            get_signal_db_cb=lambda: self._audio.signal_db,
            dispatcher=wx.CallAfter,
        )
        self._scenes = SceneStore()
        self._scenes.load()
        self._channels = ChannelMapStore()
        self._channels.load()

        # Operating mode (VFO/MR), restored from persisted settings.
        restored_scene = (
            self._scenes.by_name(self._settings.active_scene)
            if self._settings.active_scene else None
        ) or self._scenes.free_scene()
        try:
            restored_mode = OpMode(self._settings.op_mode)
        except ValueError:
            restored_mode = OpMode.VFO
        self._opstate = OperatingState(
            scene=restored_scene,
            channel_map=self._channels.active_map(),
            mode=restored_mode,
        )
        self._opstate.channel_index = self._settings.active_channel

        # Runtime state
        self._step_idx = STEPS.index(self._settings.step) if self._settings.step in STEPS else 3
        self._last_spectrum: Optional[np.ndarray] = None
        self._sweeping: bool = False               # continuous sweep running
        self._mode_pending: bool = False           # waiting for mode letter after M
        self._above_threshold: bool = False        # auto-announce threshold state
        self._recording_path: str = ""               # current recording file path

        # Open dialogs cache (so we don't create duplicates)
        self._dialogs: dict = {}

        self._build_menu()
        self._build_ui()
        self._build_status_bar()

        # Controllers (created after _build_ui so widgets exist)
        self._spectrum_ctrl = SpectrumController(self._settings, self._spectrum_panel)
        self._cursor = CursorController(
            self, self._settings, self._sonification,
            self._spectrum_panel, self._spectrum_ctrl,
            tune_cb=self._tune, duck_cb=self._audio.duck,
            freq_ctrl=self._freq_ctrl,
        )
        self._spectrum_panel.set_cursor_click_callback(self._cursor.on_spectrum_click)
        self._action_table = self._build_dispatch_table()

        self.Bind(wx.EVT_CLOSE, self._on_close)
        self.Bind(wx.EVT_CHAR_HOOK, self._on_key)

        self._apply_settings_to_ui()

    # ==================================================================
    # UI construction
    # ==================================================================

    def _build_menu(self) -> None:
        mb = wx.MenuBar()

        # File
        file_menu = wx.Menu()
        file_menu.Append(wx.ID_EXIT, _("E&xit\tAlt+F4"))
        mb.Append(file_menu, _("&File"))

        # Radio
        radio_menu = wx.Menu()
        item_freq = radio_menu.Append(wx.ID_ANY, _("&Enter Frequency…\tCtrl+Q"))
        radio_menu.AppendSeparator()
        item_scenes = radio_menu.Append(wx.ID_ANY, _("&Scenes (bands)…\tCtrl+Shift+B"))
        item_channels = radio_menu.Append(wx.ID_ANY, _("&Channels…\tCtrl+B"))
        item_scanner = radio_menu.Append(wx.ID_ANY, _("Sca&nner…\tCtrl+N"))
        self.Bind(wx.EVT_MENU, self._on_enter_freq_menu, item_freq)
        self.Bind(wx.EVT_MENU, lambda e: self._open_scenes_dialog(), item_scenes)
        self.Bind(wx.EVT_MENU, lambda e: self._open_channels_dialog(), item_channels)
        self.Bind(wx.EVT_MENU, lambda e: self._open_scanner_dialog(), item_scanner)
        mb.Append(radio_menu, _("&Radio"))

        # Options
        options_menu = wx.Menu()
        item_rf = options_menu.Append(wx.ID_ANY, _("&RF Settings…\tCtrl+R"))
        item_spectrum = options_menu.Append(wx.ID_ANY, _("&Spectrum Settings…\tCtrl+S"))
        item_audio = options_menu.Append(wx.ID_ANY, _("&Audio Settings…\tCtrl+D"))
        item_rec = options_menu.Append(wx.ID_ANY, _("R&ecording Settings…\tCtrl+E"))
        item_wfm = options_menu.Append(wx.ID_ANY, _("&WFM Settings…\tCtrl+W"))
        item_nfm = options_menu.Append(wx.ID_ANY, _("&NFM Settings…"))
        options_menu.AppendSeparator()
        item_rtl_tcp = options_menu.Append(wx.ID_ANY, _("Remote SD&R…\tCtrl+G"))
        self.Bind(wx.EVT_MENU, lambda e: self._open_rf_dialog(), item_rf)
        self.Bind(wx.EVT_MENU, lambda e: self._open_spectrum_dialog(), item_spectrum)
        self.Bind(wx.EVT_MENU, lambda e: self._open_audio_dialog(), item_audio)
        self.Bind(wx.EVT_MENU, lambda e: self._open_recording_dialog(), item_rec)
        self.Bind(wx.EVT_MENU, lambda e: self._open_wfm_dialog(), item_wfm)
        self.Bind(wx.EVT_MENU, lambda e: self._open_nfm_dialog(), item_nfm)
        self.Bind(wx.EVT_MENU, lambda e: self._open_rtl_tcp_dialog(), item_rtl_tcp)
        mb.Append(options_menu, _("&Options"))

        # Help
        help_menu = wx.Menu()
        item_guide = help_menu.Append(wx.ID_ANY, _("&User Guide…\tCtrl+H"))
        help_menu.Append(wx.ID_HELP, _("&Keyboard Shortcuts…\tF1"))
        help_menu.AppendSeparator()
        help_menu.Append(wx.ID_ABOUT, _("&About AccessDR"))
        self.Bind(wx.EVT_MENU, self._on_open_user_guide, item_guide)
        mb.Append(help_menu, _("&Help"))

        self.SetMenuBar(mb)

        # Bind standard IDs
        self.Bind(wx.EVT_MENU, self._on_exit, id=wx.ID_EXIT)
        self.Bind(wx.EVT_MENU, self._on_open_help, id=wx.ID_HELP)
        self.Bind(wx.EVT_MENU, self._on_open_about, id=wx.ID_ABOUT)

    def _build_ui(self) -> None:
        panel = wx.Panel(self)
        panel.SetName("Main controls panel")
        outer = wx.BoxSizer(wx.VERTICAL)

        # --- Frequency row ---
        freq_row = wx.BoxSizer(wx.HORIZONTAL)
        freq_label = wx.StaticText(panel, label=_("Frequency:"))
        self._freq_ctrl = wx.TextCtrl(
            panel,
            value=fmt_freq(self._settings.frequency),
            name="Frequency display",
            size=(160, -1),
        )
        self._freq_ctrl.SetEditable(False)

        tune_up = wx.Button(panel, label="\u25b2", name="Tune up", size=(32, -1))
        tune_dn = wx.Button(panel, label="\u25bc", name="Tune down", size=(32, -1))
        tune_up.Bind(wx.EVT_BUTTON, lambda e: self._step_frequency(+1))
        tune_dn.Bind(wx.EVT_BUTTON, lambda e: self._step_frequency(-1))
        # Keep for mouse users but skip in keyboard tab order.
        def _skip_focus(evt):
            btn = evt.GetEventObject()
            if wx.GetKeyState(wx.WXK_SHIFT):
                btn.Navigate(wx.NavigationKeyEvent.IsBackward)
            else:
                btn.Navigate(wx.NavigationKeyEvent.IsForward)
        for btn in (tune_up, tune_dn):
            btn.Bind(wx.EVT_SET_FOCUS, _skip_focus)

        step_label = wx.StaticText(panel, label=_("Step:"))
        self._step_choice = wx.Choice(
            panel, choices=[_(s) for s in STEP_LABELS], name="Tuning step"
        )
        self._step_choice.SetSelection(self._step_idx)
        self._step_choice.Bind(wx.EVT_CHOICE, self._on_step_change)

        for w in (freq_label, self._freq_ctrl, tune_up, tune_dn, step_label, self._step_choice):
            freq_row.Add(w, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        outer.Add(freq_row, 0, wx.ALL, 8)

        # --- Mode / BW row ---
        mode_row = wx.BoxSizer(wx.HORIZONTAL)
        mode_label = wx.StaticText(panel, label=_("Mode:"))
        self._mode_choice = wx.Choice(panel, choices=MODES, name="Demodulation mode")
        self._mode_choice.SetStringSelection(self._settings.mode)
        self._mode_choice.Bind(wx.EVT_CHOICE, self._on_mode_change)

        bw_label = wx.StaticText(panel, label=_("BW:"))
        self._bw_choice = wx.Choice(panel, choices=[], name="Filter bandwidth")
        self._bw_choice.Bind(wx.EVT_CHOICE, self._on_bw_change)

        for w in (mode_label, self._mode_choice, bw_label, self._bw_choice):
            mode_row.Add(w, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        outer.Add(mode_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # --- Start/Stop + Signal ---
        ctrl_row = wx.BoxSizer(wx.HORIZONTAL)
        self._start_btn = wx.Button(panel, label=_("\u25b6 Start"), name="Start radio")
        self._start_btn.Bind(wx.EVT_BUTTON, self._on_start_stop)
        self._signal_lbl = wx.StaticText(
            panel, label=_("Signal: —"), name="Signal strength display"
        )
        for w in (self._start_btn, self._signal_lbl):
            ctrl_row.Add(w, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        outer.Add(ctrl_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # --- Volume row ---
        vol_row = wx.BoxSizer(wx.HORIZONTAL)
        vol_label = wx.StaticText(panel, label=_("Volume:"))
        self._vol_slider = wx.Slider(
            panel, value=int(self._settings.volume * 100),
            minValue=0, maxValue=100,
            style=wx.SL_HORIZONTAL,
            name="Volume slider",
            size=(140, -1),
        )
        self._vol_slider.Bind(wx.EVT_SLIDER, self._on_volume)
        self._mute_btn = wx.ToggleButton(panel, label=_("Mute (M)"), name="Mute toggle")
        self._mute_btn.SetValue(self._settings.muted)
        self._mute_btn.Bind(wx.EVT_TOGGLEBUTTON, self._on_mute)

        for w in (vol_label, self._vol_slider, self._mute_btn):
            vol_row.Add(w, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        outer.Add(vol_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # --- Squelch row ---
        sq_row = wx.BoxSizer(wx.HORIZONTAL)
        sq_label = wx.StaticText(panel, label=_("Squelch (dBm):"))
        self._sq_slider = wx.Slider(
            panel, value=int(self._settings.squelch),
            minValue=-120, maxValue=0,
            style=wx.SL_HORIZONTAL,
            name="Squelch slider",
            size=(140, -1),
        )
        self._sq_slider.Bind(wx.EVT_SLIDER, self._on_squelch)
        self._sq_lbl = wx.StaticText(
            panel, label=f"{self._settings.squelch:.0f} dBm", name="Squelch level display"
        )
        for w in (sq_label, self._sq_slider, self._sq_lbl):
            sq_row.Add(w, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        outer.Add(sq_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # --- Sweep toggle button ---
        sweep_row = wx.BoxSizer(wx.HORIZONTAL)
        self._sweep_btn = wx.ToggleButton(
            panel, label=_("Start Sweep (Ctrl+F5)"), name="Toggle continuous sweep"
        )
        self._sweep_btn.Bind(wx.EVT_TOGGLEBUTTON, self._on_sweep_toggle)
        sweep_row.Add(self._sweep_btn, 0, wx.ALIGN_CENTER_VERTICAL)
        outer.Add(sweep_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # --- Spectrum display ---
        self._spectrum_panel = SpectrumPanel(panel, self._sonification, self._settings)
        outer.Add(self._spectrum_panel, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        panel.SetSizer(outer)

        # Tab order
        self._freq_ctrl.MoveBeforeInTabOrder(self._step_choice)
        self._step_choice.MoveBeforeInTabOrder(self._mode_choice)
        self._mode_choice.MoveBeforeInTabOrder(self._bw_choice)
        self._bw_choice.MoveBeforeInTabOrder(self._start_btn)
        self._start_btn.MoveBeforeInTabOrder(self._vol_slider)
        self._vol_slider.MoveBeforeInTabOrder(self._mute_btn)
        self._mute_btn.MoveBeforeInTabOrder(self._sq_slider)
        self._sq_slider.MoveBeforeInTabOrder(self._sweep_btn)

        # Prevent native Left/Right handling on widgets that would steal
        # arrow keys from the spectrum cursor (horizontal sliders, choices).
        def _eat_left_right(event: wx.KeyEvent) -> None:
            code = event.GetKeyCode()
            if code in (wx.WXK_LEFT, wx.WXK_RIGHT) and event.GetModifiers() in (0, wx.MOD_CONTROL):
                return  # consumed — main _on_key handler will process
            event.Skip()
        for w in (self._step_choice, self._mode_choice, self._bw_choice,
                  self._vol_slider, self._sq_slider, self._sweep_btn):
            w.Bind(wx.EVT_KEY_DOWN, _eat_left_right)

        self._update_bw_choices(self._settings.mode)

    def _build_status_bar(self) -> None:
        self._statusbar = self.CreateStatusBar(name="Status bar")
        self._statusbar.SetStatusText(_("Ready — no device connected."))

    # ==================================================================
    # Settings → UI sync
    # ==================================================================

    def _apply_settings_to_ui(self) -> None:
        self._freq_ctrl.SetValue(fmt_freq(self._settings.frequency))
        if self._settings.mode in MODES:
            self._mode_choice.SetStringSelection(self._settings.mode)
        self._update_bw_choices(self._settings.mode)
        self._vol_slider.SetValue(int(self._settings.volume * 100))
        self._mute_btn.SetValue(self._settings.muted)
        self._sq_slider.SetValue(int(self._settings.squelch))
        self._sq_lbl.SetLabel(f"{self._settings.squelch:.0f} dBm")

    # ==================================================================
    # Frequency control
    # ==================================================================

    def _tune(self, freq_hz: int) -> None:
        """Set frequency (may be called from any thread)."""
        self._settings.frequency = freq_hz
        self._radio.set_frequency(freq_hz)
        listen = int(freq_hz + self._cursor.demod_offset)
        wx.CallAfter(self._freq_ctrl.SetValue, fmt_freq(listen))
        wx.CallAfter(speech.output, fmt_freq(listen))
        wx.CallAfter(
            self._statusbar.SetStatusText,
            _("Tuned to {freq}").format(freq=fmt_freq(listen)),
        )
        wx.CallAfter(self._cursor._update_demod_marker)

    def _step_frequency(self, direction: int) -> None:
        step = STEPS[self._step_idx]
        new_freq = self._settings.frequency + direction * step
        new_freq = max(100_000, new_freq)
        self._tune(new_freq)

    def _on_enter_freq_menu(self, _event: wx.CommandEvent) -> None:
        self._open_freq_dialog()

    def _open_freq_dialog(self) -> None:
        """Open a modal dialog to enter a new frequency."""
        cur_hz = self._settings.frequency
        unit = freq_unit(cur_hz)
        dlg = wx.TextEntryDialog(
            self,
            _("Enter frequency ({unit}):").format(unit=unit),
            _("Tune to Frequency"),
            value=freq_number(cur_hz),
        )
        if dlg.ShowModal() == wx.ID_OK:
            try:
                freq_hz = parse_freq(dlg.GetValue(), default_unit=unit)
            except ValueError:
                speech.output(_("Invalid frequency."))
                dlg.Destroy()
                return
            self._cursor.reset_offset()
            self._tune(freq_hz)
        dlg.Destroy()

    def _open_demod_freq_dialog(self) -> None:
        """Open a modal dialog to set the demod (listening) frequency."""
        cur_hz = int(self._cursor.listening_freq())
        unit = freq_unit(cur_hz)
        dlg = wx.TextEntryDialog(
            self,
            _("Enter listening frequency ({unit}):").format(unit=unit),
            _("Set Listening Frequency"),
            value=freq_number(cur_hz),
        )
        if dlg.ShowModal() == wx.ID_OK:
            try:
                freq_hz = parse_freq(dlg.GetValue(), default_unit=unit)
            except ValueError:
                speech.output(_("Invalid frequency."))
                dlg.Destroy()
                return
            offset = freq_hz - self._settings.frequency
            self._cursor.set_demod_offset(offset)
            speech.output(_("Listening {freq}").format(freq=fmt_freq(self._cursor.listening_freq())))
        dlg.Destroy()

    def _on_step_change(self, event: wx.CommandEvent) -> None:
        self._step_idx = event.GetSelection()
        self._settings.step = STEPS[self._step_idx]
        speech.output(_("Step {step}").format(step=_(STEP_LABELS[self._step_idx])))

    def _cycle_step(self) -> None:
        self._step_idx = (self._step_idx + 1) % len(STEPS)
        self._step_choice.SetSelection(self._step_idx)
        self._settings.step = STEPS[self._step_idx]
        speech.output(_("Step {step}").format(step=_(STEP_LABELS[self._step_idx])))

    # ==================================================================
    # Mode / bandwidth control
    # ==================================================================

    def _update_bw_choices(self, mode: str) -> None:
        options = BW_OPTIONS.get(mode, [])
        self._bw_choice.Clear()
        for _, label in options:
            self._bw_choice.Append(label)
        if options:
            self._bw_choice.SetSelection(0)
            self._settings.bandwidth = options[0][0]

    def _on_mode_change(self, event: wx.CommandEvent) -> None:
        mode = event.GetString()
        self._settings.mode = mode
        self._update_bw_choices(mode)
        wfm_kw = self._radio.wfm_kwargs() if mode == "WFM" else {}
        nfm_kw = self._radio.nfm_kwargs() if mode == "NFM" else {}
        self._radio.set_mode(mode, wfm_kw, nfm_kw)
        speech.output(_("Mode {mode}").format(mode=mode))

    def _on_bw_change(self, event: wx.CommandEvent) -> None:
        mode = self._mode_choice.GetStringSelection()
        options = BW_OPTIONS.get(mode, [])
        idx = event.GetSelection()
        if 0 <= idx < len(options):
            self._settings.bandwidth = options[idx][0]
            speech.output(_("Bandwidth {bw}").format(bw=options[idx][1]))

    def _set_mode(self, mode: str) -> None:
        if mode not in MODES:
            return
        self._mode_choice.SetStringSelection(mode)
        self._settings.mode = mode
        self._update_bw_choices(mode)
        wfm_kw = self._radio.wfm_kwargs() if mode == "WFM" else {}
        nfm_kw = self._radio.nfm_kwargs() if mode == "NFM" else {}
        self._radio.set_mode(mode, wfm_kw, nfm_kw)
        speech.output(_("Mode {mode}").format(mode=mode))

    def _set_bandwidth(self, value: int) -> None:
        """Select a bandwidth value, syncing the choice control.

        ``settings.bandwidth`` is not consumed by the DSP pipeline (demod
        kwargs carry the filtering), so this just records the value and
        reflects it in the UI for consistency.
        """
        self._settings.bandwidth = value
        options = BW_OPTIONS.get(self._settings.mode, [])
        for idx, (bw, _label) in enumerate(options):
            if bw == value:
                self._bw_choice.SetSelection(idx)
                break

    # ==================================================================
    # Operating mode (VFO / MR), scenes and channels
    # ==================================================================

    def _page_nav(self, direction: int) -> None:
        """PageUp/Down: channel step in MR mode, frequency step in VFO."""
        res = self._opstate.step(
            direction, self._settings.frequency, STEPS[self._step_idx]
        )
        if res.mode is OpMode.VFO:
            if res.frequency is not None:
                self._cursor.reset_offset()
                self._tune(res.frequency)
                if res.at_edge:
                    speech.output(_("Band edge"))
        elif res.channel is None:
            speech.output(_("No channels in this map."))
        else:
            self._load_channel(res.channel)

    def _load_channel(self, ch: Channel) -> None:
        """Tune to a channel and announce number, label, frequency."""
        self._cursor.reset_offset()
        self._set_mode(ch.mode)
        self._set_bandwidth(ch.bandwidth)
        self._tune(ch.frequency)
        speech.output(
            _("Channel {n}, {label}, {freq}").format(
                n=ch.number, label=ch.label, freq=fmt_freq(ch.frequency)
            )
        )

    def _toggle_vfo_mr(self) -> None:
        """Toggle between VFO (free/scene) and MR (channel memory)."""
        mode = self._opstate.toggle_mode()
        if mode is OpMode.MR:
            ch = self._opstate.current_channel()
            if ch is None:
                speech.output(_("Memory mode. No channels."))
            else:
                self._load_channel(ch)
        else:
            speech.output(
                _("VFO mode. {scene}").format(scene=self._opstate.scene.name)
            )

    def _apply_scene(self, scene: Scene) -> None:
        """Apply a scene's demod setup and tune into its band."""
        self._opstate.set_scene(scene)
        self._set_mode(scene.mode)
        self._set_bandwidth(scene.bandwidth)
        if scene.nfm_deviation is not None:
            self._settings.nfm_deviation = scene.nfm_deviation
            self._radio.rebuild_nfm()
        if scene.wfm_deemphasis is not None:
            self._settings.wfm_deemphasis = scene.wfm_deemphasis
            self._radio.rebuild_wfm()
        if scene.squelch is not None:
            self._settings.squelch = scene.squelch
            self._audio.squelch = scene.squelch
            self._sq_slider.SetValue(int(scene.squelch))
            self._sq_lbl.SetLabel(f"{scene.squelch:.0f} dBm")
        landing = scene.landing_freq()
        if landing is not None:
            self._cursor.reset_offset()
            self._tune(landing)
        speech.output(_("Scene {name}").format(name=scene.name))

    def _cycle_scene(self, direction: int) -> None:
        """Select the next/previous scene (VFO mode only)."""
        if self._opstate.mode is not OpMode.VFO:
            speech.output(_("Scenes are available in VFO mode."))
            return
        scenes = self._scenes.get_all()
        if not scenes:
            return
        names = [s.name for s in scenes]
        try:
            idx = names.index(self._opstate.scene.name)
        except ValueError:
            idx = 0
        self._apply_scene(scenes[(idx + direction) % len(scenes)])

    # ==================================================================
    # Start / Stop
    # ==================================================================

    def _on_start_stop(self, _event: wx.CommandEvent) -> None:
        if self._radio.paused:
            self._stop_radio()
        elif self._radio.running:
            self._stop_radio()
        else:
            self._start_radio()

    def _start_radio(self) -> None:
        callbacks = PipelineCallbacks(
            on_spectrum=lambda s: wx.CallAfter(self._on_spectrum_update, s),
            on_stereo_change=lambda st: wx.CallAfter(self._on_stereo_change, st),
            on_rds_station=lambda n: wx.CallAfter(self._on_rds_station, n),
        )
        if not self._radio.start(callbacks):
            speech.output(_("Could not open SDR device."))
            return
        self._cursor.set_pipeline(self._radio.pipeline)
        self._start_btn.SetLabel(_("\u25a0 Stop"))
        status = _("Receiving — {freq}").format(freq=fmt_freq(self._cursor.listening_freq()))
        srv = self._settings.active_rtl_tcp_server()
        if srv is not None:
            status += _(" [Remote: {name}]").format(name=srv.get("name", ""))
        self._statusbar.SetStatusText(status)
        speech.output(_("Radio started."))

    def _stop_radio(self) -> None:
        self._radio.stop()
        self._cursor.set_pipeline(None)
        self._signal_lbl.SetLabel(_("Signal: —"))
        self._start_btn.SetLabel(_("\u25b6 Start"))
        self._statusbar.SetStatusText(_("Stopped."))
        speech.output(_("Radio stopped."))

    def _toggle_pause(self) -> None:
        """Toggle pause/resume."""
        if not self._radio.running and not self._radio.paused:
            return
        if not self._radio.paused:
            self._radio.pause()
            listen = self._cursor.listening_freq()
            self._start_btn.SetLabel(_("▶ Resume"))
            self._statusbar.SetStatusText(
                _("Paused — {freq}").format(freq=fmt_freq(listen))
            )
            speech.output(_("Paused."))
        else:
            self._radio.resume()
            listen = self._cursor.listening_freq()
            self._start_btn.SetLabel(_("■ Stop"))
            self._statusbar.SetStatusText(
                _("Receiving — {freq}").format(freq=fmt_freq(listen))
            )
            speech.output(_("Resumed."))

    # ==================================================================
    # DSP pipeline callbacks (dispatched to UI thread)
    # ==================================================================

    def _on_stereo_change(self, stereo: bool) -> None:
        """Called on UI thread when WFM stereo state changes."""
        label = _("Stereo") if stereo else _("Mono")
        listen = self._cursor.listening_freq()
        self._statusbar.SetStatusText(
            _("Receiving — {freq} [{label}]").format(
                freq=fmt_freq(listen), label=label
            ),
        )

    def _on_rds_station(self, name: str) -> None:
        """Called on UI thread when RDS station name changes."""
        speech.output(_("RDS: {name}").format(name=name))

    def _on_spectrum_update(self, spectrum: np.ndarray) -> None:
        """Called on UI thread with updated spectrum data."""
        self._last_spectrum = spectrum

        # Update signal strength display
        strength = self._audio.signal_db
        s_unit = s_meter(strength)
        self._signal_lbl.SetLabel(
            _("Signal: {db:.1f} dBFS  [{s_unit}]").format(
                db=strength, s_unit=s_unit,
            )
        )

        # Feed spectrum panel
        self._spectrum_panel.set_data(
            spectrum, self._settings.frequency, self._settings.sample_rate,
        )

        # Feed sonification (zoomed slice so sweep covers only visible range)
        if self._settings.sonification_enabled:
            self._sonification.set_spectrum(self._spectrum_ctrl.zoom_slice(spectrum))

        # Update probe tone with latest spectrum data
        if self._cursor.cursor_active:
            self._sonification.update_probe(self._cursor.cursor_pos)

        # Update spectrum panel accessible name with current range
        start_hz, end_hz = self._spectrum_ctrl.spectrum_range()
        self._spectrum_panel.SetName(
            _("Spectrum {start} to {end}").format(
                start=fmt_freq(int(start_hz)),
                end=fmt_freq(int(end_hz)),
            )
        )

        # Auto-announce strong signals — speak once per threshold crossing
        threshold = self._settings.auto_announce_threshold
        if strength >= threshold and not self._above_threshold:
            self._above_threshold = True
            speech.output(
                _("Signal {s_unit}, {db:.0f} dBFS").format(
                    s_unit=s_unit, db=strength
                )
            )
        elif strength < threshold - 3:
            self._above_threshold = False

    # ==================================================================
    # Volume / Squelch / Mute
    # ==================================================================

    def _on_volume(self, event: wx.CommandEvent) -> None:
        val = event.GetInt() / 100.0
        self._audio.volume = val
        self._settings.volume = val
        speech.output(_("Volume {v} percent").format(v=event.GetInt()))

    def _on_mute(self, event: wx.CommandEvent) -> None:
        muted = self._mute_btn.GetValue()
        self._audio.muted = muted
        self._settings.muted = muted
        speech.output(_("Muted") if muted else _("Unmuted"))

    def _on_squelch(self, event: wx.CommandEvent) -> None:
        val = float(event.GetInt())
        self._audio.squelch = val
        self._settings.squelch = val
        self._sq_lbl.SetLabel(f"{val:.0f} dBm")
        speech.output(_("Squelch {val:.0f} dBm").format(val=val))

    def _adjust_volume(self, delta_pct: int) -> None:
        """Change volume by *delta_pct* percentage points and announce."""
        pct = max(0, min(100, int(self._settings.volume * 100) + delta_pct))
        val = pct / 100.0
        self._audio.volume = val
        self._settings.volume = val
        self._vol_slider.SetValue(pct)
        speech.output(_("Volume {v} percent").format(v=pct))

    def _adjust_squelch(self, delta_db: int) -> None:
        """Change squelch by *delta_db* dB and announce."""
        val = max(-120.0, min(0.0, self._settings.squelch + delta_db))
        self._audio.squelch = val
        self._settings.squelch = val
        self._sq_slider.SetValue(int(val))
        self._sq_lbl.SetLabel(f"{val:.0f} dBm")
        speech.output(_("Squelch {val:.0f} dBm").format(val=val))

    # ==================================================================
    # Noise blanker
    # ==================================================================

    def _toggle_noise_blanker(self) -> None:
        self._noise_blanker.enabled = not self._noise_blanker.enabled
        self._settings.noise_blanker_enabled = self._noise_blanker.enabled
        speech.output(
            _("Noise blanker on") if self._noise_blanker.enabled
            else _("Noise blanker off")
        )

    # ==================================================================
    # Sweep control
    # ==================================================================

    def _on_sweep_toggle(self, _event: wx.CommandEvent) -> None:
        self._toggle_sweep()

    def _toggle_sweep(self) -> None:
        if self._sweeping:
            self._sonification.stop()
            self._audio.duck(1.0)
            self._sweeping = False
            self._sweep_btn.SetValue(False)
            self._sweep_btn.SetLabel(_("Start Sweep (Ctrl+F5)"))
            speech.output(_("Continuous sweep stopped."))
        else:
            self._settings.sonification_enabled = True
            self._audio.duck(0.1)
            self._sonification.start_sweep()
            self._sweeping = True
            self._sweep_btn.SetValue(True)
            self._sweep_btn.SetLabel(_("Stop Sweep (Ctrl+F5)"))
            speech.output(_("Continuous sweep started."))

    def _on_sweep_finished(self) -> None:
        """Called from the audio thread when a sweep/snapshot stream ends."""
        wx.CallAfter(self._audio.duck, 1.0)

    # ==================================================================
    # Keyboard shortcuts
    # ==================================================================

    def _on_key(self, event: wx.KeyEvent) -> None:
        from ui import keyboard_handler as kb

        # Only handle shortcuts when the main window itself is active.
        if wx.GetActiveWindow() is not self:
            event.Skip()
            return

        focused = self.FindFocus()
        code = event.GetKeyCode()
        modifiers = event.GetModifiers()

        # Alt+F4 must be processed even when focus is in a text control.
        action = kb.lookup(code, modifiers)
        if action == kb.CLOSE_WINDOW:
            self.Close()
            return

        if isinstance(focused, wx.TextCtrl):
            event.Skip()
            return

        # Layered mode selection: M then mode letter
        if self._mode_pending:
            self._mode_pending = False
            char = chr(code).upper() if 32 <= code < 128 else ""
            if char in MODE_KEYS and modifiers == 0:
                self._set_mode(MODE_KEYS[char])
            else:
                speech.output(_("Modulation selection cancelled."))
            return

        if action is None:
            event.Skip()
            return

        # Dispatch table — maps action names to handler calls.
        self._dispatch_action(action)

    def _build_dispatch_table(self) -> dict[str, Callable]:
        """Build action-name → handler mapping (called once, cached)."""
        from ui import keyboard_handler as kb
        return {
            # Radio control
            kb.START_STOP:          lambda: self._on_start_stop(None),
            kb.TOGGLE_PAUSE:        self._toggle_pause,
            kb.TOGGLE_MUTE:         self._toggle_mute_action,
            kb.TOGGLE_RECORDING:    self._toggle_recording,
            # Frequency
            kb.ANNOUNCE_LO:         lambda: speech.output(_("LO {freq}").format(freq=fmt_freq(self._settings.frequency))),
            kb.ANNOUNCE_LISTEN:     lambda: speech.output(_("Listening {freq}").format(freq=fmt_freq(self._cursor.listening_freq()))),
            kb.CYCLE_STEP:          self._cycle_step,
            kb.FREQ_UP:             lambda: self._step_frequency(+1),
            kb.FREQ_DOWN:           lambda: self._step_frequency(-1),
            kb.FREQ_UP_FAST:        lambda: self._step_frequency(+10),
            kb.FREQ_DOWN_FAST:      lambda: self._step_frequency(-10),
            # Mode
            kb.MODE_SELECT_START:   self._start_mode_select,
            # Channel / scene navigation (VFO / MR)
            kb.PAGE_NAV_UP:         lambda: self._page_nav(+1),
            kb.PAGE_NAV_DOWN:       lambda: self._page_nav(-1),
            kb.TOGGLE_VFO_MR:       self._toggle_vfo_mr,
            kb.SCENE_PREV:          lambda: self._cycle_scene(-1),
            kb.SCENE_NEXT:          lambda: self._cycle_scene(+1),
            # Info
            kb.ANNOUNCE_INFO:       self._announce_info,
            # Volume / squelch
            kb.VOLUME_UP:           lambda: self._adjust_volume(+5),
            kb.VOLUME_DOWN:         lambda: self._adjust_volume(-5),
            kb.SQUELCH_UP:          lambda: self._adjust_squelch(+3),
            kb.SQUELCH_DOWN:        lambda: self._adjust_squelch(-3),
            # Sonification
            kb.SNAPSHOT:            self._do_snapshot,
            kb.TOGGLE_SWEEP:        self._toggle_sweep,
            # Spectrum
            kb.SPEAK_PEAKS:         lambda: self._spectrum_ctrl.speak_peaks(self._last_spectrum),
            kb.DESCRIBE_SPECTRUM:   lambda: self._spectrum_ctrl.describe_spectrum(sweeping=self._sweeping),
            # Cursor / VFO
            kb.CURSOR_LEFT:         lambda: self._cursor.step_cursor(-1),
            kb.CURSOR_RIGHT:        lambda: self._cursor.step_cursor(+1),
            kb.CURSOR_CTRL_LEFT:    lambda: None,  # handled by cursor timer
            kb.CURSOR_CTRL_RIGHT:   lambda: None,  # handled by cursor timer
            kb.RESET_CURSOR:        self._cursor.reset_cursor,
            kb.SPEAK_CURSOR:        lambda: self._cursor.speak_cursor(self._last_spectrum),
            kb.TUNE_TO_CURSOR:      self._cursor.tune_to_cursor,
            kb.TOGGLE_DEMOD_FOLLOWS: self._toggle_demod_follows,
            # Zoom
            kb.ZOOM_IN:             self._spectrum_ctrl.zoom_in,
            kb.ZOOM_OUT:            self._spectrum_ctrl.zoom_out,
            kb.ZOOM_RESET:          self._spectrum_ctrl.zoom_reset,
            # Dialogs
            kb.OPEN_FREQ_DIALOG:    self._open_freq_dialog,
            kb.OPEN_DEMOD_FREQ_DIALOG: self._open_demod_freq_dialog,
            kb.OPEN_RF_DIALOG:      self._open_rf_dialog,
            kb.OPEN_SPECTRUM_DIALOG: self._open_spectrum_dialog,
            kb.OPEN_SCANNER_DIALOG: self._open_scanner_dialog,
            kb.OPEN_CHANNELS_DIALOG: self._open_channels_dialog,
            kb.OPEN_SCENES_DIALOG:  self._open_scenes_dialog,
            kb.OPEN_AUDIO_DIALOG:   self._open_audio_dialog,
            kb.OPEN_WFM_DIALOG:     self._open_wfm_dialog,
            kb.OPEN_NFM_DIALOG:     self._open_nfm_dialog,
            kb.OPEN_RTL_TCP_DIALOG: self._open_rtl_tcp_dialog,
            kb.OPEN_RECORDING_DIALOG: self._open_recording_dialog,
            kb.OPEN_USER_GUIDE:     lambda: self._on_open_user_guide(None),
            kb.OPEN_HELP:           self._open_help_dialog,
        }

    def _dispatch_action(self, action: str) -> None:
        """Execute a keyboard action by name."""
        handler = self._action_table.get(action)
        if handler is not None:
            handler()

    def _toggle_mute_action(self) -> None:
        val = not self._mute_btn.GetValue()
        self._mute_btn.SetValue(val)
        self._audio.muted = val
        self._settings.muted = val
        speech.output(_("Muted") if val else _("Unmuted"))

    def _start_mode_select(self) -> None:
        self._mode_pending = True
        speech.output(_("Select modulation."))

    def _do_snapshot(self) -> None:
        if self._last_spectrum is not None:
            self._settings.sonification_enabled = True
            self._audio.duck(0.1)
            self._sonification.snapshot()
            speech.output(_("Sonification snapshot."))

    def _toggle_demod_follows(self) -> None:
        self._settings.demod_follows_cursor = not self._settings.demod_follows_cursor
        state = _("on") if self._settings.demod_follows_cursor else _("off")
        speech.output(_("Demod follows cursor {state}").format(state=state))
        if not self._settings.demod_follows_cursor:
            self._cursor.reset_offset()

    def _announce_info(self) -> None:
        """Speak current signal information (I key)."""
        if not self._radio.running:
            speech.output(_("Radio not running."))
            return
        parts = []
        db = self._audio.signal_db
        parts.append(_("Signal {db:.1f} dBFS, {s_unit}").format(
            db=db, s_unit=s_meter(db)
        ))
        pipeline = self._radio.pipeline
        demod = pipeline.demodulator if pipeline else None
        if self._settings.mode == "WFM" and demod is not None:
            stereo = getattr(demod, "stereo_detected", False)
            parts.append(_("Stereo") if stereo else _("Mono"))
            rds_name = getattr(demod, "rds_station", "")
            if rds_name:
                parts.append(_("RDS: {name}").format(name=rds_name))
            rds_pty = getattr(demod, "rds_program_type", "")
            if rds_pty:
                parts.append(rds_pty)
            rds_rt = getattr(demod, "rds_text", "")
            if rds_rt:
                parts.append(rds_rt)
        if self._settings.mode == "NFM" and demod is not None:
            ctcss = getattr(demod, "ctcss_tone", None)
            if ctcss is not None:
                parts.append(_("CTCSS {tone:.1f} Hz").format(tone=ctcss))
        squelch_open = db >= self._audio.squelch
        parts.append(
            _("Squelch open") if squelch_open else _("Squelch closed")
        )
        if self._audio.muted:
            parts.append(_("Muted"))
        if self._cursor.demod_offset != 0.0:
            parts.append(_("Offset {khz:+.1f} kHz").format(
                khz=self._cursor.demod_offset / 1000.0
            ))
            parts.append(_("Listening {freq}").format(
                freq=fmt_freq(self._cursor.listening_freq())
            ))
        speech.output(", ".join(parts))

    # ==================================================================
    # Recording
    # ==================================================================

    def _toggle_recording(self) -> None:
        """Toggle audio recording on/off (R key)."""
        if self._recording_path:
            self._stop_recording()
        else:
            self._start_recording()

    def _start_recording(self) -> None:
        fmt = self._settings.recording_format
        folder = self._settings.recording_path
        if not folder or not os.path.isdir(folder):
            folder = str(Path.home())
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(folder, f"accessdr_{ts}.{fmt}")
        mode = self._settings.mode
        result = self._audio.start_recording(path=path, fmt=fmt, mode=mode)
        if result:
            self._recording_path = result
            fname = os.path.basename(result)
            speech.output(
                _("Recording started: {filename}").format(filename=fname)
            )
            self._update_recording_status()
        else:
            speech.output(_("Could not start recording."))

    def _stop_recording(self) -> None:
        self._audio.stop_recording()
        if self._recording_path:
            fname = os.path.basename(self._recording_path)
            speech.output(
                _("Recording stopped: {filename}").format(filename=fname)
            )
            self._recording_path = ""
        self._update_recording_status()

    def _update_recording_status(self) -> None:
        """Update the status bar to show/hide [REC: filename]."""
        text = self._statusbar.GetStatusText()
        # Strip any existing REC tag
        if " [REC:" in text:
            text = text[: text.index(" [REC:")]
        if self._recording_path:
            fname = os.path.basename(self._recording_path)
            text += _(" [REC: {filename}]").format(filename=fname)
        self._statusbar.SetStatusText(text)

    # ==================================================================
    # Dialog openers
    # ==================================================================

    def _open_or_raise(self, key: str, factory) -> None:
        dlg = self._dialogs.get(key)
        try:
            already_shown = dlg is not None and dlg.IsShown()
        except RuntimeError:
            # Frame was destroyed (user closed it); create a fresh one
            already_shown = False
            dlg = None
        if not already_shown:
            dlg = factory()
            self._dialogs[key] = dlg
            dlg.Show()
        dlg.Raise()
        # Focus the panel inside the frame so Tab traversal works.
        # wx.CallAfter defers until after Show() has finished rendering.
        panel = next((c for c in dlg.GetChildren() if isinstance(c, wx.Panel)), None)
        wx.CallAfter((panel or dlg).SetFocus)

    def _open_rf_dialog(self) -> None:
        from ui.dialogs.rf_dialog import RFDialog
        old_active = self._settings.rtl_tcp_active
        valid_gains = self._radio.get_valid_gains() if self._radio.running else []
        dlg = RFDialog(self, self._settings, valid_gains=valid_gains)
        if dlg.ShowModal() == wx.ID_OK:
            backend_changed = self._settings.rtl_tcp_active != old_active
            if backend_changed and (self._radio.running or self._radio.paused):
                self._stop_radio()
                self._start_radio()
                self._update_backend_status()
            else:
                self._on_rf_settings_changed(self._settings)
                self._update_backend_status()
        dlg.Destroy()

    def _open_spectrum_dialog(self) -> None:
        from ui.dialogs.spectrum_dialog import SpectrumDialog
        dlg = SpectrumDialog(self, self._settings, self._sonification)
        if dlg.ShowModal() == wx.ID_OK:
            self._save_settings(self._settings)
            self._spectrum_panel.update_waterfall_settings(self._settings)
        dlg.Destroy()

    def _open_scanner_dialog(self) -> None:
        from ui.dialogs.scanner_dialog import ScannerDialog
        self._open_or_raise("scanner", lambda: ScannerDialog(self, self._scanner))

    def _open_channels_dialog(self) -> None:
        from ui.dialogs.channels_dialog import ChannelsDialog
        self._open_or_raise(
            "channels",
            lambda: ChannelsDialog(
                self, self._channels,
                on_load=self._on_channel_load,
                get_current=self._get_current_vfo,
                on_changed=self._on_channels_changed,
            ),
        )

    def _open_scenes_dialog(self) -> None:
        from ui.dialogs.scenes_dialog import ScenesDialog
        self._open_or_raise(
            "scenes",
            lambda: ScenesDialog(
                self, self._scenes,
                on_apply=self._on_scene_apply,
                get_current=self._get_current_vfo,
            ),
        )

    def _on_scene_apply(self, scene: Scene) -> None:
        """Apply a scene from the dialog: enter VFO mode and load the band."""
        self._opstate.mode = OpMode.VFO
        self._apply_scene(scene)

    def _get_current_vfo(self) -> tuple[int, str, int]:
        """Current (frequency, mode, bandwidth) for storing to a channel."""
        return (self._settings.frequency, self._settings.mode, self._settings.bandwidth)

    def _on_channels_changed(self) -> None:
        """Keep the operating state's channel map in sync after edits."""
        self._opstate.set_channel_map(self._channels.active_map())

    def _on_channel_load(self, ch: Channel) -> None:
        """Load a channel from the dialog: enter MR mode and tune to it."""
        cmap = self._channels.active_map()
        self._opstate.set_channel_map(cmap)
        self._opstate.mode = OpMode.MR
        if cmap is not None:
            for i, c in enumerate(cmap.sorted_channels()):
                if c.number == ch.number:
                    self._opstate.channel_index = i
                    break
        self._load_channel(ch)

    def _open_audio_dialog(self) -> None:
        from ui.dialogs.audio_dialog import AudioDialog
        dlg = AudioDialog(self, self._settings, self._audio)
        if dlg.ShowModal() == wx.ID_OK:
            self._on_audio_settings_changed(self._settings)
        dlg.Destroy()

    def _open_recording_dialog(self) -> None:
        from ui.dialogs.recording_dialog import RecordingDialog
        dlg = RecordingDialog(self, self._settings)
        dlg.ShowModal()
        dlg.Destroy()

    def _open_wfm_dialog(self) -> None:
        from ui.dialogs.wfm_dialog import WFMDialog
        dlg = WFMDialog(self, self._settings)
        if dlg.ShowModal() == wx.ID_OK:
            self._on_wfm_settings_changed()
        dlg.Destroy()

    def _open_nfm_dialog(self) -> None:
        from ui.dialogs.nfm_dialog import NFMDialog
        dlg = NFMDialog(self, self._settings)
        if dlg.ShowModal() == wx.ID_OK:
            self._on_nfm_settings_changed()
        dlg.Destroy()

    def _open_rtl_tcp_dialog(self) -> None:
        from ui.dialogs.rtl_tcp_dialog import RtlTcpDialog
        import copy
        old_active = self._settings.rtl_tcp_active
        old_srv = copy.deepcopy(self._settings.active_rtl_tcp_server())
        dlg = RtlTcpDialog(self, self._settings)
        dlg.ShowModal()
        dlg.Destroy()
        # Check if the active server was removed or modified
        new_srv = self._settings.active_rtl_tcp_server()
        if self._radio.running or self._radio.paused:
            if old_srv != new_srv or self._settings.rtl_tcp_active != old_active:
                self._stop_radio()
                self._start_radio()
        self._update_backend_status()

    def _update_backend_status(self) -> None:
        """Update status bar to reflect current backend mode."""
        srv = self._settings.active_rtl_tcp_server()
        if srv is not None:
            self._statusbar.SetStatusText(
                _("Remote: {name} ({host}:{port})").format(
                    name=srv.get("name", ""),
                    host=srv.get("host", ""),
                    port=srv.get("port", 1234),
                )
            )
        elif not self._radio.running:
            self._statusbar.SetStatusText(_("Ready — no device connected."))

    def _open_help_dialog(self) -> None:
        from ui.dialogs.help_dialog import HelpDialog
        self._open_or_raise("help", lambda: HelpDialog(self))

    def _on_open_user_guide(self, _event) -> None:
        import webbrowser
        from config.paths import help_dir
        path = os.path.join(help_dir(), "user-guide.html")
        if os.path.isfile(path):
            webbrowser.open(path)
        else:
            speech.output(_("User guide not found. Run 'invoke build-help' first."))

    def _on_open_help(self, _event) -> None:
        self._open_help_dialog()

    def _on_open_about(self, _event) -> None:
        self._open_about_dialog()

    def _open_about_dialog(self) -> None:
        from ui.dialogs.about_dialog import AboutDialog
        dlg = AboutDialog(self)
        dlg.ShowModal()
        dlg.Destroy()

    # ==================================================================
    # Callbacks
    # ==================================================================

    def _on_wfm_settings_changed(self) -> None:
        """Apply WFM settings changes — rebuild demodulator if in WFM mode."""
        self._radio.rebuild_wfm()

    def _on_nfm_settings_changed(self) -> None:
        """Apply NFM settings changes — rebuild demodulator if in NFM mode."""
        self._radio.rebuild_nfm()

    def _on_rf_settings_changed(self, settings: Settings) -> None:
        self._settings = settings
        self._noise_blanker.enabled = settings.noise_blanker_enabled
        self._noise_blanker.threshold = settings.noise_blanker_threshold
        if self._radio.apply_rf_settings():
            self._stop_radio()
            self._start_radio()

    def _on_audio_settings_changed(self, settings: Settings) -> None:
        self._settings = settings
        settings.save()
        self._audio.stop()
        self._audio.device = settings.audio_device
        self._audio.blocksize = settings.audio_buffer_size
        if self._radio.running or self._radio.paused:
            self._audio.start()
        self._sync_sonification_device()

    def _sync_sonification_device(self) -> None:
        """Ensure sonification uses the same output device as radio audio."""
        from core.audio import resolve_wasapi_device
        name = self._settings.audio_device
        if name:
            self._sonification.set_device(resolve_wasapi_device(name))
        else:
            self._sonification.set_device(None)

    def _save_settings(self, settings: Settings) -> None:
        self._settings = settings
        settings.save()

    def _on_sdr_error(self, msg: str) -> None:
        wx.CallAfter(speech.output, _("SDR error: {msg}").format(msg=msg))
        wx.CallAfter(
            self._statusbar.SetStatusText,
            _("Error: {msg}").format(msg=msg),
        )

    # ==================================================================
    # Shutdown
    # ==================================================================

    def _on_exit(self, _event) -> None:
        self.Close()

    def _on_close(self, event: wx.CloseEvent) -> None:
        self._cursor.stop()
        self._stop_recording()
        self._stop_radio()
        self._settings.op_mode = self._opstate.mode.value
        self._settings.active_scene = self._opstate.scene.name
        self._settings.active_channel = self._opstate.channel_index
        self._settings.save()
        self._scenes.save()
        self._channels.save()
        for dlg in self._dialogs.values():
            try:
                dlg.Destroy()
            except Exception:   # noqa: BLE001
                pass
        event.Skip()
