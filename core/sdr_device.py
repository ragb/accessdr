"""
core/sdr_device.py — RTL-SDR hardware abstraction and IQ capture thread.

Uses pyrtlsdr (direct RTL2832U) as the primary backend, with SoapySDR and
a synthetic noise generator as fallbacks.

Thread-safety
-------------
librtlsdr's rtlsdr_set_center_freq / rtlsdr_set_gain etc. ARE documented
as safe to call while read_samples blocks in another thread.  We call them
via the raw C handle (_librtlsdr.rtlsdr_set_center_freq) rather than the
Python wrapper so there is no GIL interaction with the blocking read.
"""

from __future__ import annotations

import logging
import queue
import threading
from typing import Callable, List, Optional

import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Backend detection — pyrtlsdr
# ---------------------------------------------------------------------------
try:
    # Use the base (non-async) class explicitly — RtlSdrAio breaks sync reads
    from rtlsdr.rtlsdr import RtlSdr as _RtlSdrBase
    from rtlsdr.librtlsdr import librtlsdr as _librtlsdr
    _PYRTLSDR_AVAILABLE = True
except Exception as _exc:
    _PYRTLSDR_AVAILABLE = False
    logger.warning("pyrtlsdr not available: %s", _exc)

# ---------------------------------------------------------------------------
# Backend detection — SoapySDR (fallback)
# ---------------------------------------------------------------------------
try:
    import SoapySDR as _SoapySDR
    from SoapySDR import SOAPY_SDR_RX as _SOAPY_SDR_RX, SOAPY_SDR_CF32 as _SOAPY_SDR_CF32
    _SOAPY_AVAILABLE = True
except ImportError:
    _SOAPY_AVAILABLE = False

CHUNK_SIZE = 16_384


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def enumerate_devices() -> List[dict]:
    if _PYRTLSDR_AVAILABLE:
        try:
            count = _librtlsdr.rtlsdr_get_device_count()
            devs = []
            for i in range(count):
                raw = _librtlsdr.rtlsdr_get_device_name(i)
                name = raw.decode() if isinstance(raw, bytes) else str(raw)
                devs.append({"index": i, "label": f"[{i}] {name}"})
            return devs
        except Exception as exc:   # noqa: BLE001
            logger.error("enumerate failed: %s", exc)
    if _SOAPY_AVAILABLE:
        try:
            return [dict(r) for r in _SoapySDR.Device.enumerate()]
        except Exception as exc:   # noqa: BLE001
            logger.error("SoapySDR enumerate failed: %s", exc)
    return []


# ---------------------------------------------------------------------------
# SDRDevice
# ---------------------------------------------------------------------------

class SDRDevice:
    """RTL-SDR receiver using pyrtlsdr (preferred) or SoapySDR."""

    def __init__(self) -> None:
        self._rtl: Optional[_RtlSdrBase] = None
        self._dev_handle = None          # raw C void* from librtlsdr
        self._soapy = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self.iq_queue: queue.Queue = queue.Queue(maxsize=64)

        self.centre_freq: int = 98_100_000
        self.sample_rate: int = 2_400_000
        self.gain: float = 30.0
        self.ppm: int = 0

        self.on_error: Optional[Callable[[str], None]] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def open(self, device_index: int = 0) -> bool:
        if _PYRTLSDR_AVAILABLE:
            try:
                self._rtl = _RtlSdrBase(device_index)
                self._dev_handle = self._rtl.dev_p   # raw C handle for thread-safe calls
            except Exception as exc:   # noqa: BLE001
                logger.error("pyrtlsdr open failed: %s", exc)
                if self.on_error:
                    self.on_error(f"RTL-SDR open failed: {exc}")
                return False

            try:
                self._rtl.sample_rate = self.sample_rate
            except Exception as exc:   # noqa: BLE001
                logger.warning("set sample_rate failed: %s", exc)

            # Set frequency via C function (avoids wrapper quirks)
            try:
                _librtlsdr.rtlsdr_set_center_freq(self._dev_handle, self.centre_freq)
            except Exception as exc:   # noqa: BLE001
                logger.warning("set center_freq failed: %s", exc)

            # Skip PPM=0 — causes LIBUSB_ERROR_INVALID_PARAM on some dongles
            if self.ppm != 0:
                try:
                    _librtlsdr.rtlsdr_set_freq_correction(self._dev_handle, self.ppm)
                except Exception as exc:   # noqa: BLE001
                    logger.warning("set ppm failed: %s", exc)

            try:
                _librtlsdr.rtlsdr_set_tuner_gain_mode(self._dev_handle, 1)   # manual
                _librtlsdr.rtlsdr_set_tuner_gain(self._dev_handle, int(self.gain * 10))
            except Exception as exc:   # noqa: BLE001
                logger.warning("set gain failed: %s", exc)

            logger.info("Opened RTL-SDR device %d", device_index)
            return True

        if _SOAPY_AVAILABLE:
            try:
                self._soapy = _SoapySDR.Device({"driver": "rtlsdr"})
                self._soapy.setFrequency(_SOAPY_SDR_RX, 0, float(self.centre_freq))
                self._soapy.setSampleRate(_SOAPY_SDR_RX, 0, float(self.sample_rate))
                self._soapy.setGain(_SOAPY_SDR_RX, 0, self.gain)
                return True
            except Exception as exc:   # noqa: BLE001
                logger.error("SoapySDR open failed: %s", exc)
                if self.on_error:
                    self.on_error(f"SoapySDR open failed: {exc}")
                return False

        logger.info("No SDR backend — demo mode")
        return True

    def close(self) -> None:
        self.stop()
        if self._rtl is not None:
            try:
                self._rtl.close()
            except Exception:          # noqa: BLE001
                pass
            self._rtl = None
            self._dev_handle = None
        self._soapy = None

    # ------------------------------------------------------------------
    # Live configuration — all use the raw C handle so they're safe to
    # call from the UI thread while read_samples blocks in the DSP thread
    # ------------------------------------------------------------------

    def set_frequency(self, freq_hz: int) -> None:
        self.centre_freq = freq_hz
        if self._dev_handle is not None:
            try:
                _librtlsdr.rtlsdr_set_center_freq(self._dev_handle, freq_hz)
            except Exception as exc:   # noqa: BLE001
                logger.warning("set_frequency failed: %s", exc)
        elif self._soapy is not None:
            try:
                self._soapy.setFrequency(_SOAPY_SDR_RX, 0, float(freq_hz))
            except Exception as exc:   # noqa: BLE001
                logger.warning("setFrequency failed: %s", exc)

    def set_sample_rate(self, rate: int) -> None:
        self.sample_rate = rate
        if self._rtl is not None:
            try:
                self._rtl.sample_rate = rate
            except Exception as exc:   # noqa: BLE001
                logger.warning("set_sample_rate failed: %s", exc)
        elif self._soapy is not None:
            try:
                self._soapy.setSampleRate(_SOAPY_SDR_RX, 0, float(rate))
            except Exception as exc:   # noqa: BLE001
                logger.warning("setSampleRate failed: %s", exc)

    def set_gain(self, gain_db: float) -> None:
        self.gain = gain_db
        if self._dev_handle is not None:
            try:
                _librtlsdr.rtlsdr_set_tuner_gain(self._dev_handle, int(gain_db * 10))
            except Exception as exc:   # noqa: BLE001
                logger.warning("set_gain failed: %s", exc)
        elif self._soapy is not None:
            try:
                self._soapy.setGain(_SOAPY_SDR_RX, 0, gain_db)
            except Exception as exc:   # noqa: BLE001
                logger.warning("setGain failed: %s", exc)

    def set_ppm(self, ppm: int) -> None:
        self.ppm = ppm
        if self._dev_handle is not None and ppm != 0:
            try:
                _librtlsdr.rtlsdr_set_freq_correction(self._dev_handle, ppm)
            except Exception as exc:   # noqa: BLE001
                logger.warning("set_ppm failed: %s", exc)
        elif self._soapy is not None:
            try:
                self._soapy.setFrequencyCorrection(_SOAPY_SDR_RX, 0, float(ppm))
            except Exception as exc:   # noqa: BLE001
                logger.warning("setFrequencyCorrection failed: %s", exc)

    # ------------------------------------------------------------------
    # Streaming
    # ------------------------------------------------------------------

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._stream_loop, daemon=True, name="SDRCapture"
        )
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._rtl is not None:
            try:
                self._rtl.cancel_read_async()
            except Exception:          # noqa: BLE001
                pass
        if self._thread is not None:
            self._thread.join(timeout=3.0)
            self._thread = None

    def _stream_loop(self) -> None:
        if self._rtl is not None:
            self._pyrtlsdr_loop()
        elif self._soapy is not None:
            self._soapy_loop()
        else:
            self._dummy_loop()

    def _pyrtlsdr_loop(self) -> None:
        try:
            while self._running:
                samples = self._rtl.read_samples(CHUNK_SIZE)
                chunk = np.asarray(samples, dtype=np.complex64)
                try:
                    self.iq_queue.put_nowait(chunk)
                except queue.Full:
                    pass
        except Exception as exc:       # noqa: BLE001
            if self._running:
                logger.error("pyrtlsdr stream error: %s", exc)
                if self.on_error:
                    self.on_error(f"Stream error: {exc}")

    def _soapy_loop(self) -> None:
        try:
            stream = self._soapy.setupStream(_SOAPY_SDR_RX, _SOAPY_SDR_CF32)
            self._soapy.activateStream(stream)
            buf = np.zeros(CHUNK_SIZE, dtype=np.complex64)
            while self._running:
                sr = self._soapy.readStream(stream, [buf], CHUNK_SIZE, timeoutUs=100_000)
                if sr.ret > 0:
                    try:
                        self.iq_queue.put_nowait(buf[: sr.ret].copy())
                    except queue.Full:
                        pass
            self._soapy.deactivateStream(stream)
            self._soapy.closeStream(stream)
        except Exception as exc:       # noqa: BLE001
            if self._running:
                logger.error("SoapySDR stream error: %s", exc)
                if self.on_error:
                    self.on_error(f"Stream error: {exc}")

    def _dummy_loop(self) -> None:
        import time
        rng = np.random.default_rng()
        chunk_dur = CHUNK_SIZE / max(self.sample_rate, 1)
        while self._running:
            chunk = (
                rng.standard_normal(CHUNK_SIZE).astype(np.float32)
                + 1j * rng.standard_normal(CHUNK_SIZE).astype(np.float32)
            ).astype(np.complex64) * 0.01
            try:
                self.iq_queue.put_nowait(chunk)
            except queue.Full:
                pass
            time.sleep(chunk_dur)
