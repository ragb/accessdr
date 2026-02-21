"""
ui/main_window.py — AccessDR main application window.

Hosts the primary radio controls (frequency, mode, bandwidth, start/stop,
volume, squelch) and coordinates the SDR device, DSP thread, and audio
output.  All cross-thread communication is via queue.Queue + wx.CallAfter.
"""

from __future__ import annotations

import logging
import os
import queue
import threading
import time
from typing import Optional

import numpy as np
import wx

from accessibility import speech
from accessibility.sonification import Sonification
from config.bands import BAND_NAMES, centre_frequency, get_band
from ui.spectrum_panel import SpectrumPanel
from config.bookmarks import Bookmark, BookmarkStore
from config.settings import Settings
from core.audio import AudioOutput
from core.dsp.demodulator import make_demodulator, Demodulator
from core.dsp.filters import decimate
from core.dsp.mixer import Mixer
from core.dsp.noise_blanker import NoiseBlanker
from core.dsp.spectrum import SpectrumAnalyser
from core.scanner import Scanner
from core.sdr_device import SDRDevice

logger = logging.getLogger(__name__)

MODES = ["WFM", "NFM", "AM", "USB", "LSB", "CW", "DSB"]
MODE_KEYS = {"W": "WFM", "N": "NFM", "A": "AM", "U": "USB", "L": "LSB", "C": "CW", "D": "DSB"}
STEPS = [1, 10, 100, 1_000, 10_000, 100_000, 1_000_000]
STEP_LABELS = [
    N_("1 Hz"), N_("10 Hz"), N_("100 Hz"), N_("1 kHz"),
    N_("10 kHz"), N_("100 kHz"), N_("1 MHz"),
]
AUDIO_RATE = 48_000
BASEBAND_RATE = 240_000   # default; overridden per-session by _baseband_rate_for()


def _baseband_rate_for(sample_rate: int) -> int:
    """Pick a baseband rate with an exact integer decimation factor.

    Returns sample_rate / factor where factor yields a rate in 200–400 kHz
    that is closest to 240 kHz (the ideal baseband width for WFM).
    """
    best = None
    for factor in range(2, 21):
        if sample_rate % factor == 0:
            bb = sample_rate // factor
            if 200_000 <= bb <= 400_000:
                if best is None or abs(bb - 240_000) < abs(best - 240_000):
                    best = bb
    if best is not None:
        return best
    # Fallback: closest integer factor to 240 kHz target
    factor = max(1, round(sample_rate / 240_000))
    if sample_rate % factor == 0:
        return sample_rate // factor
    return sample_rate  # no decimation


# ---------------------------------------------------------------------------
# Process / thread priority (Windows) — reduces audio underruns
# ---------------------------------------------------------------------------

def _elevate_process_priority() -> None:
    """Set process priority to Above Normal on Windows."""
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        ABOVE_NORMAL_PRIORITY_CLASS = 0x00008000
        kernel32.SetPriorityClass(kernel32.GetCurrentProcess(),
                                  ABOVE_NORMAL_PRIORITY_CLASS)
    except Exception:  # noqa: BLE001
        pass


def _elevate_dsp_priority(thread: threading.Thread) -> None:
    """Raise the DSP thread to THREAD_PRIORITY_HIGHEST on Windows."""
    try:
        import ctypes
        import ctypes.wintypes as wt
        THREAD_SET_INFORMATION = 0x0020
        THREAD_PRIORITY_HIGHEST = 2
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.OpenThread(THREAD_SET_INFORMATION, False,
                                     thread.native_id)
        if handle:
            kernel32.SetThreadPriority(handle, THREAD_PRIORITY_HIGHEST)
            kernel32.CloseHandle(handle)
    except Exception:  # noqa: BLE001
        pass


_elevate_process_priority()

BW_OPTIONS = {
    "WFM":  [(200_000, "200 kHz"), (180_000, "180 kHz"), (150_000, "150 kHz")],
    "NFM":  [(12_500, "12.5 kHz"), (25_000, "25 kHz")],
    "AM":   [(6_000, "6 kHz"), (10_000, "10 kHz")],
    "USB":  [(2_700, "2.7 kHz"), (3_000, "3 kHz")],
    "LSB":  [(2_700, "2.7 kHz"), (3_000, "3 kHz")],
    "CW":   [(500, "500 Hz"), (250, "250 Hz"), (1_000, "1 kHz")],
    "DSB":  [(6_000, "6 kHz"), (10_000, "10 kHz")],
}


def _fmt_freq(hz: int) -> str:
    """Format Hz as MHz string with enough precision to show the last digit.

    Examples: 98.100 MHz, 98.1005 MHz, 98.10050 MHz, 98.100500 MHz.
    Always shows at least 3 decimal places (kHz resolution).
    """
    mhz = hz / 1_000_000
    if hz % 1000 == 0:
        return f"{mhz:.3f} MHz"
    if hz % 100 == 0:
        return f"{mhz:.4f} MHz"
    if hz % 10 == 0:
        return f"{mhz:.5f} MHz"
    return f"{mhz:.6f} MHz"


def _s_meter(db_fs: float) -> str:
    """Return S-unit string for an IQ power level (dBFS, approximate for RTL-SDR)."""
    if db_fs >= -5:
        return "S9+30"
    if db_fs >= -10:
        return "S9+20"
    if db_fs >= -15:
        return "S9+10"
    if db_fs >= -20:
        return "S9"
    if db_fs >= -26:
        return "S8"
    if db_fs >= -32:
        return "S7"
    if db_fs >= -38:
        return "S6"
    if db_fs >= -44:
        return "S5"
    if db_fs >= -50:
        return "S4"
    if db_fs >= -56:
        return "S3"
    if db_fs >= -62:
        return "S2"
    if db_fs >= -68:
        return "S1"
    return "S0"


class MainWindow(wx.Frame):
    """Primary application window."""

    def __init__(self, parent, title: str) -> None:
        super().__init__(parent, title=title, size=(640, 560))
        self.SetName("AccessDR Main Window")

        # Load persisted settings
        self._settings = Settings.load()

        # Core objects
        self._sdr = SDRDevice()
        self._sdr.on_error = self._on_sdr_error
        self._audio = AudioOutput(
            sample_rate=AUDIO_RATE,
            device=self._settings.audio_device,
            blocksize=self._settings.audio_buffer_size,
        )
        self._audio.volume = self._settings.volume
        self._audio.squelch = self._settings.squelch
        self._audio.muted = self._settings.muted
        self._spectrum = SpectrumAnalyser(fft_size=self._settings.fft_size)
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
        self._bookmarks = BookmarkStore()
        self._bookmarks.load()

        # Runtime state
        self._running = False
        self._paused = False
        self._dsp_thread: Optional[threading.Thread] = None
        self._step_idx = STEPS.index(self._settings.step) if self._settings.step in STEPS else 3
        self._was_stereo: Optional[bool] = None   # tracks last announced stereo state
        self._last_rds_station: str = ""          # tracks last announced RDS station name
        self._retune_pending: bool = False        # set by _tune(), cleared by DSP loop
        self._last_spectrum: Optional[np.ndarray] = None
        self._sweeping: bool = False               # continuous sweep running
        self._zoom_level: int = 0                  # 0–5: factor = 2^level
        self._mode_pending: bool = False           # waiting for mode letter after M
        self._above_threshold: bool = False        # auto-announce threshold state

        # Noise blanker — always created so B key works before radio starts
        self._noise_blanker = NoiseBlanker(self._settings.noise_blanker_threshold)
        self._noise_blanker.enabled = self._settings.noise_blanker_enabled

        # Software VFO offset state
        self._demod_offset: float = 0.0           # Hz from LO
        self._mixer: Optional[Mixer] = None       # created in _start_radio
        self._baseband_rate: int = BASEBAND_RATE   # overwritten in _start_radio

        # Spectrum cursor state
        self._cursor_pos: float = 0.5            # 0.0–1.0 within zoomed range
        self._cursor_active: bool = False         # probe tone playing
        self._ctrl_was_down: bool = False         # tracks Ctrl state transitions
        self._cursor_last_time: float = 0.0       # for delta-time movement
        self._cursor_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_cursor_timer, self._cursor_timer)
        self._cursor_timer.Start(50)              # always polling Ctrl state

        # Open dialogs cache (so we don't create duplicates)
        self._dialogs: dict = {}

        self._build_menu()
        self._build_ui()
        self._build_status_bar()

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
        bands_menu = wx.Menu()
        for name in BAND_NAMES:
            item = bands_menu.Append(wx.ID_ANY, _(name))
            self.Bind(wx.EVT_MENU, self._make_band_handler(name), item)
        radio_menu.AppendSubMenu(bands_menu, _("&Bands"))
        item_freq = radio_menu.Append(wx.ID_ANY, _("&Enter Frequency…\tCtrl+Q"))
        self.Bind(wx.EVT_MENU, self._on_enter_freq_menu, item_freq)
        mb.Append(radio_menu, _("&Radio"))

        # Tools
        tools_menu = wx.Menu()
        item_scanner = tools_menu.Append(wx.ID_ANY, _("Sca&nner…\tCtrl+N"))
        item_bookmarks = tools_menu.Append(wx.ID_ANY, _("&Bookmarks…\tCtrl+B"))
        self.Bind(wx.EVT_MENU, lambda e: self._open_scanner_dialog(), item_scanner)
        self.Bind(wx.EVT_MENU, lambda e: self._open_bookmarks_dialog(), item_bookmarks)
        mb.Append(tools_menu, _("&Tools"))

        # Options
        options_menu = wx.Menu()
        item_rf = options_menu.Append(wx.ID_ANY, _("&RF Settings…\tCtrl+R"))
        item_spectrum = options_menu.Append(wx.ID_ANY, _("&Spectrum Settings…\tCtrl+S"))
        item_audio = options_menu.Append(wx.ID_ANY, _("&Audio Settings…\tCtrl+D"))
        item_wfm = options_menu.Append(wx.ID_ANY, _("&WFM Settings…\tCtrl+W"))
        self.Bind(wx.EVT_MENU, lambda e: self._open_rf_dialog(), item_rf)
        self.Bind(wx.EVT_MENU, lambda e: self._open_spectrum_dialog(), item_spectrum)
        self.Bind(wx.EVT_MENU, lambda e: self._open_audio_dialog(), item_audio)
        self.Bind(wx.EVT_MENU, lambda e: self._open_wfm_dialog(), item_wfm)
        mb.Append(options_menu, _("&Options"))

        # Help
        help_menu = wx.Menu()
        item_guide = help_menu.Append(wx.ID_ANY, _("&User Guide…\tCtrl+H"))
        help_menu.Append(wx.ID_HELP, _("&Keyboard Shortcuts…\tF1"))
        self.Bind(wx.EVT_MENU, self._on_open_user_guide, item_guide)
        mb.Append(help_menu, _("&Help"))

        self.SetMenuBar(mb)

        # Bind standard IDs
        self.Bind(wx.EVT_MENU, self._on_exit, id=wx.ID_EXIT)
        self.Bind(wx.EVT_MENU, self._on_open_help, id=wx.ID_HELP)

    def _build_ui(self) -> None:
        panel = wx.Panel(self)
        panel.SetName("Main controls panel")
        outer = wx.BoxSizer(wx.VERTICAL)

        # --- Frequency row ---
        freq_row = wx.BoxSizer(wx.HORIZONTAL)
        freq_label = wx.StaticText(panel, label=_("Frequency:"))
        self._freq_ctrl = wx.TextCtrl(
            panel,
            value=_fmt_freq(self._settings.frequency),
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
        self._spectrum_panel.set_cursor_click_callback(self._on_spectrum_click)
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
        self._freq_ctrl.SetValue(_fmt_freq(self._settings.frequency))
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
        self._sdr.set_frequency(freq_hz)
        self._retune_pending = True   # ask DSP loop to re-announce stereo status
        listen = int(freq_hz + self._demod_offset)
        wx.CallAfter(self._freq_ctrl.SetValue, _fmt_freq(listen))
        wx.CallAfter(speech.output, _fmt_freq(listen))
        wx.CallAfter(
            self._statusbar.SetStatusText,
            _("Tuned to {freq}").format(freq=_fmt_freq(listen)),
        )
        wx.CallAfter(self._update_demod_marker)

    def _step_frequency(self, direction: int) -> None:
        step = STEPS[self._step_idx]
        new_freq = self._settings.frequency + direction * step
        new_freq = max(100_000, new_freq)
        self._tune(new_freq)

    def _on_enter_freq_menu(self, _event: wx.CommandEvent) -> None:
        self._open_freq_dialog()

    def _open_freq_dialog(self) -> None:
        """Open a modal dialog to enter a new frequency."""
        current = self._settings.frequency / 1_000_000
        dlg = wx.TextEntryDialog(
            self,
            _("Enter frequency (MHz):"),
            _("Tune to Frequency"),
            value=f"{current:.3f}",
        )
        if dlg.ShowModal() == wx.ID_OK:
            text = dlg.GetValue().strip().lower()
            try:
                text = text.replace("mhz", "").replace("khz", "").replace("hz", "").strip()
                val = float(text)
                if val < 30_000:
                    freq_hz = int(val * 1_000_000)    # assumed MHz
                elif val < 30_000_000:
                    freq_hz = int(val * 1_000)        # assumed kHz
                else:
                    freq_hz = int(val)
            except ValueError:
                speech.output(_("Invalid frequency."))
                dlg.Destroy()
                return
            self._reset_offset()
            self._tune(freq_hz)
        dlg.Destroy()

    def _open_demod_freq_dialog(self) -> None:
        """Open a modal dialog to set the demod (listening) frequency."""
        current = self._listening_freq() / 1_000_000
        dlg = wx.TextEntryDialog(
            self,
            _("Enter listening frequency (MHz):"),
            _("Set Listening Frequency"),
            value=f"{current:.3f}",
        )
        if dlg.ShowModal() == wx.ID_OK:
            text = dlg.GetValue().strip().lower()
            try:
                text = text.replace("mhz", "").replace("khz", "").replace("hz", "").strip()
                val = float(text)
                if val < 30_000:
                    freq_hz = int(val * 1_000_000)
                elif val < 30_000_000:
                    freq_hz = int(val * 1_000)
                else:
                    freq_hz = int(val)
            except ValueError:
                speech.output(_("Invalid frequency."))
                dlg.Destroy()
                return
            offset = freq_hz - self._settings.frequency
            self._set_demod_offset(offset)
            speech.output(_("Listening {freq}").format(freq=_fmt_freq(self._listening_freq())))
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
        self._was_stereo = None
        if self._running:
            self._sdr.set_tuner_bandwidth(self._hw_bandwidth_for_mode(mode))
        speech.output(_("Mode {mode}").format(mode=mode))

    @staticmethod
    def _hw_bandwidth_for_mode(mode: str) -> int:
        """Return suitable hardware IF bandwidth (Hz) for *mode*."""
        if mode == "WFM":
            return 300_000
        # NFM, AM, SSB, CW, DSB — minimum practical for R820T
        return 100_000

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
        self._was_stereo = None
        if self._running:
            self._sdr.set_tuner_bandwidth(self._hw_bandwidth_for_mode(mode))
        speech.output(_("Mode {mode}").format(mode=mode))

    # ==================================================================
    # Start / Stop
    # ==================================================================

    def _on_start_stop(self, _event: wx.CommandEvent) -> None:
        if self._paused:
            # Full stop from paused state
            self._paused = False
            self._stop_radio()
        elif self._running:
            self._stop_radio()
        else:
            self._start_radio()

    def _start_radio(self) -> None:
        if not self._sdr.open():
            speech.output(_("Could not open SDR device."))
            return
        # Compute baseband rate for the configured sample rate (must be integer factor)
        self._baseband_rate = _baseband_rate_for(self._settings.sample_rate)
        logger.info("Baseband rate %d Hz (decimate %dx from %d)",
                     self._baseband_rate,
                     self._settings.sample_rate // self._baseband_rate,
                     self._settings.sample_rate)
        # Create stateful demodulator — filters pre-computed, state preserved across chunks
        kwargs = self._wfm_kwargs() if self._settings.mode == "WFM" else {}
        self._demodulator: Demodulator = make_demodulator(
            self._settings.mode, self._baseband_rate, AUDIO_RATE, **kwargs
        )
        self._mixer = Mixer(self._settings.sample_rate)
        self._noise_blanker.threshold = self._settings.noise_blanker_threshold
        self._noise_blanker.enabled = self._settings.noise_blanker_enabled
        self._demod_offset = 0.0
        # Spectrum update throttle: ~20 Hz (chunk_rate / spec_every ≈ 20)
        from core.sdr_device import CHUNK_SIZE
        chunk_rate = self._settings.sample_rate / CHUNK_SIZE
        self._spec_every = max(1, int(round(chunk_rate / 20)))
        self._spec_skip = 0
        self._sdr.set_frequency(self._settings.frequency)
        self._sdr.set_sample_rate(self._settings.sample_rate)
        self._sdr.set_gain(self._settings.gain)
        self._sdr.set_ppm(self._settings.ppm)
        self._sdr.set_agc_mode(self._settings.agc_mode)
        self._sdr.set_offset_tuning(self._settings.offset_tuning)
        if self._settings.tuner_bandwidth != 0:
            self._sdr.set_tuner_bandwidth(self._settings.tuner_bandwidth)
        else:
            self._sdr.set_tuner_bandwidth(self._hw_bandwidth_for_mode(self._settings.mode))
        self._sdr.start()

        self._audio.start()

        self._running = True
        self._dsp_thread = threading.Thread(
            target=self._dsp_loop, daemon=True, name="DSPThread"
        )
        self._dsp_thread.start()
        _elevate_dsp_priority(self._dsp_thread)

        self._start_btn.SetLabel(_("\u25a0 Stop"))
        self._statusbar.SetStatusText(
            _("Receiving — {freq}").format(freq=_fmt_freq(self._listening_freq()))
        )
        speech.output(_("Radio started."))

    def _stop_radio(self) -> None:
        self._running = False
        self._paused = False
        self._sdr.stop()
        self._sdr.close()
        self._audio.stop()
        if self._dsp_thread:
            self._dsp_thread.join(timeout=2.0)
            self._dsp_thread = None
        self._was_stereo = None
        self._signal_lbl.SetLabel(_("Signal: —"))
        self._start_btn.SetLabel(_("\u25b6 Start"))
        self._statusbar.SetStatusText(_("Stopped."))
        speech.output(_("Radio stopped."))

    def _toggle_pause(self) -> None:
        """Toggle pause/resume. Pause freezes IQ capture and audio but keeps
        the last spectrum visible and navigable."""
        if not self._running and not self._paused:
            return  # can't pause a stopped radio

        if not self._paused:
            # --- Pause ---
            self._paused = True
            self._sdr.pause()                    # stop IQ capture (keeps device open)
            self._running = False                 # let DSP thread exit naturally
            if self._dsp_thread:
                self._dsp_thread.join(timeout=2.0)
                self._dsp_thread = None
            self._audio.pause()                   # stop audio stream, drain queue
            listen = self._listening_freq()
            self._start_btn.SetLabel(_("▶ Resume"))
            self._statusbar.SetStatusText(
                _("Paused — {freq}").format(freq=_fmt_freq(listen))
            )
            speech.output(_("Paused."))
        else:
            # --- Resume ---
            # Drain stale IQ data
            while not self._sdr.iq_queue.empty():
                try:
                    self._sdr.iq_queue.get_nowait()
                except queue.Empty:
                    break
            self._sdr.start()                     # restart IQ capture
            self._audio.resume()                  # restart audio stream
            self._running = True
            self._dsp_thread = threading.Thread(
                target=self._dsp_loop, daemon=True, name="DSPThread"
            )
            self._dsp_thread.start()
            _elevate_dsp_priority(self._dsp_thread)
            self._paused = False
            listen = self._listening_freq()
            self._start_btn.SetLabel(_("■ Stop"))
            self._statusbar.SetStatusText(
                _("Receiving — {freq}").format(freq=_fmt_freq(listen))
            )
            speech.output(_("Resumed."))

    # ==================================================================
    # DSP thread
    # ==================================================================

    def _dsp_loop(self) -> None:
        """Main DSP thread: demodulate IQ and feed audio + spectrum."""
        current_mode = self._settings.mode
        dsp_stereo: Optional[bool] = None   # tracks last announced stereo state (DSP thread)
        stereo_delay: int = 0               # chunks to wait before announcing after retune

        while self._running:
            try:
                iq = self._sdr.iq_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            # Rebuild demodulator if mode changed (new filter state required)
            if self._settings.mode != current_mode:
                current_mode = self._settings.mode
                kwargs = self._wfm_kwargs() if current_mode == "WFM" else {}
                self._demodulator = make_demodulator(current_mode, self._baseband_rate, AUDIO_RATE, **kwargs)
                dsp_stereo = None
                stereo_delay = 0

            # Re-announce stereo status after a retune, but delay so the
            # frequency speech finishes before the stereo announcement fires.
            if self._retune_pending:
                self._retune_pending = False
                dsp_stereo = None
                stereo_delay = 6   # ~6 chunks ≈ 300–400 ms at typical chunk sizes
                self._last_rds_station = ""
                # Reset RDS decoder state on retune
                rds_reset = getattr(self._demodulator, "_rds", None)
                if rds_reset is not None:
                    rds_reset.reset()

            # Remove RTL-SDR DC offset spike (constant hardware bias at centre freq)
            iq = iq - np.mean(iq)

            # Noise blanker — suppress impulse noise before any further processing
            iq = self._noise_blanker.process(iq)

            # RF signal power from raw IQ (dBFS, 0 = full scale).
            # np.vdot(iq,iq) = Σ|iq[i]|² in one BLAS call — no complex128/abs.
            iq_power = float(np.vdot(iq, iq).real) / len(iq)
            self._audio.signal_db = 10.0 * np.log10(max(iq_power, 1e-10))

            # Spectrum analysis — throttle to ~20 Hz to save CPU
            self._spec_skip = getattr(self, "_spec_skip", 0) + 1
            if self._spec_skip >= self._spec_every:
                self._spec_skip = 0
                spec = self._spectrum.process(iq)
                wx.CallAfter(self._on_spectrum_update, spec)

            # Shift desired signal to DC via software VFO offset (full 2.4 MHz range)
            mixed = self._mixer.process(iq, self._demod_offset)

            # Decimate to baseband — anti-aliasing filter acts as channel filter
            bb = decimate(mixed, self._settings.sample_rate, self._baseband_rate)

            # Demodulate using stateful demodulator (filter state carried between chunks)
            audio = self._demodulator.process(bb)
            self._audio.write(audio)

            # Track stereo/mono state; update status bar silently on change.
            # The I key report includes stereo/mono so we don't speak it here.
            if current_mode == "WFM":
                stereo = getattr(self._demodulator, "stereo_detected", False)
                if stereo_delay > 0:
                    stereo_delay -= 1
                    dsp_stereo = stereo
                elif stereo != dsp_stereo:
                    dsp_stereo = stereo
                    label = _("Stereo") if stereo else _("Mono")
                    listen = int(self._settings.frequency + self._demod_offset)
                    wx.CallAfter(
                        self._statusbar.SetStatusText,
                        _("Receiving — {freq} [{label}]").format(
                            freq=_fmt_freq(listen), label=label
                        ),
                    )

                # RDS auto-announce: speak station name on change
                rds_name = getattr(self._demodulator, "rds_station", "")
                if rds_name and rds_name != self._last_rds_station:
                    self._last_rds_station = rds_name
                    wx.CallAfter(speech.output, _("RDS: {name}").format(name=rds_name))

    def _on_spectrum_update(self, spectrum: np.ndarray) -> None:
        """Called on UI thread with updated spectrum data."""
        self._last_spectrum = spectrum

        # Update signal strength display
        strength = self._audio.signal_db
        s_unit = _s_meter(strength)
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
            self._sonification.set_spectrum(self._zoom_slice(spectrum))

        # Update probe tone with latest spectrum data
        if self._cursor_active:
            self._sonification.update_probe(self._cursor_pos)

        # Update spectrum panel accessible name with current range
        start_hz, end_hz = self._spectrum_range()
        self._spectrum_panel.SetName(
            _("Spectrum {start} to {end} MHz").format(
                start=f"{start_hz / 1_000_000:.3f}",
                end=f"{end_hz / 1_000_000:.3f}",
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
    # Spectrum zoom
    # ==================================================================

    def _zoom_slice(self, spectrum: np.ndarray) -> np.ndarray:
        """Return the centre portion of *spectrum* according to zoom level."""
        if self._zoom_level == 0:
            return spectrum
        factor = 2 ** self._zoom_level
        n = len(spectrum)
        mid = n // 2
        half = n // (2 * factor)
        return spectrum[mid - half : mid + half]

    def _spectrum_range(self) -> tuple[float, float]:
        """Return (start_hz, end_hz) of the current zoomed view."""
        half_span = self._settings.sample_rate / (2 * 2 ** self._zoom_level)
        centre = self._settings.frequency
        return (centre - half_span, centre + half_span)

    def _zoom_in(self) -> None:
        if self._zoom_level >= 5:
            speech.output(_("Already at maximum zoom."))
            return
        self._zoom_level += 1
        self._announce_zoom()
        self._spectrum_panel.set_zoom(self._zoom_level)

    def _zoom_out(self) -> None:
        if self._zoom_level <= 0:
            speech.output(_("Already at full spectrum."))
            return
        self._zoom_level -= 1
        self._announce_zoom()
        self._spectrum_panel.set_zoom(self._zoom_level)

    def _zoom_reset(self) -> None:
        if self._zoom_level == 0:
            speech.output(_("Already at full spectrum."))
            return
        self._zoom_level = 0
        self._announce_zoom()
        self._spectrum_panel.set_zoom(self._zoom_level)

    def _announce_zoom(self) -> None:
        start_hz, end_hz = self._spectrum_range()
        start_mhz = start_hz / 1_000_000
        end_mhz = end_hz / 1_000_000
        if self._zoom_level == 0:
            msg = _("Full spectrum, {start} to {end} MHz").format(
                start=f"{start_mhz:.3f}", end=f"{end_mhz:.3f}"
            )
        else:
            factor = 2 ** self._zoom_level
            msg = _("Zoom {level}x, {start} to {end} MHz").format(
                level=factor, start=f"{start_mhz:.3f}", end=f"{end_mhz:.3f}"
            )
        speech.output(msg)

    def _describe_spectrum(self) -> None:
        start_hz, end_hz = self._spectrum_range()
        start_mhz = start_hz / 1_000_000
        end_mhz = end_hz / 1_000_000
        if self._zoom_level == 0:
            msg = _("Full spectrum, {start} to {end} MHz").format(
                start=f"{start_mhz:.3f}", end=f"{end_mhz:.3f}"
            )
        else:
            factor = 2 ** self._zoom_level
            msg = _("Zoom {level}x, {start} to {end} MHz").format(
                level=factor, start=f"{start_mhz:.3f}", end=f"{end_mhz:.3f}"
            )
        if self._sweeping:
            msg += _(", sweep active")
        speech.output(msg)

    # ==================================================================
    # Spectrum cursor
    # ==================================================================

    def _cursor_freq(self) -> int:
        """Convert cursor position (0.0–1.0) to Hz within zoomed range."""
        start_hz, end_hz = self._spectrum_range()
        span = end_hz - start_hz
        return int(start_hz + self._cursor_pos * span)

    def _cursor_db(self) -> float:
        """Interpolate spectrum power at the cursor position (dBFS)."""
        if self._last_spectrum is None:
            return -100.0
        zoomed = self._zoom_slice(self._last_spectrum)
        n = len(zoomed)
        if n < 2:
            return -100.0
        bin_f = self._cursor_pos * (n - 1)
        lo = int(bin_f)
        hi = min(lo + 1, n - 1)
        frac = bin_f - lo
        return float(zoomed[lo] * (1.0 - frac) + zoomed[hi] * frac)

    def _start_cursor_probe(self) -> None:
        """Start the cursor probe tone at the current position."""
        if self._cursor_active:
            return
        self._cursor_active = True
        self._cursor_last_time = time.monotonic()
        self._settings.sonification_enabled = True
        self._audio.duck(0.1)  # fade radio down while probing
        self._sonification.start_probe(self._cursor_pos)

    def _stop_cursor_probe(self) -> None:
        """Stop the cursor probe tone."""
        if not self._cursor_active:
            return
        self._cursor_active = False
        self._sonification.stop_probe()
        self._audio.duck(1.0)  # fade radio back up

    def _on_cursor_timer(self, _event: wx.TimerEvent) -> None:
        """50 ms tick: poll Ctrl for probe start/stop, poll arrows for movement."""
        # Only track when main window is active
        if wx.GetActiveWindow() is not self:
            if self._cursor_active:
                self._stop_cursor_probe()
            self._ctrl_was_down = False
            return

        ctrl_down = wx.GetKeyState(wx.WXK_CONTROL)

        # Ctrl transition: pressed → start probe, released → stop probe
        if ctrl_down and not self._ctrl_was_down:
            self._start_cursor_probe()
        elif not ctrl_down and self._ctrl_was_down:
            self._stop_cursor_probe()
        self._ctrl_was_down = ctrl_down

        if not self._cursor_active:
            return

        # Poll arrow keys for direction while probe is active
        left = wx.GetKeyState(wx.WXK_LEFT)
        right = wx.GetKeyState(wx.WXK_RIGHT)
        direction = (-1 if left else 0) + (1 if right else 0)

        now = time.monotonic()
        dt = now - self._cursor_last_time
        self._cursor_last_time = now

        if direction != 0:
            speed = self._settings.cursor_speed
            self._cursor_pos += direction * speed * dt
            self._cursor_pos = max(0.0, min(1.0, self._cursor_pos))

        self._sonification.update_probe(self._cursor_pos)
        self._spectrum_panel.set_cursor(self._cursor_pos)
        if self._settings.demod_follows_cursor:
            self._update_offset_from_cursor()

    def _step_cursor(self, direction: int) -> None:
        """Move the cursor by one discrete step and announce position."""
        step = self._settings.cursor_speed * 0.1
        self._cursor_pos += direction * step
        self._cursor_pos = max(0.0, min(1.0, self._cursor_pos))
        self._spectrum_panel.set_cursor(self._cursor_pos)
        if self._settings.demod_follows_cursor:
            self._update_offset_from_cursor()
        self._speak_cursor()

    def _speak_cursor(self) -> None:
        """Speak the cursor's current frequency and power."""
        freq_hz = self._cursor_freq()
        db = self._cursor_db()
        s_unit = _s_meter(db)
        speech.output(
            _("{freq}, {db:.0f} dBFS, {s_unit}").format(
                freq=_fmt_freq(freq_hz), db=db, s_unit=s_unit,
            )
        )

    def _reset_cursor(self) -> None:
        """Reset the spectrum cursor to the centre and clear demod offset."""
        self._cursor_pos = 0.5
        self._spectrum_panel.set_cursor(self._cursor_pos)
        self._reset_offset()
        speech.output(_("Cursor centred, offset cleared."))

    def _tune_to_cursor(self) -> None:
        """Tune the LO to the cursor frequency and reset offset."""
        freq_hz = self._cursor_freq()
        self._reset_offset()
        self._cursor_pos = 0.5
        self._spectrum_panel.set_cursor(self._cursor_pos)
        self._tune(freq_hz)

    def _on_spectrum_click(self, pos: float) -> None:
        """Handle mouse click on spectrum panel — move cursor to position."""
        self._cursor_pos = pos
        self._spectrum_panel.set_cursor(pos)
        if self._settings.demod_follows_cursor:
            self._update_offset_from_cursor()

    # ==================================================================
    # Software VFO offset
    # ==================================================================

    def _listening_freq(self) -> int:
        """Return the actual listening frequency (LO + demod offset)."""
        return int(self._settings.frequency + self._demod_offset)

    def _set_demod_offset(self, hz: float) -> None:
        """Set the demod offset, clamping to ±half capture bandwidth."""
        max_offset = self._settings.sample_rate / 2.0   # ±1.2 MHz
        self._demod_offset = max(-max_offset, min(max_offset, hz))
        self._update_demod_marker()
        listen = self._listening_freq()
        self._freq_ctrl.SetValue(_fmt_freq(listen))

    def _reset_offset(self) -> None:
        """Zero the demod offset and reset mixer phase."""
        self._demod_offset = 0.0
        if self._mixer is not None:
            self._mixer.reset()
        self._update_demod_marker()
        self._freq_ctrl.SetValue(_fmt_freq(self._settings.frequency))

    def _update_offset_from_cursor(self) -> None:
        """Convert cursor position to demod offset Hz (clamped to baseband)."""
        start_hz, end_hz = self._spectrum_range()
        span = end_hz - start_hz
        cursor_hz = start_hz + self._cursor_pos * span
        offset = cursor_hz - self._settings.frequency
        self._set_demod_offset(offset)

    def _update_demod_marker(self) -> None:
        """Sync the spectrum panel demod marker to the current offset."""
        if self._demod_offset == 0.0:
            self._spectrum_panel.set_demod_marker(None)
        else:
            # Convert offset Hz to 0.0–1.0 position within zoomed spectrum range
            start_hz, end_hz = self._spectrum_range()
            span = end_hz - start_hz
            if span > 0:
                pos = (self._settings.frequency + self._demod_offset - start_hz) / span
                pos = max(0.0, min(1.0, pos))
                self._spectrum_panel.set_demod_marker(pos)
            else:
                self._spectrum_panel.set_demod_marker(None)

    # ==================================================================
    # Keyboard shortcuts
    # ==================================================================

    def _on_key(self, event: wx.KeyEvent) -> None:
        # Only handle shortcuts when the main window itself is active.
        # EVT_CHAR_HOOK bubbles up from child frames (dialogs), so without
        # this guard arrow keys and mode keys would fire inside dialogs too.
        if wx.GetActiveWindow() is not self:
            event.Skip()
            return

        focused = self.FindFocus()
        in_text = isinstance(focused, wx.TextCtrl)
        code = event.GetKeyCode()
        modifiers = event.GetModifiers()

        if in_text:
            event.Skip()
            return

        char = chr(code) if 32 <= code < 128 else ""

        # Layered mode selection: M then mode letter
        if self._mode_pending:
            self._mode_pending = False
            if char.upper() in MODE_KEYS and modifiers == 0:
                self._set_mode(MODE_KEYS[char.upper()])
            else:
                speech.output(_("Modulation selection cancelled."))
            return

        if code == ord("M") and modifiers == 0:
            self._mode_pending = True
            speech.output(_("Select modulation."))
            return

        if code == ord("Q") and modifiers == 0:
            speech.output(_("LO {freq}").format(freq=_fmt_freq(self._settings.frequency)))
            return

        if code == ord("O") and modifiers == 0:
            speech.output(_("Listening {freq}").format(freq=_fmt_freq(self._listening_freq())))
            return

        if code == ord("S") and modifiers == 0:
            self._cycle_step()
            return

        if code == wx.WXK_F2 and modifiers == 0:
            self._on_start_stop(event)
            return

        if code == wx.WXK_SPACE and modifiers in (0, wx.MOD_CONTROL):
            self._toggle_pause()
            return

        if code == wx.WXK_F3 and modifiers == 0:
            val = not self._mute_btn.GetValue()
            self._mute_btn.SetValue(val)
            self._audio.muted = val
            self._settings.muted = val
            speech.output(_("Muted") if val else _("Unmuted"))
            return

        if code == ord("I") and modifiers == 0:
            if not self._running:
                speech.output(_("Radio not running."))
            else:
                parts = []
                db = self._audio.signal_db
                parts.append(_("Signal {db:.1f} dBFS, {s_unit}").format(
                    db=db, s_unit=_s_meter(db)
                ))
                if self._settings.mode == "WFM" and self._demodulator is not None:
                    stereo = getattr(self._demodulator, "stereo_detected", False)
                    parts.append(_("Stereo") if stereo else _("Mono"))
                    rds_name = getattr(self._demodulator, "rds_station", "")
                    if rds_name:
                        parts.append(_("RDS: {name}").format(name=rds_name))
                if self._settings.mode == "NFM" and self._demodulator is not None:
                    ctcss = getattr(self._demodulator, "ctcss_tone", None)
                    if ctcss is not None:
                        parts.append(_("CTCSS {tone:.1f} Hz").format(tone=ctcss))
                squelch_open = db >= self._audio.squelch
                parts.append(
                    _("Squelch open") if squelch_open else _("Squelch closed")
                )
                if self._audio.muted:
                    parts.append(_("Muted"))
                if self._demod_offset != 0.0:
                    parts.append(_("Offset {khz:+.1f} kHz").format(
                        khz=self._demod_offset / 1000.0
                    ))
                    parts.append(_("Listening {freq}").format(
                        freq=_fmt_freq(self._listening_freq())
                    ))
                speech.output(", ".join(parts))
            return

        if code == wx.WXK_F5 and modifiers == 0:
            if self._last_spectrum is not None:
                self._settings.sonification_enabled = True
                self._audio.duck(0.1)
                self._sonification.snapshot()
                speech.output(_("Sonification snapshot."))
            return

        if code == wx.WXK_F5 and modifiers == wx.MOD_CONTROL:
            self._toggle_sweep()
            return

        if code == ord("F") and modifiers == 0:
            self._speak_peaks()
            return

        if code == ord("G") and modifiers == 0:
            self._describe_spectrum()
            return

        if code == ord("C") and modifiers == wx.MOD_SHIFT:
            self._settings.demod_follows_cursor = not self._settings.demod_follows_cursor
            state = _("on") if self._settings.demod_follows_cursor else _("off")
            speech.output(_("Demod follows cursor {state}").format(state=state))
            if not self._settings.demod_follows_cursor:
                self._reset_offset()
            return

        if code == ord("C") and modifiers == 0:
            self._reset_cursor()
            return

        if code == ord("T") and modifiers == 0:
            self._speak_cursor()
            return

        if code == ord("T") and modifiers == wx.MOD_CONTROL:
            self._tune_to_cursor()
            return

        # Volume: PageUp / PageDown (±5%)
        if code == wx.WXK_PAGEUP and modifiers == 0:
            self._adjust_volume(+5)
            return
        if code == wx.WXK_PAGEDOWN and modifiers == 0:
            self._adjust_volume(-5)
            return

        # Squelch: Shift+PageUp / Shift+PageDown (±3 dB)
        if code == wx.WXK_PAGEUP and modifiers == wx.MOD_SHIFT:
            self._adjust_squelch(+3)
            return
        if code == wx.WXK_PAGEDOWN and modifiers == wx.MOD_SHIFT:
            self._adjust_squelch(-3)
            return

        # Zoom: = / + / numpad+ to zoom in, - / numpad- to zoom out
        if code in (ord("="), ord("+"), wx.WXK_NUMPAD_ADD) and modifiers == 0:
            self._zoom_in()
            return
        if code in (ord("-"), wx.WXK_NUMPAD_SUBTRACT) and modifiers == 0:
            self._zoom_out()
            return
        if code == wx.WXK_BACK and modifiers == 0:
            self._zoom_reset()
            return

        if code == wx.WXK_UP and modifiers == 0:
            self._step_frequency(+1)
            return

        if code == wx.WXK_DOWN and modifiers == 0:
            self._step_frequency(-1)
            return

        if code == wx.WXK_UP and modifiers == wx.MOD_SHIFT:
            self._step_frequency(+10)
            return

        if code == wx.WXK_DOWN and modifiers == wx.MOD_SHIFT:
            self._step_frequency(-10)
            return

        if code == wx.WXK_LEFT and modifiers == wx.MOD_CONTROL:
            return  # movement handled by cursor timer polling

        if code == wx.WXK_RIGHT and modifiers == wx.MOD_CONTROL:
            return  # movement handled by cursor timer polling

        if code == wx.WXK_LEFT and modifiers == 0:
            self._step_cursor(-1)
            return

        if code == wx.WXK_RIGHT and modifiers == 0:
            self._step_cursor(+1)
            return

        if code == wx.WXK_F1:
            self._open_help_dialog()
            return

        # Frequency entry shortcuts (Ctrl+letter)
        if modifiers == wx.MOD_CONTROL:
            if code == ord("Q"):
                self._open_freq_dialog()
                return
            if code == ord("O"):
                self._open_demod_freq_dialog()
                return

        # Dialog shortcuts (Ctrl+letter)
        if modifiers == wx.MOD_CONTROL:
            if code == ord("R"):
                self._open_rf_dialog()
                return
            if code == ord("S"):
                self._open_spectrum_dialog()
                return
            if code == ord("N"):
                self._open_scanner_dialog()
                return
            if code == ord("B"):
                self._open_bookmarks_dialog()
                return
            if code == ord("D"):
                self._open_audio_dialog()
                return
            if code == ord("W"):
                self._open_wfm_dialog()
                return
            if code == ord("H"):
                self._on_open_user_guide(None)
                return

        event.Skip()

    def _speak_peaks(self) -> None:
        """Speak top N spectrum peaks (F key), respecting zoom."""
        if self._last_spectrum is None:
            speech.output(_("No spectrum data yet."))
            return
        zoomed = self._zoom_slice(self._last_spectrum)
        factor = 2 ** self._zoom_level
        peaks = SpectrumAnalyser.find_peaks(
            zoomed,
            centre_hz=self._settings.frequency,
            sample_rate=self._settings.sample_rate // factor,
            n_peaks=self._settings.speech_peak_count,
        )
        if not peaks:
            speech.output(_("No peaks detected."))
            return
        parts = [f"{f / 1e6:.3f} MHz {db:.0f} dBm" for f, db in peaks]
        speech.output(_("Peaks: ") + ", ".join(parts))

    # ==================================================================
    # Band jump
    # ==================================================================

    def _make_band_handler(self, name: str):
        def handler(_event):
            lo, hi, mode = get_band(name)
            freq = centre_frequency(name)
            self._tune(freq)
            self._set_mode(mode)
            speech.output(
                _("Band: {name}, {freq}, mode {mode}").format(
                    name=_(name), freq=_fmt_freq(freq), mode=mode
                )
            )
        return handler

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
        valid_gains = self._sdr.get_valid_gains() if self._running else []
        dlg = RFDialog(self, self._settings, valid_gains=valid_gains)
        if dlg.ShowModal() == wx.ID_OK:
            self._on_rf_settings_changed(self._settings)
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

    def _open_bookmarks_dialog(self) -> None:
        from ui.dialogs.bookmarks_dialog import BookmarksDialog
        self._open_or_raise(
            "bookmarks",
            lambda: BookmarksDialog(self, self._bookmarks, on_load=self._on_bookmark_load),
        )

    def _open_audio_dialog(self) -> None:
        from ui.dialogs.audio_dialog import AudioDialog
        dlg = AudioDialog(self, self._settings, self._audio)
        if dlg.ShowModal() == wx.ID_OK:
            self._on_audio_settings_changed(self._settings)
        dlg.Destroy()

    def _open_wfm_dialog(self) -> None:
        from ui.dialogs.wfm_dialog import WFMDialog
        dlg = WFMDialog(self, self._settings)
        if dlg.ShowModal() == wx.ID_OK:
            self._on_wfm_settings_changed()
        dlg.Destroy()

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

    # ==================================================================
    # Callbacks
    # ==================================================================

    def _on_bookmark_load(self, bm: Bookmark) -> None:
        self._tune(bm.frequency)
        self._set_mode(bm.mode)

    def _wfm_kwargs(self) -> dict:
        """Build kwargs dict for WFMDemodulator from current settings."""
        return dict(
            deemphasis=self._settings.wfm_deemphasis,
            stereo_mode=self._settings.wfm_stereo_mode,
            hiblend_enabled=self._settings.wfm_hiblend_enabled,
            rds_enabled=self._settings.wfm_rds_enabled,
        )

    def _on_wfm_settings_changed(self) -> None:
        """Apply WFM settings changes — rebuild demodulator if in WFM mode."""
        if self._running and self._settings.mode == "WFM":
            self._demodulator = make_demodulator(
                "WFM", self._baseband_rate, AUDIO_RATE, **self._wfm_kwargs()
            )

    def _on_rf_settings_changed(self, settings: Settings) -> None:
        self._settings = settings
        # Sync noise blanker state
        nb = getattr(self, "_noise_blanker", None)
        if nb is not None:
            nb.enabled = settings.noise_blanker_enabled
            nb.threshold = settings.noise_blanker_threshold
        if self._running:
            self._sdr.set_gain(settings.gain)
            self._sdr.set_ppm(settings.ppm)
            self._sdr.set_sample_rate(settings.sample_rate)
            self._sdr.set_agc_mode(settings.agc_mode)
            self._sdr.set_offset_tuning(settings.offset_tuning)
            self._sdr.set_tuner_bandwidth(settings.tuner_bandwidth)

    def _on_audio_settings_changed(self, settings: Settings) -> None:
        self._settings = settings
        settings.save()
        # Restart audio stream with new device / buffer size
        from core.audio import _resolve_wasapi_device
        self._audio.stop()
        self._audio.device = settings.audio_device
        self._audio.blocksize = settings.audio_buffer_size
        if self._running or self._paused:
            self._audio.start()
        self._sync_sonification_device()

    def _sync_sonification_device(self) -> None:
        """Ensure sonification uses the same output device as radio audio."""
        from core.audio import _resolve_wasapi_device
        name = self._settings.audio_device
        if name:
            self._sonification.set_device(_resolve_wasapi_device(name))
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
        self._cursor_timer.Stop()
        self._stop_cursor_probe()
        self._stop_radio()
        self._settings.save()
        self._bookmarks.save()
        for dlg in self._dialogs.values():
            try:
                dlg.Destroy()
            except Exception:   # noqa: BLE001
                pass
        event.Skip()
