"""core/sdr_backends.py — SDR hardware backend strategy classes.

Each backend encapsulates one SDR library (pyrtlsdr, SoapySDR) or a
synthetic noise source (demo mode).  SDRDevice selects the first
available backend and delegates all hardware calls to it.

Thread-safety
-------------
For pyrtlsdr, live tuning calls use the raw C handle rather than
pyrtlsdr's Python wrappers because the wrappers call self.close() on
any libusb error — which would destroy the USB handle from the UI
thread while the capture thread is still reading.  The raw C functions
are safe to call concurrently with rtlsdr_read_async.
"""

from __future__ import annotations

import ctypes
import logging
from abc import ABC, abstractmethod
from typing import Callable, List, Optional

import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Backend detection — pyrtlsdr
# ---------------------------------------------------------------------------
try:
    from rtlsdr.rtlsdr import RtlSdr as _RtlSdrBase
    from rtlsdr.librtlsdr import librtlsdr as _librtlsdr
    _PYRTLSDR_AVAILABLE = True
except Exception as _exc:
    _PYRTLSDR_AVAILABLE = False
    logger.warning("pyrtlsdr not available: %s", _exc)

# ---------------------------------------------------------------------------
# Backend detection — SoapySDR
# ---------------------------------------------------------------------------
try:
    import SoapySDR as _SoapySDR
    from SoapySDR import SOAPY_SDR_RX as _SOAPY_SDR_RX, SOAPY_SDR_CF32 as _SOAPY_SDR_CF32
    _SOAPY_AVAILABLE = True
except ImportError:
    _SOAPY_AVAILABLE = False


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------

class SDRBackend(ABC):
    """Abstract SDR backend — one per hardware library."""

    @abstractmethod
    def open(self, device_index: int, config: dict) -> bool:
        """Open the device. *config* contains centre_freq, sample_rate, gain, ppm, etc."""

    @abstractmethod
    def close(self) -> None: ...

    @abstractmethod
    def stream_loop(
        self,
        chunk_size: int,
        running: Callable[[], bool],
        on_samples: Optional[Callable[[np.ndarray], None]],
        on_error: Optional[Callable[[str], None]],
    ) -> None:
        """Blocking capture loop — runs in the capture thread."""

    def set_frequency(self, freq_hz: int) -> None: ...
    def set_sample_rate(self, rate: int) -> None: ...
    def set_gain(self, gain_db: float) -> None: ...
    def set_ppm(self, ppm: int) -> None: ...
    def set_agc_mode(self, on: bool, gain_db: float) -> None: ...
    def set_offset_tuning(self, on: bool) -> None: ...
    def set_tuner_bandwidth(self, bw_hz: int) -> None: ...
    def set_bias_tee(self, on: bool) -> None: ...
    def cancel_async(self) -> None:
        """Signal an async capture loop to stop (no-op for most backends)."""

    def reset_buffer(self) -> None:
        """Reset internal buffers before starting a new capture session."""

    def get_valid_gains(self) -> List[float]:
        return []


# ---------------------------------------------------------------------------
# pyrtlsdr backend
# ---------------------------------------------------------------------------

class PyRtlSdrBackend(SDRBackend):
    """Backend using pyrtlsdr (direct RTL2832U via librtlsdr)."""

    def __init__(self) -> None:
        self._rtl: Optional[_RtlSdrBase] = None
        self._dev_handle = None  # raw C void* for thread-safe calls
        self._capture_alive: bool = False

    def open(self, device_index: int, config: dict) -> bool:
        try:
            self._rtl = _RtlSdrBase(device_index)
            self._dev_handle = self._rtl.dev_p
        except Exception as exc:   # noqa: BLE001
            logger.error("pyrtlsdr open failed: %s", exc)
            return False

        # One-time init — no concurrent reader yet, pyrtlsdr wrappers safe.
        try:
            self._rtl.sample_rate = config.get("sample_rate", 2_400_000)
        except Exception as exc:   # noqa: BLE001
            logger.warning("set sample_rate failed: %s", exc)
        try:
            self._rtl.center_freq = config.get("centre_freq", 98_100_000)
        except Exception as exc:   # noqa: BLE001
            logger.warning("set center_freq failed: %s", exc)
        ppm = config.get("ppm", 0)
        if ppm != 0:
            try:
                self._rtl.freq_correction = ppm
            except Exception as exc:   # noqa: BLE001
                logger.warning("set ppm failed: %s", exc)
        try:
            self._rtl.gain = config.get("gain", 30.0)
        except Exception as exc:   # noqa: BLE001
            logger.warning("set gain failed: %s", exc)

        self._register_extra_prototypes()

        # Apply optional hardware settings via raw C
        self.set_agc_mode(config.get("agc_mode", False), config.get("gain", 30.0))
        self.set_offset_tuning(config.get("offset_tuning", False))
        self.set_tuner_bandwidth(config.get("tuner_bandwidth", 0))
        self.set_bias_tee(config.get("bias_tee", False))

        logger.info("Opened RTL-SDR device %d", device_index)
        return True

    def close(self) -> None:
        if self._rtl is not None:
            if self._capture_alive:
                logger.error(
                    "close() called while async capture still alive — "
                    "leaking USB handle to avoid BSOD"
                )
                self._rtl = None
                self._dev_handle = None
                return
            try:
                self._rtl.close()
            except Exception:   # noqa: BLE001
                pass
            self._rtl = None
            self._dev_handle = None

    def cancel_async(self) -> None:
        if self._dev_handle is not None:
            try:
                # Set pyrtlsdr's flag first so its internal callback checker
                # skips any trailing callbacks and read_bytes_async won't call
                # self.close() on a negative return code path.
                if self._rtl is not None:
                    self._rtl.read_async_canceling = True
                _librtlsdr.rtlsdr_cancel_async(self._dev_handle)
            except Exception as exc:   # noqa: BLE001
                logger.warning("cancel_async failed: %s", exc)

    def reset_buffer(self) -> None:
        if self._dev_handle is not None:
            try:
                _librtlsdr.rtlsdr_reset_buffer(self._dev_handle)
            except Exception as exc:   # noqa: BLE001
                logger.warning("reset_buffer failed: %s", exc)

    def stream_loop(self, chunk_size, running, on_samples, on_error):
        def _on_samples(samples, rtlsdr_obj):
            if not running():
                self.cancel_async()
                return
            chunk = np.asarray(samples, dtype=np.complex64)
            if on_samples is not None:
                on_samples(chunk)

        self._capture_alive = True
        try:
            self._rtl.read_samples_async(_on_samples, num_samples=chunk_size)
        except Exception as exc:   # noqa: BLE001
            if running():
                logger.error("pyrtlsdr async read error: %s", exc)
                if on_error:
                    on_error(f"Stream error: {exc}")
        finally:
            self._capture_alive = False

    # -- Live setters (raw C — safe during concurrent reads) --

    def set_frequency(self, freq_hz: int) -> None:
        if self._dev_handle is not None:
            try:
                _librtlsdr.rtlsdr_set_center_freq(self._dev_handle, freq_hz)
            except Exception as exc:   # noqa: BLE001
                logger.warning("set_frequency failed: %s", exc)

    def set_sample_rate(self, rate: int) -> None:
        if self._dev_handle is not None:
            try:
                _librtlsdr.rtlsdr_set_sample_rate(self._dev_handle, rate)
            except Exception as exc:   # noqa: BLE001
                logger.warning("set_sample_rate failed: %s", exc)

    def set_gain(self, gain_db: float) -> None:
        if self._dev_handle is not None:
            try:
                _librtlsdr.rtlsdr_set_tuner_gain(self._dev_handle, int(gain_db * 10))
            except Exception as exc:   # noqa: BLE001
                logger.warning("set_gain failed: %s", exc)

    def set_ppm(self, ppm: int) -> None:
        if self._dev_handle is not None and ppm != 0:
            try:
                _librtlsdr.rtlsdr_set_freq_correction(self._dev_handle, ppm)
            except Exception as exc:   # noqa: BLE001
                logger.warning("set_ppm failed: %s", exc)

    def set_agc_mode(self, on: bool, gain_db: float = 30.0) -> None:
        if self._dev_handle is not None:
            try:
                _librtlsdr.rtlsdr_set_agc_mode(self._dev_handle, int(on))
                _librtlsdr.rtlsdr_set_tuner_gain_mode(self._dev_handle, 0 if on else 1)
                if not on:
                    _librtlsdr.rtlsdr_set_tuner_gain(
                        self._dev_handle, int(gain_db * 10)
                    )
            except Exception as exc:   # noqa: BLE001
                logger.warning("set_agc_mode failed: %s", exc)

    def set_offset_tuning(self, on: bool) -> None:
        if self._dev_handle is not None:
            try:
                _librtlsdr.rtlsdr_set_offset_tuning(self._dev_handle, int(on))
            except Exception as exc:   # noqa: BLE001
                logger.warning("set_offset_tuning failed: %s", exc)

    def set_tuner_bandwidth(self, bw_hz: int) -> None:
        if self._dev_handle is not None:
            try:
                _librtlsdr.rtlsdr_set_tuner_bandwidth(self._dev_handle, bw_hz)
            except Exception as exc:   # noqa: BLE001
                logger.warning("set_tuner_bandwidth failed: %s", exc)

    def set_bias_tee(self, on: bool) -> None:
        if self._dev_handle is not None:
            try:
                _librtlsdr.rtlsdr_set_bias_tee(self._dev_handle, int(on))
            except Exception as exc:   # noqa: BLE001
                logger.warning("set_bias_tee failed: %s", exc)

    def get_valid_gains(self) -> List[float]:
        if self._rtl is not None:
            try:
                return list(self._rtl.valid_gains_db)
            except Exception:   # noqa: BLE001
                pass
        return []

    # -- Internal --

    def _register_extra_prototypes(self) -> None:
        lib = _librtlsdr
        try:
            if not hasattr(lib.rtlsdr_set_offset_tuning, "argtypes"):
                lib.rtlsdr_set_offset_tuning.argtypes = [ctypes.c_void_p, ctypes.c_int]
                lib.rtlsdr_set_offset_tuning.restype = ctypes.c_int
        except Exception:   # noqa: BLE001
            pass
        try:
            if not hasattr(lib.rtlsdr_set_tuner_bandwidth, "argtypes"):
                lib.rtlsdr_set_tuner_bandwidth.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
                lib.rtlsdr_set_tuner_bandwidth.restype = ctypes.c_int
        except Exception:   # noqa: BLE001
            pass
        try:
            if not hasattr(lib.rtlsdr_reset_buffer, "argtypes"):
                lib.rtlsdr_reset_buffer.argtypes = [ctypes.c_void_p]
                lib.rtlsdr_reset_buffer.restype = ctypes.c_int
        except Exception:   # noqa: BLE001
            pass
        try:
            if not hasattr(lib.rtlsdr_cancel_async, "argtypes"):
                lib.rtlsdr_cancel_async.argtypes = [ctypes.c_void_p]
                lib.rtlsdr_cancel_async.restype = ctypes.c_int
        except Exception:   # noqa: BLE001
            pass
        try:
            if not hasattr(lib.rtlsdr_set_bias_tee, "argtypes"):
                lib.rtlsdr_set_bias_tee.argtypes = [ctypes.c_void_p, ctypes.c_int]
                lib.rtlsdr_set_bias_tee.restype = ctypes.c_int
        except Exception:   # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# SoapySDR backend
# ---------------------------------------------------------------------------

class SoapyBackend(SDRBackend):
    """Backend using SoapySDR."""

    def __init__(self) -> None:
        self._soapy = None

    def open(self, device_index: int, config: dict) -> bool:
        try:
            self._soapy = _SoapySDR.Device({"driver": "rtlsdr"})
            self._soapy.setFrequency(_SOAPY_SDR_RX, 0, float(config.get("centre_freq", 98_100_000)))
            self._soapy.setSampleRate(_SOAPY_SDR_RX, 0, float(config.get("sample_rate", 2_400_000)))
            self._soapy.setGain(_SOAPY_SDR_RX, 0, config.get("gain", 30.0))
            return True
        except Exception as exc:   # noqa: BLE001
            logger.error("SoapySDR open failed: %s", exc)
            return False

    def close(self) -> None:
        self._soapy = None

    def stream_loop(self, chunk_size, running, on_samples, on_error):
        try:
            stream = self._soapy.setupStream(_SOAPY_SDR_RX, _SOAPY_SDR_CF32)
            self._soapy.activateStream(stream)
            buf = np.zeros(chunk_size, dtype=np.complex64)
            while running():
                sr = self._soapy.readStream(stream, [buf], chunk_size, timeoutUs=100_000)
                if sr.ret > 0 and on_samples is not None:
                    on_samples(buf[: sr.ret].copy())
            self._soapy.deactivateStream(stream)
            self._soapy.closeStream(stream)
        except Exception as exc:   # noqa: BLE001
            if running():
                logger.error("SoapySDR stream error: %s", exc)
                if on_error:
                    on_error(f"Stream error: {exc}")

    def set_frequency(self, freq_hz: int) -> None:
        if self._soapy is not None:
            try:
                self._soapy.setFrequency(_SOAPY_SDR_RX, 0, float(freq_hz))
            except Exception as exc:   # noqa: BLE001
                logger.warning("setFrequency failed: %s", exc)

    def set_sample_rate(self, rate: int) -> None:
        if self._soapy is not None:
            try:
                self._soapy.setSampleRate(_SOAPY_SDR_RX, 0, float(rate))
            except Exception as exc:   # noqa: BLE001
                logger.warning("setSampleRate failed: %s", exc)

    def set_gain(self, gain_db: float) -> None:
        if self._soapy is not None:
            try:
                self._soapy.setGain(_SOAPY_SDR_RX, 0, gain_db)
            except Exception as exc:   # noqa: BLE001
                logger.warning("setGain failed: %s", exc)

    def set_ppm(self, ppm: int) -> None:
        if self._soapy is not None:
            try:
                self._soapy.setFrequencyCorrection(_SOAPY_SDR_RX, 0, float(ppm))
            except Exception as exc:   # noqa: BLE001
                logger.warning("setFrequencyCorrection failed: %s", exc)


# ---------------------------------------------------------------------------
# Demo backend (no hardware)
# ---------------------------------------------------------------------------

class DummyBackend(SDRBackend):
    """Synthetic noise source for demo mode."""

    def __init__(self) -> None:
        self._sample_rate: int = 2_400_000

    def open(self, device_index: int, config: dict) -> bool:
        self._sample_rate = config.get("sample_rate", 2_400_000)
        logger.info("No SDR backend — demo mode")
        return True

    def close(self) -> None:
        pass

    def stream_loop(self, chunk_size, running, on_samples, on_error):
        import time
        rng = np.random.default_rng()
        chunk_dur = chunk_size / max(self._sample_rate, 1)
        while running():
            chunk = (
                rng.standard_normal(chunk_size).astype(np.float32)
                + 1j * rng.standard_normal(chunk_size).astype(np.float32)
            ).astype(np.complex64) * 0.01
            if on_samples is not None:
                on_samples(chunk)
            time.sleep(chunk_dur)


# ---------------------------------------------------------------------------
# Factory + device enumeration
# ---------------------------------------------------------------------------

def enumerate_devices() -> List[dict]:
    """Return a list of detected SDR devices."""
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


def create_backend() -> SDRBackend:
    """Return the best available backend."""
    if _PYRTLSDR_AVAILABLE:
        return PyRtlSdrBackend()
    if _SOAPY_AVAILABLE:
        return SoapyBackend()
    return DummyBackend()
