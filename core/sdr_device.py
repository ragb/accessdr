"""core/sdr_device.py — RTL-SDR hardware abstraction and IQ capture thread.

Delegates to a backend strategy class (PyRtlSdrBackend, SoapyBackend,
or DummyBackend) selected at open() time.  See core/sdr_backends.py for
backend implementations and thread-safety notes.
"""

from __future__ import annotations

import logging
import threading
from typing import Callable, List, Optional

import numpy as np

from core.platform_utils import elevate_dsp_priority
from core.sdr_backends import SDRBackend, create_backend, enumerate_devices  # noqa: F401

logger = logging.getLogger(__name__)

CHUNK_SIZE = 65_536  # default; overridden by Settings.sdr_buffer_size


class SDRDevice:
    """RTL-SDR receiver — delegates to the best available backend."""

    def __init__(self, chunk_size: int = CHUNK_SIZE, settings=None) -> None:
        self._backend: Optional[SDRBackend] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._settings = settings
        self.chunk_size: int = chunk_size

        self.centre_freq: int = 98_100_000
        self.sample_rate: int = 2_400_000
        self.gain: float = 30.0
        self.ppm: int = 0
        self.agc_mode: bool = False
        self.offset_tuning: bool = False
        self.tuner_bandwidth: int = 0  # Hz, 0 = auto
        self.direct_sampling: int = 0  # 0 = off, 1 = I-branch, 2 = Q-branch
        self.tuner_dithering: bool = True
        self.bias_tee: bool = False
        self.bias_tee_gpio: int = 0
        self.applied_tuner_bandwidth: int = 0  # actual BW the tuner applied (Hz)

        self.on_samples: Optional[Callable[[np.ndarray], None]] = None
        self.on_error: Optional[Callable[[str], None]] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def open(self, device_index: int = 0) -> bool:
        if self._backend is not None:
            self.close()

        backend = create_backend(self._settings)
        config = dict(
            centre_freq=self.centre_freq,
            sample_rate=self.sample_rate,
            gain=self.gain,
            ppm=self.ppm,
            agc_mode=self.agc_mode,
            offset_tuning=self.offset_tuning,
            tuner_bandwidth=self.tuner_bandwidth,
            direct_sampling=self.direct_sampling,
            tuner_dithering=self.tuner_dithering,
            bias_tee=self.bias_tee,
            bias_tee_gpio=self.bias_tee_gpio,
        )
        if not backend.open(device_index, config):
            if self.on_error:
                self.on_error("SDR open failed")
            return False
        self._backend = backend
        return True

    def close(self) -> None:
        self.stop()
        if self._backend is not None:
            self._backend.close()
            self._backend = None

    # ------------------------------------------------------------------
    # Live configuration — delegated to backend
    # ------------------------------------------------------------------

    def set_frequency(self, freq_hz: int) -> None:
        self.centre_freq = freq_hz
        if self._backend is not None:
            self._backend.set_frequency(freq_hz)

    def set_sample_rate(self, rate: int) -> None:
        self.sample_rate = rate
        if self._backend is not None:
            self._backend.set_sample_rate(rate)

    def set_gain(self, gain_db: float) -> None:
        self.gain = gain_db
        if self._backend is not None:
            self._backend.set_gain(gain_db)

    def set_ppm(self, ppm: int) -> None:
        self.ppm = ppm
        if self._backend is not None:
            self._backend.set_ppm(ppm)

    def set_agc_mode(self, on: bool) -> None:
        self.agc_mode = on
        if self._backend is not None:
            self._backend.set_agc_mode(on, self.gain)

    def set_offset_tuning(self, on: bool) -> None:
        self.offset_tuning = on
        if self._backend is not None:
            self._backend.set_offset_tuning(on)

    def set_tuner_bandwidth(self, bw_hz: int) -> int:
        """Set hardware IF bandwidth. 0 = automatic.

        Returns the actual bandwidth the tuner applied in Hz (it quantises
        to discrete steps), or *bw_hz* if the backend can't report it.
        """
        self.tuner_bandwidth = bw_hz
        applied = bw_hz
        if self._backend is not None:
            applied = self._backend.set_tuner_bandwidth(bw_hz)
        self.applied_tuner_bandwidth = applied
        return applied

    def set_dithering(self, on: bool) -> None:
        """Enable/disable tuner frequency dithering. Off = cleaner narrowband."""
        self.tuner_dithering = on
        if self._backend is not None:
            self._backend.set_dithering(on)

    def set_bias_tee(self, on: bool) -> None:
        self.bias_tee = on
        if self._backend is not None:
            self._backend.set_bias_tee(on, self.bias_tee_gpio)

    def set_direct_sampling(self, mode: int) -> None:
        self.direct_sampling = mode
        if self._backend is not None:
            self._backend.set_direct_sampling(mode)

    def get_valid_gains(self) -> List[float]:
        """Return cached list of valid tuner gain values in dB."""
        if self._backend is not None:
            return self._backend.get_valid_gains()
        return []

    # ------------------------------------------------------------------
    # Streaming
    # ------------------------------------------------------------------

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        if self._backend is not None:
            self._backend.reset_buffer()
        self._thread = threading.Thread(
            target=self._stream_loop, daemon=True, name="SDRCapture"
        )
        self._thread.start()
        elevate_dsp_priority(self._thread)

    def stop(self) -> None:
        self._running = False
        # Proactively cancel the async read from this (main) thread.  We used to
        # rely solely on the capture thread cancelling itself from a sample
        # callback, but if that callback doesn't fire (or the first cancel
        # doesn't take) the thread stays blocked inside rtlsdr_read_async,
        # keeping device 0 claimed so it can't be reopened.  Cross-thread
        # cancel is safe now that pyrtlsdr's close()-on-cancel is neutered
        # (see PyRtlSdrBackend.open) — rtlsdr_cancel_async is just a
        # thread-safe libusb_cancel_transfer.
        if self._backend is not None:
            self._backend.cancel_async()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            if self._thread.is_alive():
                # Cancel didn't take on the first try — retry, then wait longer.
                logger.warning("capture thread slow to stop; retrying cancel")
                if self._backend is not None:
                    self._backend.cancel_async()
                self._thread.join(timeout=3.0)
                if self._thread.is_alive():
                    logger.error("SDR capture thread did not exit; device may "
                                 "stay busy until replug")
            self._thread = None

    def pause(self) -> None:
        """Stop the capture thread. Safe for later resume via start()."""
        self.stop()

    def _stream_loop(self) -> None:
        if self._backend is not None:
            self._backend.stream_loop(
                self.chunk_size,
                lambda: self._running,
                self.on_samples,
                self.on_error,
            )
