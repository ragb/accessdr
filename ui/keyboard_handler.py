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

# --- Radio control ---
START_STOP = "start_stop"
TOGGLE_PAUSE = "toggle_pause"
TOGGLE_MUTE = "toggle_mute"

# --- Info ---
ANNOUNCE_INFO = "announce_info"

# --- Volume / squelch ---
VOLUME_UP = "volume_up"
VOLUME_DOWN = "volume_down"
SQUELCH_UP = "squelch_up"
SQUELCH_DOWN = "squelch_down"

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
OPEN_BOOKMARKS_DIALOG = "open_bookmarks_dialog"
OPEN_AUDIO_DIALOG = "open_audio_dialog"
OPEN_WFM_DIALOG = "open_wfm_dialog"
OPEN_USER_GUIDE = "open_user_guide"

# --- Window ---
CLOSE_WINDOW = "close_window"


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
        (wx.WXK_SPACE, NONE):        TOGGLE_PAUSE,
        (wx.WXK_SPACE, M):           TOGGLE_PAUSE,
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

        # Volume / squelch
        (wx.WXK_PAGEUP, NONE):      VOLUME_UP,
        (wx.WXK_PAGEDOWN, NONE):    VOLUME_DOWN,
        (wx.WXK_PAGEUP, S):         SQUELCH_UP,
        (wx.WXK_PAGEDOWN, S):       SQUELCH_DOWN,

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
        (ord("B"), M):               OPEN_BOOKMARKS_DIALOG,
        (ord("D"), M):               OPEN_AUDIO_DIALOG,
        (ord("W"), M):               OPEN_WFM_DIALOG,
        (ord("H"), M):               OPEN_USER_GUIDE,

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
