"""
core/scanner.py — Frequency scanner logic.

Scans a frequency range step-by-step, dwelling on each frequency long
enough to detect a signal above a squelch threshold.  Emits callbacks
when signals are found.

Threading
---------
The scanner runs in a daemon thread.  All callbacks are dispatched via
the caller-supplied dispatcher (typically wx.CallAfter) so they arrive
safely on the UI thread.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# How many spectrum updates to collect per dwell before judging
DWELL_UPDATES = 3
DWELL_SECONDS = 0.3             # seconds per step


class ScanResult:
    """A frequency where a signal was detected."""

    def __init__(self, freq_hz: int, strength_db: float) -> None:
        self.freq_hz = freq_hz
        self.strength_db = strength_db

    def __repr__(self) -> str:
        return f"ScanResult({self.freq_hz / 1e6:.3f} MHz, {self.strength_db:.1f} dBm)"


class Scanner:
    """Step-scan a frequency range and report signals above squelch."""

    def __init__(
        self,
        set_frequency_cb: Callable[[int], None],
        get_signal_db_cb: Callable[[], float],
        dispatcher: Callable = lambda f, *a, **kw: f(*a, **kw),
    ) -> None:
        """
        Parameters
        ----------
        set_frequency_cb:
            Callable that tunes the SDR to a given Hz.
        get_signal_db_cb:
            Callable that returns the current peak signal in dBm.
        dispatcher:
            Used to push callbacks to the UI thread (typically wx.CallAfter).
        """
        self._set_freq = set_frequency_cb
        self._get_signal = get_signal_db_cb
        self._dispatch = dispatcher

        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._hold = False
        self._skip = False

        self.results: List[ScanResult] = []

        # Callbacks for UI
        self.on_signal_found: Optional[Callable[[ScanResult], None]] = None
        self.on_scan_complete: Optional[Callable[[List[ScanResult]], None]] = None
        self.on_frequency_change: Optional[Callable[[int], None]] = None

    # ------------------------------------------------------------------
    # Public control
    # ------------------------------------------------------------------

    def start(
        self,
        start_hz: int,
        stop_hz: int,
        step_hz: int,
        squelch_db: float = -80.0,
    ) -> None:
        """Begin scanning from *start_hz* to *stop_hz* in *step_hz* steps."""
        if self._running:
            self.stop()

        self.results = []
        self._running = True
        self._hold = False
        self._skip = False

        self._thread = threading.Thread(
            target=self._scan_loop,
            args=(start_hz, stop_hz, step_hz, squelch_db),
            daemon=True,
            name="Scanner",
        )
        self._thread.start()

    def stop(self) -> None:
        """Abort the current scan."""
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def hold(self) -> None:
        """Pause on current frequency (toggle)."""
        self._hold = not self._hold

    def skip(self) -> None:
        """Skip to next frequency immediately."""
        self._skip = True

    @property
    def is_running(self) -> bool:
        return self._running

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _scan_loop(
        self,
        start_hz: int,
        stop_hz: int,
        step_hz: int,
        squelch_db: float,
    ) -> None:
        freq = start_hz
        while self._running and freq <= stop_hz:
            self._set_freq(freq)

            if self.on_frequency_change:
                self._dispatch(self.on_frequency_change, freq)

            # Dwell
            dwell_end = time.monotonic() + DWELL_SECONDS
            while time.monotonic() < dwell_end and self._running and not self._skip:
                if self._hold:
                    time.sleep(0.05)
                    dwell_end = time.monotonic() + DWELL_SECONDS
                    continue
                time.sleep(0.02)

            self._skip = False

            if not self._running:
                break

            # Check signal
            strength = self._get_signal()
            if strength >= squelch_db:
                result = ScanResult(freq_hz=freq, strength_db=strength)
                self.results.append(result)
                logger.info("Signal found: %s", result)
                if self.on_signal_found:
                    self._dispatch(self.on_signal_found, result)
                # Hold briefly on found signal
                time.sleep(1.5)

            freq += step_hz

        self._running = False
        if self.on_scan_complete:
            self._dispatch(self.on_scan_complete, list(self.results))
