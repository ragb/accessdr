"""ui/radio_controller.py — Radio lifecycle management.

Coordinates SDR device, DSP pipeline, and audio output start/stop/pause.
Owns the SDRDevice and DSPPipeline; takes AudioOutput and NoiseBlanker
as dependencies.
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

from config.modes import AUDIO_RATE
from core.audio import AudioOutput
from core.dsp.noise_blanker import NoiseBlanker
from core.dsp.pipeline import DSPPipeline, PipelineCallbacks
from core.sdr_device import SDRDevice

logger = logging.getLogger(__name__)


class RadioController:
    """Manages SDR device, DSP pipeline, and radio start/stop/pause."""

    def __init__(
        self,
        settings,
        audio: AudioOutput,
        noise_blanker: NoiseBlanker,
    ) -> None:
        self._settings = settings
        self._audio = audio
        self._noise_blanker = noise_blanker
        self._sdr = SDRDevice(chunk_size=settings.sdr_buffer_size, settings=settings)
        self._pipeline: Optional[DSPPipeline] = None
        self._running = False
        self._paused = False

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def running(self) -> bool:
        return self._running

    @property
    def paused(self) -> bool:
        return self._paused

    @property
    def pipeline(self) -> Optional[DSPPipeline]:
        return self._pipeline

    @property
    def chunk_size(self) -> int:
        return self._sdr.chunk_size

    @chunk_size.setter
    def chunk_size(self, value: int) -> None:
        self._sdr.chunk_size = value

    @property
    def sdr(self) -> SDRDevice:
        return self._sdr

    def set_error_callback(self, cb: Callable[[str], None]) -> None:
        self._sdr.on_error = cb

    def get_valid_gains(self) -> list:
        return self._sdr.get_valid_gains()

    # ------------------------------------------------------------------
    # Radio lifecycle
    # ------------------------------------------------------------------

    def start(self, callbacks: PipelineCallbacks) -> bool:
        """Open SDR, build pipeline, start capture and audio.

        Returns True on success, False if SDR couldn't be opened.
        """
        if not self._sdr.open():
            return False

        self._audio.audio_underruns = 0
        self._audio.audio_overruns = 0
        self._noise_blanker.threshold = self._settings.noise_blanker_threshold
        self._noise_blanker.enabled = self._settings.noise_blanker_enabled

        mode = self._settings.mode
        wfm_kw = self.wfm_kwargs() if mode == "WFM" else {}
        nfm_kw = self.nfm_kwargs() if mode == "NFM" else {}
        self._pipeline = DSPPipeline(
            sample_rate=self._settings.sample_rate,
            chunk_size=self._sdr.chunk_size,
            mode=mode,
            noise_blanker=self._noise_blanker,
            audio_write=self._audio.write,
            signal_db_setter=lambda db: setattr(self._audio, "signal_db", db),
            audio_underruns_getter=lambda: self._audio.audio_underruns,
            audio_overruns_getter=lambda: self._audio.audio_overruns,
            fft_size=self._settings.fft_size,
            wfm_kwargs=wfm_kw,
            nfm_kwargs=nfm_kw,
            callbacks=callbacks,
        )

        # Configure SDR hardware. Direct sampling first: it changes the
        # signal path, so the frequency below must be set in the right mode.
        self._sdr.set_direct_sampling(self._settings.direct_sampling)
        self._sdr.set_frequency(self._hw_freq(self._settings.frequency))
        self._sdr.set_sample_rate(self._settings.sample_rate)
        self._sdr.set_gain(self._settings.gain)
        self._sdr.set_ppm(self._settings.ppm)
        self._sdr.set_agc_mode(self._settings.agc_mode)
        self._sdr.set_offset_tuning(self._settings.offset_tuning)
        if self._settings.tuner_bandwidth != 0:
            self._sdr.set_tuner_bandwidth(self._settings.tuner_bandwidth)
        else:
            self._sdr.set_tuner_bandwidth(0)  # auto
        self._sdr.set_dithering(self._settings.tuner_dithering)
        self._sdr.set_bias_tee(self._settings.bias_tee)

        self._sdr.on_samples = self._pipeline.process
        self._sdr.start()
        self._audio.start()

        self._running = True
        self._paused = False
        return True

    def stop(self) -> None:
        """Stop capture, close SDR, stop audio, destroy pipeline."""
        self._running = False
        self._paused = False
        self._sdr.stop()
        self._sdr.on_samples = None
        self._sdr.close()
        self._audio.stop()
        self._pipeline = None

    def pause(self) -> bool:
        """Pause capture and audio.

        Returns True if paused, False if radio is already stopped.
        """
        if not self._running and not self._paused:
            return False
        self._sdr.pause()
        self._audio.pause()
        self._running = False
        self._paused = True
        return True

    def resume(self) -> None:
        """Resume capture and audio from paused state."""
        self._sdr.start()
        self._audio.resume()
        self._running = True
        self._paused = False

    # ------------------------------------------------------------------
    # Hardware / pipeline control
    # ------------------------------------------------------------------

    def _hw_freq(self, freq_hz: int) -> int:
        """Map a real (display) frequency to the hardware LO frequency.

        With an upconverter, the dongle tunes ``freq + upconverter_offset``
        while the rest of the app keeps the real HF frequency.
        """
        return freq_hz + self._settings.upconverter_offset

    def set_frequency(self, freq_hz: int) -> None:
        """Tune SDR (via upconverter offset) and notify pipeline of retune."""
        self._sdr.set_frequency(self._hw_freq(freq_hz))
        if self._pipeline is not None:
            self._pipeline.notify_retune()

    def set_mode(
        self,
        mode: str,
        wfm_kwargs: Optional[dict] = None,
        nfm_kwargs: Optional[dict] = None,
    ) -> None:
        """Change demod mode on pipeline and set tuner BW to auto."""
        if self._pipeline is not None:
            self._pipeline.set_mode(mode, wfm_kwargs or {}, nfm_kwargs or {})
        if self._running:
            self._sdr.set_tuner_bandwidth(0)

    def apply_rf_settings(self) -> bool:
        """Apply RF settings to SDR hardware.

        Returns True if a full restart is required (buffer size or direct
        sampling changed — both alter the capture/signal path).
        """
        s = self._settings
        need_restart = self._running and (
            self._sdr.chunk_size != s.sdr_buffer_size
            or self._sdr.direct_sampling != s.direct_sampling
        )
        self._sdr.chunk_size = s.sdr_buffer_size
        if not need_restart and self._running:
            self._sdr.set_gain(s.gain)
            self._sdr.set_ppm(s.ppm)
            self._sdr.set_sample_rate(s.sample_rate)
            self._sdr.set_agc_mode(s.agc_mode)
            self._sdr.set_offset_tuning(s.offset_tuning)
            self._sdr.set_tuner_bandwidth(s.tuner_bandwidth)
            self._sdr.set_dithering(s.tuner_dithering)
            self._sdr.set_bias_tee(s.bias_tee)
            # Re-tune so a changed upconverter offset takes effect now.
            self._sdr.set_frequency(self._hw_freq(s.frequency))
        return need_restart

    @property
    def applied_tuner_bandwidth(self) -> int:
        """Actual IF bandwidth (Hz) the tuner applied for the last request."""
        return self._sdr.applied_tuner_bandwidth

    def rebuild_wfm(self) -> None:
        """Rebuild WFM demodulator from current settings."""
        if self._running and self._settings.mode == "WFM" and self._pipeline:
            self._pipeline.rebuild_demodulator(wfm_kwargs=self.wfm_kwargs())

    def rebuild_nfm(self) -> None:
        """Rebuild NFM demodulator from current settings."""
        if self._running and self._settings.mode == "NFM" and self._pipeline:
            self._pipeline.rebuild_demodulator(nfm_kwargs=self.nfm_kwargs())

    def wfm_kwargs(self) -> dict:
        """Build WFM demodulator kwargs from current settings."""
        return dict(
            deemphasis=self._settings.wfm_deemphasis,
            stereo_mode=self._settings.wfm_stereo_mode,
            hiblend_enabled=self._settings.wfm_hiblend_enabled,
            rds_enabled=self._settings.wfm_rds_enabled,
        )

    def nfm_kwargs(self) -> dict:
        """Build NFM demodulator kwargs from current settings."""
        return dict(
            deviation=self._settings.nfm_deviation,
            ctcss_notch=self._settings.nfm_ctcss_notch,
        )
