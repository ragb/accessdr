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
    """A frequency where a signal was detected.

    *label* names the target when scanning a channel map (e.g. "CH05 Calling"),
    and is empty for a plain frequency-range / band scan.
    """

    def __init__(self, freq_hz: int, strength_db: float, label: str = "") -> None:
        self.freq_hz = freq_hz
        self.strength_db = strength_db
        self.label = label

    def __repr__(self) -> str:
        return f"ScanResult({self.freq_hz / 1e6:.3f} MHz, {self.strength_db:.1f} dBm)"


class Scanner:
    """Step-scan a frequency range and report signals above squelch."""

    def __init__(
        self,
        set_frequency_cb: Callable[[int], None],
        get_signal_db_cb: Callable[[], float],
        dispatcher: Callable = lambda f, *a, **kw: f(*a, **kw),
        get_squelch_open_cb: Optional[Callable[[], bool]] = None,
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
        get_squelch_open_cb:
            Callable returning True when the auto squelch gate considers
            a signal present.  Used for signal detection during scanning.
        """
        self._set_freq = set_frequency_cb
        self._get_signal = get_signal_db_cb
        self._dispatch = dispatcher
        self._get_squelch_open = get_squelch_open_cb

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
    ) -> None:
        """Scan a frequency range from *start_hz* to *stop_hz* in *step_hz* steps.

        Used for band scans (the band supplies start/stop/step).
        """
        if step_hz <= 0:
            step_hz = 100_000
        targets: List[Tuple[int, str]] = []
        freq = start_hz
        while freq <= stop_hz:
            targets.append((freq, ""))
            freq += step_hz
        self.start_targets(targets)

    def start_list(
        self,
        freqs: List[int],
        labels: Optional[List[str]] = None,
    ) -> None:
        """Scan a discrete list of frequencies (channel-map / memory scan)."""
        labels = labels or [""] * len(freqs)
        self.start_targets(list(zip(freqs, labels)))

    def start_targets(
        self,
        targets: List[Tuple[int, str]],
    ) -> None:
        """Scan an explicit list of ``(freq_hz, label)`` targets."""
        if self._running:
            self.stop()

        self.results = []
        self._running = True
        self._hold = False
        self._skip = False

        self._thread = threading.Thread(
            target=self._scan_loop,
            args=(list(targets),),
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
        targets: List[Tuple[int, str]],
    ) -> None:
        i = 0
        n = len(targets)
        while self._running and i < n:
            freq, label = targets[i]
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

            # Check signal via the live auto squelch gate
            strength = self._get_signal()
            signal_found = (
                self._get_squelch_open()
                if self._get_squelch_open is not None
                else False
            )
            if signal_found:
                result = ScanResult(freq_hz=freq, strength_db=strength, label=label)
                self.results.append(result)
                logger.info("Signal found: %s", result)
                if self.on_signal_found:
                    self._dispatch(self.on_signal_found, result)
                # Hold briefly on found signal
                time.sleep(1.5)

            i += 1

        self._running = False
        if self.on_scan_complete:
            self._dispatch(self.on_scan_complete, list(self.results))
