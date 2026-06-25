"""ui/keyboard_handler.py — Keyboard shortcut dispatch table.

Maps (keycode, modifiers) pairs to action name strings.  The MainWindow
interprets action names and calls the appropriate methods.  This keeps
the shortcut definitions separate from the implementation logic.
"""

from __future__ import annotations

import wx


# Action name constants — used as keys in the dispatch result.
# Grouped by functional area for readability.

# --- Frequency / tuning ---
ANNOUNCE_LO = "announce_lo"
ANNOUNCE_LISTEN = "announce_listen"
CYCLE_STEP = "cycle_step"
FREQ_UP = "freq_up"
FREQ_DOWN = "freq_down"
FREQ_UP_FAST = "freq_up_fast"
FREQ_DOWN_FAST = "freq_down_fast"
OPEN_FREQ_DIALOG = "open_freq_dialog"
OPEN_DEMOD_FREQ_DIALOG = "open_demod_freq_dialog"

# --- Mode selection ---
MODE_SELECT_START = "mode_select_start"

# --- Channel / scene navigation (VFO / MR) ---
PAGE_NAV_UP = "page_nav_up"
PAGE_NAV_DOWN = "page_nav_down"
TOGGLE_VFO_MR = "toggle_vfo_mr"
SCENE_PREV = "scene_prev"
SCENE_NEXT = "scene_next"

# --- Radio control ---
START_STOP = "start_stop"
TOGGLE_MUTE = "toggle_mute"
TOGGLE_RECORDING = "toggle_recording"

# --- Info ---
ANNOUNCE_INFO = "announce_info"
ANNOUNCE_SIGNAL = "announce_signal"

# --- Volume / squelch / gain ---
VOLUME_UP = "volume_up"
VOLUME_DOWN = "volume_down"
SQUELCH_UP = "squelch_up"
SQUELCH_DOWN = "squelch_down"
SQUELCH_TOGGLE = "squelch_toggle"
SQUELCH_MONITOR = "squelch_monitor"
GAIN_UP = "gain_up"
GAIN_DOWN = "gain_down"

# --- Sonification / spectrum ---
SNAPSHOT = "snapshot"
TOGGLE_SWEEP = "toggle_sweep"
SPEAK_PEAKS = "speak_peaks"
DESCRIBE_SPECTRUM = "describe_spectrum"

# --- Cursor / VFO ---
CURSOR_LEFT = "cursor_left"
CURSOR_RIGHT = "cursor_right"
CURSOR_CTRL_LEFT = "cursor_ctrl_left"
CURSOR_CTRL_RIGHT = "cursor_ctrl_right"
RESET_CURSOR = "reset_cursor"
SPEAK_CURSOR = "speak_cursor"
TUNE_TO_CURSOR = "tune_to_cursor"
TOGGLE_DEMOD_FOLLOWS = "toggle_demod_follows"

# --- Zoom ---
ZOOM_IN = "zoom_in"
ZOOM_OUT = "zoom_out"
ZOOM_RESET = "zoom_reset"

# --- Dialogs ---
OPEN_HELP = "open_help"
OPEN_RF_DIALOG = "open_rf_dialog"
OPEN_SPECTRUM_DIALOG = "open_spectrum_dialog"
OPEN_SCANNER_DIALOG = "open_scanner_dialog"
OPEN_CHANNELS_DIALOG = "open_channels_dialog"
OPEN_BANDS_DIALOG = "open_bands_dialog"
OPEN_AUDIO_DIALOG = "open_audio_dialog"
OPEN_RTL_TCP_DIALOG = "open_rtl_tcp_dialog"
OPEN_RECORDING_DIALOG = "open_recording_dialog"
OPEN_USER_GUIDE = "open_user_guide"

# --- Window ---
CLOSE_WINDOW = "close_window"


# ---------------------------------------------------------------------------
# Context sets — which actions are live in which operating mode.
#
# The active notebook tab is the operating mode (VFO vs Memory).  Cursor and
# spectrum controls only make sense in VFO (the spectrum is hidden in Memory),
# so they are gated there; the always-relevant controls work in both modes.
# These are the single source of truth for both _on_key gating and the
# grouped keyboard-shortcuts help.
# ---------------------------------------------------------------------------

# Work in both modes (radio control, volume/squelch/mute, info, mode toggle,
# recording, and every menu/dialog opener).
GLOBAL_ACTIONS = frozenset({
    START_STOP, TOGGLE_MUTE, TOGGLE_RECORDING, ANNOUNCE_INFO, ANNOUNCE_SIGNAL,
    VOLUME_UP, VOLUME_DOWN,
    SQUELCH_UP, SQUELCH_DOWN, SQUELCH_TOGGLE, SQUELCH_MONITOR,
    GAIN_UP, GAIN_DOWN,
    TOGGLE_VFO_MR, CLOSE_WINDOW, OPEN_HELP,
    # Page nav steps the frequency in VFO and the channel in Memory.
    PAGE_NAV_UP, PAGE_NAV_DOWN,
    OPEN_RF_DIALOG, OPEN_SPECTRUM_DIALOG, OPEN_SCANNER_DIALOG,
    OPEN_CHANNELS_DIALOG, OPEN_BANDS_DIALOG, OPEN_AUDIO_DIALOG,
    OPEN_RTL_TCP_DIALOG, OPEN_RECORDING_DIALOG, OPEN_USER_GUIDE,
    OPEN_FREQ_DIALOG, OPEN_DEMOD_FREQ_DIALOG,
})

# VFO only: spectrum, cursor, and free-tuning actions.
VFO_ACTIONS = frozenset({
    SPEAK_PEAKS, DESCRIBE_SPECTRUM, ZOOM_IN, ZOOM_OUT, ZOOM_RESET,
    SNAPSHOT, TOGGLE_SWEEP,
    CURSOR_LEFT, CURSOR_RIGHT, CURSOR_CTRL_LEFT, CURSOR_CTRL_RIGHT,
    RESET_CURSOR, SPEAK_CURSOR, TUNE_TO_CURSOR, TOGGLE_DEMOD_FOLLOWS,
    FREQ_UP, FREQ_DOWN, FREQ_UP_FAST, FREQ_DOWN_FAST, CYCLE_STEP,
    MODE_SELECT_START, SCENE_PREV, SCENE_NEXT,
    ANNOUNCE_LO, ANNOUNCE_LISTEN,
})

# Memory (Channels) only, beyond the globals: nothing extra today (page nav
# and the mode toggle are global). Kept for symmetry / future channel actions.
CHANNELS_ACTIONS = frozenset()


def _build_keymap() -> dict[tuple[int, int], str]:
    """Build the (keycode, modifiers) → action mapping.

    Called once at import time.  wx constants are available because wx
    is imported at module level.
    """
    M = wx.MOD_CONTROL
    S = wx.MOD_SHIFT
    NONE = 0

    km: dict[tuple[int, int], str] = {
        # Radio control
        (wx.WXK_F2, NONE):           START_STOP,
        (wx.WXK_F3, NONE):           TOGGLE_MUTE,

        # Frequency
        (ord("Q"), NONE):            ANNOUNCE_LO,
        (ord("O"), NONE):            ANNOUNCE_LISTEN,
        (ord("S"), NONE):            CYCLE_STEP,
        (wx.WXK_UP, NONE):          FREQ_UP,
        (wx.WXK_DOWN, NONE):        FREQ_DOWN,
        (wx.WXK_UP, S):             FREQ_UP_FAST,
        (wx.WXK_DOWN, S):           FREQ_DOWN_FAST,

        # Mode
        (ord("M"), NONE):            MODE_SELECT_START,

        # Info
        (ord("I"), NONE):            ANNOUNCE_INFO,
        (ord("D"), NONE):            ANNOUNCE_SIGNAL,

        # Channel / scene navigation
        (wx.WXK_PAGEUP, NONE):      PAGE_NAV_UP,
        (wx.WXK_PAGEDOWN, NONE):    PAGE_NAV_DOWN,
        (ord("V"), NONE):            TOGGLE_VFO_MR,
        (ord("["), NONE):            SCENE_PREV,
        (ord("]"), NONE):            SCENE_NEXT,

        # Volume / squelch
        (wx.WXK_F11, NONE):         VOLUME_UP,
        (wx.WXK_F12, NONE):         VOLUME_DOWN,
        (wx.WXK_F11, S):            GAIN_UP,
        (wx.WXK_F12, S):            GAIN_DOWN,
        (ord("A"), M | S):          SQUELCH_TOGGLE,
        (wx.WXK_F4, M):             SQUELCH_TOGGLE,
        (ord("L"), NONE):            SQUELCH_MONITOR,
        (wx.WXK_F4, NONE):          SQUELCH_MONITOR,

        # Sonification
        (wx.WXK_F5, NONE):          SNAPSHOT,
        (wx.WXK_F5, M):             TOGGLE_SWEEP,

        # Spectrum / peaks
        (ord("F"), NONE):            SPEAK_PEAKS,
        (ord("G"), NONE):            DESCRIBE_SPECTRUM,

        # Cursor / VFO
        (wx.WXK_LEFT, NONE):        CURSOR_LEFT,
        (wx.WXK_RIGHT, NONE):       CURSOR_RIGHT,
        (wx.WXK_LEFT, M):           CURSOR_CTRL_LEFT,
        (wx.WXK_RIGHT, M):          CURSOR_CTRL_RIGHT,
        (ord("C"), NONE):            RESET_CURSOR,
        (ord("C"), S):               TOGGLE_DEMOD_FOLLOWS,
        (ord("T"), NONE):            SPEAK_CURSOR,
        (ord("T"), M):               TUNE_TO_CURSOR,

        # Zoom
        (ord("="), NONE):            ZOOM_IN,
        (ord("+"), NONE):            ZOOM_IN,
        (wx.WXK_NUMPAD_ADD, NONE):  ZOOM_IN,
        (ord("-"), NONE):            ZOOM_OUT,
        (wx.WXK_NUMPAD_SUBTRACT, NONE): ZOOM_OUT,
        (wx.WXK_BACK, NONE):        ZOOM_RESET,

        # Dialogs (Ctrl+key)
        (ord("Q"), M):               OPEN_FREQ_DIALOG,
        (ord("O"), M):               OPEN_DEMOD_FREQ_DIALOG,
        (ord("R"), M):               OPEN_RF_DIALOG,
        (ord("S"), M):               OPEN_SPECTRUM_DIALOG,
        (ord("N"), M):               OPEN_SCANNER_DIALOG,
        (ord("B"), M):               OPEN_CHANNELS_DIALOG,
        (ord("B"), M | S):           OPEN_BANDS_DIALOG,
        (ord("D"), M):               OPEN_AUDIO_DIALOG,
        (ord("G"), M):               OPEN_RTL_TCP_DIALOG,
        (ord("E"), M):               OPEN_RECORDING_DIALOG,
        (ord("H"), M):               OPEN_USER_GUIDE,

        # Recording
        (ord("R"), NONE):            TOGGLE_RECORDING,

        # Help
        (wx.WXK_F1, NONE):          OPEN_HELP,

        # Window
        (wx.WXK_F4, wx.MOD_ALT):    CLOSE_WINDOW,
    }
    return km


KEYMAP: dict[tuple[int, int], str] = _build_keymap()


def lookup(code: int, modifiers: int) -> str | None:
    """Return the action name for a keypress, or *None* if unbound."""
    return KEYMAP.get((code, modifiers))
