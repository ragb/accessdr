"""ui/spectrum_controller.py — Spectrum zoom and info announcements.

Manages zoom level, computes the visible frequency range, slices
spectrum arrays to the zoomed region, and provides speech output for
zoom state and spectrum peaks.  No wx dependency beyond the spectrum
panel that is passed in.
"""

from __future__ import annotations

from typing import Optional

import numpy as np

from accessibility import speech
from core.dsp.spectrum import SpectrumAnalyser
from core.signal_utils import s_meter
from ui.formatting import fmt_freq


class SpectrumController:
    """Zoom math, spectrum slicing, and info announcements."""

    MAX_ZOOM = 5

    def __init__(self, settings, spectrum_panel) -> None:
        self._settings = settings
        self._panel = spectrum_panel
        self._zoom_level: int = 0

    # ------------------------------------------------------------------
    # Zoom level
    # ------------------------------------------------------------------

    @property
    def zoom_level(self) -> int:
        return self._zoom_level

    def zoom_slice(self, spectrum: np.ndarray) -> np.ndarray:
        """Return the centre portion of *spectrum* according to zoom level."""
        if self._zoom_level == 0:
            return spectrum
        factor = 2 ** self._zoom_level
        n = len(spectrum)
        mid = n // 2
        half = n // (2 * factor)
        return spectrum[mid - half : mid + half]

    def spectrum_range(self) -> tuple[float, float]:
        """Return (start_hz, end_hz) of the current zoomed view."""
        half_span = self._settings.sample_rate / (2 * 2 ** self._zoom_level)
        centre = self._settings.frequency
        return (centre - half_span, centre + half_span)

    def zoom_in(self) -> None:
        if self._zoom_level >= self.MAX_ZOOM:
            speech.output(_("Already at maximum zoom."))
            return
        self._zoom_level += 1
        self._announce_zoom()
        self._panel.set_zoom(self._zoom_level)

    def zoom_out(self) -> None:
        if self._zoom_level <= 0:
            speech.output(_("Already at full spectrum."))
            return
        self._zoom_level -= 1
        self._announce_zoom()
        self._panel.set_zoom(self._zoom_level)

    def zoom_reset(self) -> None:
        if self._zoom_level == 0:
            speech.output(_("Already at full spectrum."))
            return
        self._zoom_level = 0
        self._announce_zoom()
        self._panel.set_zoom(self._zoom_level)

    # ------------------------------------------------------------------
    # Speech announcements
    # ------------------------------------------------------------------

    def _announce_zoom(self) -> None:
        start_hz, end_hz = self.spectrum_range()
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

    def describe_spectrum(self, sweeping: bool = False) -> None:
        start_hz, end_hz = self.spectrum_range()
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
        if sweeping:
            msg += _(", sweep active")
        speech.output(msg)

    def speak_peaks(self, last_spectrum: Optional[np.ndarray]) -> None:
        """Speak top N spectrum peaks, respecting zoom."""
        if last_spectrum is None:
            speech.output(_("No spectrum data yet."))
            return
        zoomed = self.zoom_slice(last_spectrum)
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
