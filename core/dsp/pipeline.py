"""core/dsp/pipeline.py — Per-chunk DSP pipeline.

Owns the demodulator, decimator, mixer, noise blanker, and spectrum
analyser.  Processes raw IQ chunks on the SDR capture thread and
reports events (spectrum updates, stereo/RDS changes) via callbacks.
No wx dependency.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np

from config.modes import AUDIO_RATE, baseband_rate_for
from core.dsp.demodulator import Demodulator, make_demodulator
from core.dsp.filters import StatefulDecimator
from core.dsp.mixer import Mixer
from core.dsp.noise_blanker import NoiseBlanker
from core.dsp.spectrum import SpectrumAnalyser

logger = logging.getLogger(__name__)


@dataclass
class PipelineCallbacks:
    """Callback hooks for UI notifications from the DSP thread.

    All callbacks are invoked on the **SDR capture thread** — callers
    are responsible for marshalling to the UI thread (e.g. wx.CallAfter).
    """
    on_spectrum: Optional[Callable[[np.ndarray], None]] = None
    on_stereo_change: Optional[Callable[[bool], None]] = None
    on_rds_station: Optional[Callable[[str], None]] = None


class DSPPipeline:
    """Stateful per-chunk DSP pipeline.

    Constructed once per radio start; holds all mutable DSP state that
    was previously scattered across MainWindow.
    """

    def __init__(
        self,
        sample_rate: int,
        chunk_size: int,
        mode: str,
        noise_blanker: NoiseBlanker,
        audio_write: Callable[[np.ndarray], None],
        signal_db_setter: Callable[[float], None],
        audio_underruns_getter: Callable[[], int],
        audio_overruns_getter: Callable[[], int],
        fft_size: int = 1024,
        wfm_kwargs: Optional[dict] = None,
        nfm_kwargs: Optional[dict] = None,
        callbacks: Optional[PipelineCallbacks] = None,
    ) -> None:
        self._sample_rate = sample_rate
        self._chunk_size = chunk_size
        self._mode = mode
        self._noise_blanker = noise_blanker
        self._audio_write = audio_write
        self._signal_db_setter = signal_db_setter
        self._audio_underruns_getter = audio_underruns_getter
        self._audio_overruns_getter = audio_overruns_getter
        self._cb = callbacks or PipelineCallbacks()

        # Compute baseband rate
        self._baseband_rate = baseband_rate_for(sample_rate)
        logger.info(
            "Baseband rate %d Hz (decimate %dx from %d)",
            self._baseband_rate,
            sample_rate // self._baseband_rate,
            sample_rate,
        )

        # DSP objects
        self._nfm_kwargs = nfm_kwargs or {}
        init_kwargs = (wfm_kwargs or {}) if mode == "WFM" else (
            self._nfm_kwargs if mode == "NFM" else {}
        )
        self._demodulator: Demodulator = make_demodulator(
            mode, self._baseband_rate, AUDIO_RATE,
            **init_kwargs,
        )
        self._decimator = StatefulDecimator(
            factor=sample_rate // self._baseband_rate,
            input_rate=sample_rate,
        )
        self._mixer = Mixer(sample_rate)
        self._spectrum = SpectrumAnalyser(fft_size=fft_size)

        # Software VFO offset (Hz from LO)
        self.demod_offset: float = 0.0

        # Spectrum throttle (~20 Hz update rate)
        chunk_rate = sample_rate / chunk_size
        self._spec_every = max(1, int(round(chunk_rate / 20)))
        self._spec_skip = 0

        # Stereo/RDS tracking
        self._dsp_stereo: Optional[bool] = None
        self._stereo_delay: int = 0
        self._last_rds_station: str = ""

        # Health / diagnostics
        self._health_t = time.monotonic()
        self._health_chunks = 0
        self._prev_au_ur = 0
        self._prev_au_or = 0

        # Track the mode the demodulator was last built for
        self._demod_built_mode: str = mode

        # Retune flag
        self._retune_pending = False

        # WFM kwargs for mode rebuilds
        self._wfm_kwargs = wfm_kwargs or {}

    @property
    def baseband_rate(self) -> int:
        return self._baseband_rate

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def demodulator(self) -> Demodulator:
        return self._demodulator

    def set_mode(
        self,
        mode: str,
        wfm_kwargs: Optional[dict] = None,
        nfm_kwargs: Optional[dict] = None,
    ) -> None:
        """Request a mode change — takes effect on the next process() call."""
        self._mode = mode
        self._wfm_kwargs = wfm_kwargs or {}
        self._nfm_kwargs = nfm_kwargs or {}

    def rebuild_demodulator(
        self,
        wfm_kwargs: Optional[dict] = None,
        nfm_kwargs: Optional[dict] = None,
    ) -> None:
        """Force-rebuild the demodulator with new parameters."""
        if wfm_kwargs is not None:
            self._wfm_kwargs = wfm_kwargs
        if nfm_kwargs is not None:
            self._nfm_kwargs = nfm_kwargs
        kwargs = (
            self._wfm_kwargs if self._mode == "WFM"
            else self._nfm_kwargs if self._mode == "NFM"
            else {}
        )
        self._demodulator = make_demodulator(
            self._mode, self._baseband_rate, AUDIO_RATE, **kwargs,
        )

    def notify_retune(self) -> None:
        """Called when the user retunes — resets stereo/RDS tracking."""
        self._retune_pending = True

    def process(self, iq: np.ndarray) -> None:
        """Process one IQ chunk.  Called from the SDR capture thread."""
        self._health_chunks += 1
        now = time.monotonic()
        if now - self._health_t >= 5.0:
            elapsed = now - self._health_t
            rate = self._health_chunks / elapsed
            au_ur = self._audio_underruns_getter() - self._prev_au_ur
            au_or = self._audio_overruns_getter() - self._prev_au_or
            parts = [f"DSP {rate:.0f} chunks/s"]
            if au_ur:
                parts.append(f"audio underruns {au_ur}")
            if au_or:
                parts.append(f"audio overruns {au_or}")
            logger.info(" | ".join(parts))
            self._health_t = now
            self._health_chunks = 0
            self._prev_au_ur = self._audio_underruns_getter()
            self._prev_au_or = self._audio_overruns_getter()

        # Rebuild demodulator if mode changed
        if self._mode != self._demod_built_mode:
            self._demod_built_mode = self._mode
            kwargs = (
                self._wfm_kwargs if self._mode == "WFM"
                else self._nfm_kwargs if self._mode == "NFM"
                else {}
            )
            self._demodulator = make_demodulator(
                self._mode, self._baseband_rate, AUDIO_RATE, **kwargs,
            )
            self._dsp_stereo = None
            self._stereo_delay = 0

        # Handle retune
        if self._retune_pending:
            self._retune_pending = False
            self._dsp_stereo = None
            chunk_s = self._chunk_size / max(self._sample_rate, 1)
            self._stereo_delay = max(1, int(0.3 / chunk_s))
            self._last_rds_station = ""
            rds = getattr(self._demodulator, "_rds", None)
            if rds is not None:
                rds.reset()

        # DC offset removal
        iq = iq - np.mean(iq)

        # Noise blanker
        iq = self._noise_blanker.process(iq)

        # RF power measurement (dBFS)
        iq_power = float(np.vdot(iq, iq).real) / len(iq)
        self._signal_db_setter(10.0 * np.log10(max(iq_power, 1e-10)))

        # Spectrum analysis (throttled)
        self._spec_skip += 1
        if self._spec_skip >= self._spec_every:
            self._spec_skip = 0
            spec = self._spectrum.process(iq)
            if self._cb.on_spectrum is not None:
                self._cb.on_spectrum(spec)

        # Software VFO mix → decimate → demodulate → audio
        mixed = self._mixer.process(iq, self.demod_offset)
        bb = self._decimator.process(mixed)
        audio = self._demodulator.process(bb)
        self._audio_write(audio)

        # Stereo/RDS tracking (WFM only)
        if self._mode == "WFM":
            stereo = getattr(self._demodulator, "stereo_detected", False)
            if self._stereo_delay > 0:
                self._stereo_delay -= 1
                self._dsp_stereo = stereo
            elif stereo != self._dsp_stereo:
                self._dsp_stereo = stereo
                if self._cb.on_stereo_change is not None:
                    self._cb.on_stereo_change(stereo)

            rds_name = getattr(self._demodulator, "rds_station", "")
            if rds_name and rds_name != self._last_rds_station:
                self._last_rds_station = rds_name
                if self._cb.on_rds_station is not None:
                    self._cb.on_rds_station(rds_name)
