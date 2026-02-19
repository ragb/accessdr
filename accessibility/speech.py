"""
accessibility/speech.py — Screen-reader speech and braille output wrapper.

Uses accessible_output2 to speak text and send it to a braille display
through the active screen reader (NVDA, JAWS, System Access, etc.).

The ``output`` function sends text to both speech and braille
simultaneously.  Use ``speak`` or ``braille`` individually when only
one channel is needed.

Falls back to a no-op if accessible_output2 is unavailable, so the
rest of the application can still run without a screen reader present.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

try:
    import accessible_output2.outputs.auto as _ao2
    _OUTPUT = _ao2.Auto()
    _AO2_AVAILABLE = True
except Exception as exc:          # noqa: BLE001
    logger.warning("accessible_output2 not available: %s", exc)
    _OUTPUT = None
    _AO2_AVAILABLE = False


def speak(text: str, interrupt: bool = True) -> None:
    """Speak *text* via the active screen reader.

    Parameters
    ----------
    text:
        The string to speak.
    interrupt:
        If True (default), interrupt any currently-spoken text first.
    """
    if not _AO2_AVAILABLE or _OUTPUT is None:
        logger.debug("speech (no-op): %s", text)
        return
    try:
        _OUTPUT.speak(text, interrupt=interrupt)
    except Exception as exc:      # noqa: BLE001
        logger.warning("speech error: %s", exc)


def braille(text: str) -> None:
    """Send *text* to the screen reader's braille display."""
    if not _AO2_AVAILABLE or _OUTPUT is None:
        logger.debug("braille (no-op): %s", text)
        return
    try:
        _OUTPUT.braille(text)
    except Exception as exc:      # noqa: BLE001
        logger.warning("braille error: %s", exc)


def output(text: str, interrupt: bool = True) -> None:
    """Send *text* to both speech and braille.

    Note: ``Auto.output()`` has a bug that skips braille, so we call
    ``speak()`` and ``braille()`` explicitly.
    """
    speak(text, interrupt=interrupt)
    braille(text)


def silence() -> None:
    """Stop any currently-spoken speech immediately."""
    if not _AO2_AVAILABLE or _OUTPUT is None:
        return
    try:
        _OUTPUT.silence()
    except Exception as exc:      # noqa: BLE001
        logger.warning("silence error: %s", exc)


def is_available() -> bool:
    """Return True if a speech backend was successfully initialised."""
    return _AO2_AVAILABLE
