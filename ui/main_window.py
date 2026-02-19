"""
ui/main_window.py — AccessDR main application window.

Hosts the primary radio controls (frequency, mode, bandwidth, start/stop,
volume, squelch) and coordinates the SDR device, DSP thread, and audio
output.  All cross-thread communication is via queue.Queue + wx.CallAfter.
"""

from __future__ import annotations

import logging
import queue
import threading
from typing import Optional

import numpy as np
import wx

from accessibility import speech
from accessibility.sonification import Sonification
from config.bands import BAND_NAMES, centre_frequency, get_band
from config.bookmarks import Bookmark, BookmarkStore
from config.settings import Settings
from core.audio import AudioOutput
from core.dsp.demodulator import make_demodulator, Demodulator
from core.dsp.filters import decimate
from core.dsp.spectrum import SpectrumAnalyser
from core.scanner import Scanner
from core.sdr_device import SDRDevice

logger = logging.getLogger(__name__)

MODES = ["WFM", "NFM", "AM", "USB", "LSB", "CW", "DSB"]
MODE_KEYS = {"W": "WFM", "N": "NFM", "A": "AM", "U": "USB", "L": "LSB", "C": "CW", "D": "DSB"}
STEPS = [1, 10, 100, 1_000, 10_000, 100_000, 1_000_000]
STEP_LABELS = ["1 Hz", "10 Hz", "100 Hz", "1 kHz", "10 kHz", "100 kHz", "1 MHz"]
AUDIO_RATE = 48_000
BASEBAND_RATE = 240_000   # decimate 2.4 MSPS → 240 kSPS → demodulate → 48 kHz

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
    """Format Hz as MHz string with 3 decimal places, e.g. '98.100 MHz'."""
    mhz = hz / 1_000_000
    return f"{mhz:.3f} MHz"


def _signal_quality(db: float) -> str:
    """Return a one-word quality label for an IQ power level (dBFS).

    RTL-SDR IQ samples are normalised to ±1.  Typical receive levels:
      ≥ −10 dBFS : very strong (risk of clipping)
      −10 to −20 : excellent
      −20 to −35 : good
      −35 to −50 : fair
      −50 to −65 : weak
      < −65 dBFS : noise floor / no signal
    """
    if db >= -10:
        return "Excellent"
    if db >= -20:
        return "Excellent"
    if db >= -35:
        return "Good"
    if db >= -50:
        return "Fair"
    if db >= -65:
        return "Weak"
    return "None"


class MainWindow(wx.Frame):
    """Primary application window."""

    def __init__(self, parent, title: str) -> None:
        super().__init__(parent, title=title, size=(520, 320))
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
        )
        self._scanner = Scanner(
            set_frequency_cb=self._tune,
            get_signal_db_cb=lambda: self._audio.signal_db,
            dispatcher=wx.CallAfter,
        )
        self._bookmarks = BookmarkStore()
        self._bookmarks.load()

        # Runtime state
        self._running = False
        self._dsp_thread: Optional[threading.Thread] = None
        self._step_idx = STEPS.index(self._settings.step) if self._settings.step in STEPS else 3
        self._was_stereo: Optional[bool] = None   # tracks last announced stereo state
        self._retune_pending: bool = False        # set by _tune(), cleared by DSP loop
        self._last_spectrum: Optional[np.ndarray] = None

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
        file_menu.Append(wx.ID_EXIT, "E&xit\tAlt+F4")
        mb.Append(file_menu, "&File")

        # Radio
        radio_menu = wx.Menu()
        item_rf = radio_menu.Append(wx.ID_ANY, "&RF Settings…\tCtrl+R")
        self.Bind(wx.EVT_MENU, lambda e: self._open_rf_dialog(), item_rf)
        bands_menu = wx.Menu()
        for name in BAND_NAMES:
            item = bands_menu.Append(wx.ID_ANY, name)
            self.Bind(wx.EVT_MENU, self._make_band_handler(name), item)
        radio_menu.AppendSubMenu(bands_menu, "&Bands")
        mb.Append(radio_menu, "&Radio")

        # View
        view_menu = wx.Menu()
        item_spectrum = view_menu.Append(wx.ID_ANY, "&Spectrum && Sonification…\tCtrl+S")
        self.Bind(wx.EVT_MENU, lambda e: self._open_spectrum_dialog(), item_spectrum)
        mb.Append(view_menu, "&View")

        # Tools
        tools_menu = wx.Menu()
        item_scanner = tools_menu.Append(wx.ID_ANY, "&Scanner…\tCtrl+N")
        item_bookmarks = tools_menu.Append(wx.ID_ANY, "&Bookmarks…\tCtrl+B")
        item_audio = tools_menu.Append(wx.ID_ANY, "&Audio Settings…\tCtrl+D")
        self.Bind(wx.EVT_MENU, lambda e: self._open_scanner_dialog(), item_scanner)
        self.Bind(wx.EVT_MENU, lambda e: self._open_bookmarks_dialog(), item_bookmarks)
        self.Bind(wx.EVT_MENU, lambda e: self._open_audio_dialog(), item_audio)
        mb.Append(tools_menu, "&Tools")

        # Help
        help_menu = wx.Menu()
        help_menu.Append(wx.ID_HELP, "&Keyboard Shortcuts…\tF1")
        mb.Append(help_menu, "&Help")

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
        freq_label = wx.StaticText(panel, label="Frequency:")
        self._freq_ctrl = wx.TextCtrl(
            panel,
            value=_fmt_freq(self._settings.frequency),
            style=wx.TE_PROCESS_ENTER,
            name="Frequency display",
            size=(160, -1),
        )
        self._freq_ctrl.Bind(wx.EVT_TEXT_ENTER, self._on_freq_enter)
        self._freq_ctrl.Bind(wx.EVT_SET_FOCUS, lambda e: (e.Skip(), self._freq_ctrl.SelectAll()))

        tune_up = wx.Button(panel, label="▲", name="Tune up", size=(32, -1))
        tune_dn = wx.Button(panel, label="▼", name="Tune down", size=(32, -1))
        tune_up.Bind(wx.EVT_BUTTON, lambda e: self._step_frequency(+1))
        tune_dn.Bind(wx.EVT_BUTTON, lambda e: self._step_frequency(-1))

        step_label = wx.StaticText(panel, label="Step:")
        self._step_choice = wx.Choice(panel, choices=STEP_LABELS, name="Tuning step")
        self._step_choice.SetSelection(self._step_idx)
        self._step_choice.Bind(wx.EVT_CHOICE, self._on_step_change)

        for w in (freq_label, self._freq_ctrl, tune_up, tune_dn, step_label, self._step_choice):
            freq_row.Add(w, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        outer.Add(freq_row, 0, wx.ALL, 8)

        # --- Mode / BW row ---
        mode_row = wx.BoxSizer(wx.HORIZONTAL)
        mode_label = wx.StaticText(panel, label="Mode:")
        self._mode_choice = wx.Choice(panel, choices=MODES, name="Demodulation mode")
        self._mode_choice.SetStringSelection(self._settings.mode)
        self._mode_choice.Bind(wx.EVT_CHOICE, self._on_mode_change)

        bw_label = wx.StaticText(panel, label="BW:")
        self._bw_choice = wx.Choice(panel, choices=[], name="Filter bandwidth")
        self._bw_choice.Bind(wx.EVT_CHOICE, self._on_bw_change)

        for w in (mode_label, self._mode_choice, bw_label, self._bw_choice):
            mode_row.Add(w, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        outer.Add(mode_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # --- Start/Stop + Signal ---
        ctrl_row = wx.BoxSizer(wx.HORIZONTAL)
        self._start_btn = wx.Button(panel, label="▶ Start", name="Start radio")
        self._start_btn.Bind(wx.EVT_BUTTON, self._on_start_stop)
        self._signal_lbl = wx.StaticText(panel, label="Signal: —", name="Signal strength display")
        for w in (self._start_btn, self._signal_lbl):
            ctrl_row.Add(w, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        outer.Add(ctrl_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # --- Volume row ---
        vol_row = wx.BoxSizer(wx.HORIZONTAL)
        vol_label = wx.StaticText(panel, label="Volume:")
        self._vol_slider = wx.Slider(
            panel, value=int(self._settings.volume * 100),
            minValue=0, maxValue=100,
            style=wx.SL_HORIZONTAL,
            name="Volume slider",
            size=(140, -1),
        )
        self._vol_slider.Bind(wx.EVT_SLIDER, self._on_volume)
        self._mute_btn = wx.ToggleButton(panel, label="Mute (M)", name="Mute toggle")
        self._mute_btn.SetValue(self._settings.muted)
        self._mute_btn.Bind(wx.EVT_TOGGLEBUTTON, self._on_mute)

        for w in (vol_label, self._vol_slider, self._mute_btn):
            vol_row.Add(w, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        outer.Add(vol_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # --- Squelch row ---
        sq_row = wx.BoxSizer(wx.HORIZONTAL)
        sq_label = wx.StaticText(panel, label="Squelch (dBm):")
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

        panel.SetSizer(outer)

        # Tab order
        self._freq_ctrl.MoveBeforeInTabOrder(self._mode_choice)
        self._mode_choice.MoveBeforeInTabOrder(self._bw_choice)
        self._bw_choice.MoveBeforeInTabOrder(self._start_btn)
        self._start_btn.MoveBeforeInTabOrder(self._vol_slider)
        self._vol_slider.MoveBeforeInTabOrder(self._sq_slider)

        self._update_bw_choices(self._settings.mode)

    def _build_status_bar(self) -> None:
        self._statusbar = self.CreateStatusBar(name="Status bar")
        self._statusbar.SetStatusText("Ready — no device connected.")

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
        wx.CallAfter(self._freq_ctrl.SetValue, _fmt_freq(freq_hz))
        wx.CallAfter(speech.speak, _fmt_freq(freq_hz))
        wx.CallAfter(self._statusbar.SetStatusText, f"Tuned to {_fmt_freq(freq_hz)}")

    def _step_frequency(self, direction: int) -> None:
        step = STEPS[self._step_idx]
        new_freq = self._settings.frequency + direction * step
        new_freq = max(100_000, new_freq)
        self._tune(new_freq)

    def _on_freq_enter(self, _event: wx.CommandEvent) -> None:
        text = self._freq_ctrl.GetValue().strip().lower()
        try:
            # Accept bare MHz number or "98.1 MHz"
            text = text.replace("mhz", "").replace("khz", "").replace("hz", "").strip()
            # Heuristic: if no decimal or value > 1e6 treat as Hz, else MHz
            val = float(text)
            if val < 30_000:
                freq_hz = int(val * 1_000_000)    # assumed MHz
            elif val < 30_000_000:
                freq_hz = int(val * 1_000)        # assumed kHz
            else:
                freq_hz = int(val)
        except ValueError:
            speech.speak("Invalid frequency.")
            return
        self._tune(freq_hz)

    def _on_step_change(self, event: wx.CommandEvent) -> None:
        self._step_idx = event.GetSelection()
        self._settings.step = STEPS[self._step_idx]
        speech.speak(f"Step {STEP_LABELS[self._step_idx]}")

    def _cycle_step(self) -> None:
        self._step_idx = (self._step_idx + 1) % len(STEPS)
        self._step_choice.SetSelection(self._step_idx)
        self._settings.step = STEPS[self._step_idx]
        speech.speak(f"Step {STEP_LABELS[self._step_idx]}")

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
        speech.speak(f"Mode {mode}")

    def _on_bw_change(self, event: wx.CommandEvent) -> None:
        mode = self._mode_choice.GetStringSelection()
        options = BW_OPTIONS.get(mode, [])
        idx = event.GetSelection()
        if 0 <= idx < len(options):
            self._settings.bandwidth = options[idx][0]
            speech.speak(f"Bandwidth {options[idx][1]}")

    def _set_mode(self, mode: str) -> None:
        if mode not in MODES:
            return
        self._mode_choice.SetStringSelection(mode)
        self._settings.mode = mode
        self._update_bw_choices(mode)
        self._was_stereo = None
        speech.speak(f"Mode {mode}")

    # ==================================================================
    # Start / Stop
    # ==================================================================

    def _on_start_stop(self, _event: wx.CommandEvent) -> None:
        if self._running:
            self._stop_radio()
        else:
            self._start_radio()

    def _start_radio(self) -> None:
        if not self._sdr.open():
            speech.speak("Could not open SDR device.")
            return
        # Create stateful demodulator — filters pre-computed, state preserved across chunks
        self._demodulator: Demodulator = make_demodulator(
            self._settings.mode, BASEBAND_RATE, AUDIO_RATE
        )
        self._sdr.set_frequency(self._settings.frequency)
        self._sdr.set_sample_rate(self._settings.sample_rate)
        self._sdr.set_gain(self._settings.gain)
        self._sdr.set_ppm(self._settings.ppm)
        self._sdr.start()

        self._audio.start()

        self._running = True
        self._dsp_thread = threading.Thread(
            target=self._dsp_loop, daemon=True, name="DSPThread"
        )
        self._dsp_thread.start()

        self._start_btn.SetLabel("■ Stop")
        self._statusbar.SetStatusText(f"Receiving — {_fmt_freq(self._settings.frequency)}")
        speech.speak("Radio started.")

    def _stop_radio(self) -> None:
        self._running = False
        self._sdr.stop()
        self._audio.stop()
        if self._dsp_thread:
            self._dsp_thread.join(timeout=2.0)
            self._dsp_thread = None
        self._was_stereo = None
        self._signal_lbl.SetLabel("Signal: —")
        self._start_btn.SetLabel("▶ Start")
        self._statusbar.SetStatusText("Stopped.")
        speech.speak("Radio stopped.")

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
                self._demodulator = make_demodulator(current_mode, BASEBAND_RATE, AUDIO_RATE)
                dsp_stereo = None
                stereo_delay = 0

            # Re-announce stereo status after a retune, but delay so the
            # frequency speech finishes before the stereo announcement fires.
            if self._retune_pending:
                self._retune_pending = False
                dsp_stereo = None
                stereo_delay = 6   # ~6 chunks ≈ 300–400 ms at typical chunk sizes

            # RF signal power from raw IQ (dBFS, 0 = full scale).
            # Measuring here — before any DSP — correctly tracks gain changes.
            iq_power = float(np.mean(np.abs(iq.astype(np.complex128)) ** 2))
            self._audio.signal_db = 10.0 * np.log10(max(iq_power, 1e-10))

            # Decimate to baseband
            bb = decimate(iq, self._settings.sample_rate, BASEBAND_RATE)

            # Spectrum analysis
            spec = self._spectrum.process(bb)
            wx.CallAfter(self._on_spectrum_update, spec)

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
                    label = "Stereo" if stereo else "Mono"
                    wx.CallAfter(
                        self._statusbar.SetStatusText,
                        f"Receiving — {_fmt_freq(self._settings.frequency)} [{label}]",
                    )

    def _on_spectrum_update(self, spectrum: np.ndarray) -> None:
        """Called on UI thread with updated spectrum data."""
        self._last_spectrum = spectrum

        # Update signal strength display
        strength = self._audio.signal_db
        self._signal_lbl.SetLabel(
            f"Signal: {strength:.1f} dBFS  [{_signal_quality(strength)}]"
        )

        # Feed sonification
        if self._settings.sonification_enabled:
            self._sonification.set_spectrum(spectrum)

        # Auto-announce strong signals
        if strength >= self._settings.auto_announce_threshold:
            # Throttle to avoid spamming — only speak when level crosses threshold
            pass  # TODO: implement threshold crossing detection

    # ==================================================================
    # Volume / Squelch / Mute
    # ==================================================================

    def _on_volume(self, event: wx.CommandEvent) -> None:
        val = event.GetInt() / 100.0
        self._audio.volume = val
        self._settings.volume = val
        speech.speak(f"Volume {event.GetInt()} percent")

    def _on_mute(self, event: wx.CommandEvent) -> None:
        muted = self._mute_btn.GetValue()
        self._audio.muted = muted
        self._settings.muted = muted
        speech.speak("Muted" if muted else "Unmuted")

    def _on_squelch(self, event: wx.CommandEvent) -> None:
        val = float(event.GetInt())
        self._audio.squelch = val
        self._settings.squelch = val
        self._sq_lbl.SetLabel(f"{val:.0f} dBm")
        speech.speak(f"Squelch {val:.0f} dBm")

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

        # Mode keys
        char = chr(code) if 32 <= code < 128 else ""
        if char.upper() in MODE_KEYS and modifiers == 0:
            self._set_mode(MODE_KEYS[char.upper()])
            return

        if code == ord("S") and modifiers == 0:
            self._cycle_step()
            return

        if code == ord("M") and modifiers == 0:
            val = not self._mute_btn.GetValue()
            self._mute_btn.SetValue(val)
            self._audio.muted = val
            self._settings.muted = val
            speech.speak("Muted" if val else "Unmuted")
            return

        if code == ord("I") and modifiers == 0:
            if not self._running:
                speech.speak("Radio not running.")
            else:
                parts = []
                db = self._audio.signal_db
                parts.append(f"Signal {db:.1f} dBFS, {_signal_quality(db)}")
                if self._settings.mode == "WFM" and self._demodulator is not None:
                    stereo = getattr(self._demodulator, "stereo_detected", False)
                    parts.append("Stereo" if stereo else "Mono")
                squelch_open = db >= self._audio.squelch
                parts.append("Squelch open" if squelch_open else "Squelch closed")
                if self._audio.muted:
                    parts.append("Muted")
                speech.speak(", ".join(parts))
            return

        if code == wx.WXK_SPACE and modifiers == 0:
            if self._settings.sonification_enabled and self._last_spectrum is not None:
                self._sonification.snapshot()
                speech.speak("Sonification snapshot.")
            return

        if code == ord("F") and modifiers == 0:
            self._speak_peaks()
            return

        if code == ord("R") and modifiers == 0:
            self._on_start_stop(event)
            return

        if code == wx.WXK_UP and modifiers == 0:
            self._step_frequency(+1)
            return

        if code == wx.WXK_DOWN and modifiers == 0:
            self._step_frequency(-1)
            return

        if code == wx.WXK_UP and modifiers == wx.ACCEL_CTRL:
            self._step_frequency(+10)
            return

        if code == wx.WXK_DOWN and modifiers == wx.ACCEL_CTRL:
            self._step_frequency(-10)
            return

        if code == wx.WXK_F1:
            self._open_help_dialog()
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

        event.Skip()

    def _speak_peaks(self) -> None:
        """Speak top N spectrum peaks (F key)."""
        if self._last_spectrum is None:
            speech.speak("No spectrum data yet.")
            return
        peaks = SpectrumAnalyser.find_peaks(
            self._last_spectrum,
            centre_hz=self._settings.frequency,
            sample_rate=self._settings.sample_rate,
            n_peaks=self._settings.speech_peak_count,
        )
        if not peaks:
            speech.speak("No peaks detected.")
            return
        parts = [f"{f / 1e6:.3f} MHz {db:.0f} dBm" for f, db in peaks]
        speech.speak("Peaks: " + ", ".join(parts))

    # ==================================================================
    # Band jump
    # ==================================================================

    def _make_band_handler(self, name: str):
        def handler(_event):
            lo, hi, mode = get_band(name)
            freq = centre_frequency(name)
            self._tune(freq)
            self._set_mode(mode)
            speech.speak(f"Band: {name}, {_fmt_freq(freq)}, mode {mode}")
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
        self._open_or_raise(
            "rf",
            lambda: RFDialog(self, self._settings, on_change=self._on_rf_settings_changed),
        )

    def _open_spectrum_dialog(self) -> None:
        from ui.dialogs.spectrum_dialog import SpectrumDialog
        self._open_or_raise(
            "spectrum",
            lambda: SpectrumDialog(
                self, self._settings, self._sonification, on_change=self._save_settings
            ),
        )

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
        self._open_or_raise(
            "audio",
            lambda: AudioDialog(
                self, self._settings, self._audio, on_change=self._save_settings
            ),
        )

    def _open_help_dialog(self) -> None:
        from ui.dialogs.help_dialog import HelpDialog
        self._open_or_raise("help", lambda: HelpDialog(self))

    def _on_open_help(self, _event) -> None:
        self._open_help_dialog()

    # ==================================================================
    # Callbacks
    # ==================================================================

    def _on_bookmark_load(self, bm: Bookmark) -> None:
        self._tune(bm.frequency)
        self._set_mode(bm.mode)

    def _on_rf_settings_changed(self, settings: Settings) -> None:
        self._settings = settings
        if self._running:
            self._sdr.set_gain(settings.gain)
            self._sdr.set_ppm(settings.ppm)
            self._sdr.set_sample_rate(settings.sample_rate)

    def _save_settings(self, settings: Settings) -> None:
        self._settings = settings
        settings.save()

    def _on_sdr_error(self, msg: str) -> None:
        wx.CallAfter(speech.speak, f"SDR error: {msg}")
        wx.CallAfter(self._statusbar.SetStatusText, f"Error: {msg}")

    # ==================================================================
    # Shutdown
    # ==================================================================

    def _on_exit(self, _event) -> None:
        self.Close()

    def _on_close(self, event: wx.CloseEvent) -> None:
        self._stop_radio()
        self._settings.save()
        self._bookmarks.save()
        for dlg in self._dialogs.values():
            try:
                dlg.Destroy()
            except Exception:   # noqa: BLE001
                pass
        event.Skip()
