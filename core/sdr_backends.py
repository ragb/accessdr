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
import socket
import struct
import threading
from abc import ABC, abstractmethod
from typing import Callable, List, Optional

import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Backend detection — pyrtlsdr
# ---------------------------------------------------------------------------
# pyrtlsdr >= 0.4.0 loads librtlsdr with a bare CDLL('rtlsdr.dll'), relying on
# the Windows DLL search path (it no longer adds the package dir itself).
# Register the directory holding the bundled DLLs (for the pthreadVC2 /
# msvcr100 dependencies) and pre-load rtlsdr.dll by absolute path so the
# later bare-name import resolves to the already-loaded module — no patching
# of the installed package required.
try:
    import os as _os
    import sys as _sys
    from config.paths import bundle_dir as _bundle_dir
    _dll_dir = _bundle_dir()
    if _sys.platform == "win32":
        if hasattr(_os, "add_dll_directory") and _os.path.isdir(_dll_dir):
            _os.add_dll_directory(_dll_dir)
        _rtl_dll = _os.path.join(_dll_dir, "rtlsdr.dll")
        if _os.path.isfile(_rtl_dll):
            ctypes.CDLL(_rtl_dll)
except Exception as _exc:   # noqa: BLE001
    logger.debug("could not pre-load rtlsdr.dll: %s", _exc)

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

    def set_tuner_bandwidth(self, bw_hz: int) -> int:
        """Set IF bandwidth (0 = auto). Return the actual applied BW in Hz."""
        return bw_hz

    def set_dithering(self, on: bool) -> None:
        """Enable/disable tuner frequency dithering (no-op for most backends)."""

    def set_bias_tee(self, on: bool) -> None: ...
    def set_direct_sampling(self, mode: int) -> None:
        """Set direct-sampling mode: 0 = off, 1 = I-branch, 2 = Q-branch.

        RTL2832U-specific (for HF without an upconverter); a no-op on
        backends/devices that tune HF natively.
        """
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
        self.set_dithering(config.get("tuner_dithering", True))
        self.set_bias_tee(config.get("bias_tee", False))
        self.set_direct_sampling(config.get("direct_sampling", 0))

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

    def set_tuner_bandwidth(self, bw_hz: int) -> int:
        if self._dev_handle is None:
            return bw_hz
        try:
            getfn = getattr(_librtlsdr, "rtlsdr_set_and_get_tuner_bandwidth", None)
            if getfn is not None:
                applied = ctypes.c_uint32(0)
                getfn(self._dev_handle, bw_hz, ctypes.byref(applied), 1)
                return int(applied.value) or bw_hz
            _librtlsdr.rtlsdr_set_tuner_bandwidth(self._dev_handle, bw_hz)
        except Exception as exc:   # noqa: BLE001
            logger.warning("set_tuner_bandwidth failed: %s", exc)
        return bw_hz

    def set_dithering(self, on: bool) -> None:
        if self._dev_handle is not None:
            fn = getattr(_librtlsdr, "rtlsdr_set_dithering", None)
            if fn is None:
                return
            try:
                fn(self._dev_handle, int(on))
            except Exception as exc:   # noqa: BLE001
                logger.warning("set_dithering failed: %s", exc)

    def set_bias_tee(self, on: bool) -> None:
        if self._dev_handle is not None:
            try:
                _librtlsdr.rtlsdr_set_bias_tee(self._dev_handle, int(on))
            except Exception as exc:   # noqa: BLE001
                logger.warning("set_bias_tee failed: %s", exc)

    def set_direct_sampling(self, mode: int) -> None:
        if self._dev_handle is not None:
            try:
                _librtlsdr.rtlsdr_set_direct_sampling(self._dev_handle, int(mode))
            except Exception as exc:   # noqa: BLE001
                logger.warning("set_direct_sampling failed: %s", exc)

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
        try:
            if not hasattr(lib.rtlsdr_set_direct_sampling, "argtypes"):
                lib.rtlsdr_set_direct_sampling.argtypes = [ctypes.c_void_p, ctypes.c_int]
                lib.rtlsdr_set_direct_sampling.restype = ctypes.c_int
        except Exception:   # noqa: BLE001
            pass
        try:
            fn = getattr(lib, "rtlsdr_set_dithering", None)
            if fn is not None and not hasattr(fn, "argtypes"):
                fn.argtypes = [ctypes.c_void_p, ctypes.c_int]
                fn.restype = ctypes.c_int
        except Exception:   # noqa: BLE001
            pass
        try:
            fn = getattr(lib, "rtlsdr_set_and_get_tuner_bandwidth", None)
            if fn is not None and not hasattr(fn, "argtypes"):
                fn.argtypes = [
                    ctypes.c_void_p, ctypes.c_uint32,
                    ctypes.POINTER(ctypes.c_uint32), ctypes.c_int,
                ]
                fn.restype = ctypes.c_int
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
# rtl_tcp remote backend
# ---------------------------------------------------------------------------

# R820T gain table in dB — rtl_tcp only reports gain_count, not the values.
_R820T_GAINS = [
    0.0, 0.9, 1.4, 2.7, 3.7, 7.7, 8.7, 12.5, 14.4, 15.7,
    16.6, 19.7, 20.7, 22.9, 25.4, 28.0, 29.7, 32.8, 33.8,
    36.4, 37.2, 38.6, 40.2, 42.1, 43.4, 43.9, 44.5, 48.0, 49.6,
]

# rtl_tcp command opcodes
_CMD_SET_FREQ = 0x01
_CMD_SET_SAMPLE_RATE = 0x02
_CMD_SET_GAIN_MODE = 0x03
_CMD_SET_GAIN = 0x04
_CMD_SET_FREQ_CORRECTION = 0x05
_CMD_SET_AGC_MODE = 0x08
_CMD_SET_DIRECT_SAMPLING = 0x09
_CMD_SET_OFFSET_TUNING = 0x0A
_CMD_SET_TUNER_BANDWIDTH = 0x0B
_CMD_SET_BIAS_TEE = 0x0E


class RtlTcpBackend(SDRBackend):
    """Backend streaming IQ data from a remote rtl_tcp server."""

    def __init__(self, host: str, port: int) -> None:
        self._host = host
        self._port = port
        self._sock: Optional[socket.socket] = None
        self._cmd_lock = threading.Lock()
        self._tuner_type: int = 0
        self._gain_count: int = 0

    def open(self, device_index: int, config: dict) -> bool:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5.0)
            sock.connect((self._host, self._port))

            # Read 12-byte handshake header
            header = b""
            while len(header) < 12:
                chunk = sock.recv(12 - len(header))
                if not chunk:
                    raise ConnectionError("rtl_tcp closed during handshake")
                header += chunk

            magic = header[:4]
            if magic != b"RTL0":
                raise ConnectionError(
                    f"Bad rtl_tcp magic: {magic!r} (expected b'RTL0')"
                )
            self._tuner_type = struct.unpack(">I", header[4:8])[0]
            self._gain_count = struct.unpack(">I", header[8:12])[0]
            logger.info(
                "rtl_tcp connected to %s:%d  tuner=%d  gains=%d",
                self._host, self._port, self._tuner_type, self._gain_count,
            )
            self._sock = sock
        except Exception as exc:  # noqa: BLE001
            logger.error("rtl_tcp connect failed: %s", exc)
            try:
                sock.close()
            except Exception:  # noqa: BLE001
                pass
            return False

        # Send initial configuration commands
        sr = config.get("sample_rate", 2_400_000)
        freq = config.get("centre_freq", 98_100_000)
        gain = config.get("gain", 30.0)
        ppm = config.get("ppm", 0)
        agc = config.get("agc_mode", False)

        self._send_cmd(_CMD_SET_SAMPLE_RATE, sr)
        self._send_cmd(_CMD_SET_FREQ, freq)
        if agc:
            self._send_cmd(_CMD_SET_AGC_MODE, 1)
            self._send_cmd(_CMD_SET_GAIN_MODE, 0)
        else:
            self._send_cmd(_CMD_SET_AGC_MODE, 0)
            self._send_cmd(_CMD_SET_GAIN_MODE, 1)
            self._send_cmd(_CMD_SET_GAIN, int(gain * 10))
        if ppm != 0:
            self._send_cmd(_CMD_SET_FREQ_CORRECTION, ppm)
        self._send_cmd(_CMD_SET_OFFSET_TUNING, int(config.get("offset_tuning", False)))
        bw = config.get("tuner_bandwidth", 0)
        if bw:
            self._send_cmd(_CMD_SET_TUNER_BANDWIDTH, bw)
        self._send_cmd(_CMD_SET_BIAS_TEE, int(config.get("bias_tee", False)))
        self._send_cmd(_CMD_SET_DIRECT_SAMPLING, int(config.get("direct_sampling", 0)))

        return True

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.shutdown(socket.SHUT_RDWR)
            except Exception:  # noqa: BLE001
                pass
            try:
                self._sock.close()
            except Exception:  # noqa: BLE001
                pass
            self._sock = None

    def stream_loop(self, chunk_size, running, on_samples, on_error):
        if self._sock is None:
            return
        self._sock.settimeout(2.0)
        # Each complex sample = 2 bytes (uint8 I + uint8 Q)
        byte_count = chunk_size * 2
        buf = bytearray(byte_count)

        while running():
            try:
                view = memoryview(buf)
                received = 0
                while received < byte_count:
                    if not running():
                        return
                    try:
                        n = self._sock.recv_into(view[received:], byte_count - received)
                    except socket.timeout:
                        continue
                    if n == 0:
                        raise ConnectionError("rtl_tcp server closed connection")
                    received += n

                # Convert uint8 IQ pairs to complex64
                raw = np.frombuffer(buf, dtype=np.uint8)
                iq = raw.astype(np.float32)
                iq = (iq - 127.5) / 127.5
                samples = iq[0::2] + 1j * iq[1::2]
                if on_samples is not None:
                    on_samples(samples.astype(np.complex64))
            except socket.timeout:
                continue
            except Exception as exc:  # noqa: BLE001
                if running():
                    logger.error("rtl_tcp stream error: %s", exc)
                    if on_error:
                        on_error(f"Stream error: {exc}")
                return

    # -- Command sending --

    def _send_cmd(self, opcode: int, param: int) -> None:
        """Send a 5-byte command to the rtl_tcp server (thread-safe)."""
        if self._sock is None:
            return
        data = struct.pack(">BI", opcode, param & 0xFFFFFFFF)
        with self._cmd_lock:
            try:
                self._sock.sendall(data)
            except Exception as exc:  # noqa: BLE001
                logger.warning("rtl_tcp send_cmd(0x%02x) failed: %s", opcode, exc)

    # -- Live setters --

    def set_frequency(self, freq_hz: int) -> None:
        self._send_cmd(_CMD_SET_FREQ, freq_hz)

    def set_sample_rate(self, rate: int) -> None:
        self._send_cmd(_CMD_SET_SAMPLE_RATE, rate)

    def set_gain(self, gain_db: float) -> None:
        self._send_cmd(_CMD_SET_GAIN, int(gain_db * 10))

    def set_ppm(self, ppm: int) -> None:
        if ppm != 0:
            self._send_cmd(_CMD_SET_FREQ_CORRECTION, ppm)

    def set_agc_mode(self, on: bool, gain_db: float = 30.0) -> None:
        self._send_cmd(_CMD_SET_AGC_MODE, int(on))
        self._send_cmd(_CMD_SET_GAIN_MODE, 0 if on else 1)
        if not on:
            self._send_cmd(_CMD_SET_GAIN, int(gain_db * 10))

    def set_offset_tuning(self, on: bool) -> None:
        self._send_cmd(_CMD_SET_OFFSET_TUNING, int(on))

    def set_tuner_bandwidth(self, bw_hz: int) -> int:
        self._send_cmd(_CMD_SET_TUNER_BANDWIDTH, bw_hz)
        return bw_hz  # rtl_tcp can't report the actual applied BW

    def set_bias_tee(self, on: bool) -> None:
        self._send_cmd(_CMD_SET_BIAS_TEE, int(on))

    def set_direct_sampling(self, mode: int) -> None:
        self._send_cmd(_CMD_SET_DIRECT_SAMPLING, int(mode))

    def get_valid_gains(self) -> List[float]:
        return list(_R820T_GAINS)


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


def create_backend(settings=None) -> SDRBackend:
    """Return the best available backend.

    If *settings* has an active rtl_tcp server, return an `RtlTcpBackend`
    connected to that server.  Otherwise fall through to local backends.
    """
    if settings is not None:
        srv = settings.active_rtl_tcp_server()
        if srv is not None:
            return RtlTcpBackend(srv["host"], srv["port"])
    if _PYRTLSDR_AVAILABLE:
        return PyRtlSdrBackend()
    if _SOAPY_AVAILABLE:
        return SoapyBackend()
    return DummyBackend()
