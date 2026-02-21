"""
core/audio.py — sounddevice audio output stream.

The AudioOutput class manages a sounddevice OutputStream that consumes
float32 audio samples produced by the demodulator.  Samples are buffered
in a queue; the callback drains that queue on every audio block.

Volume and mute are applied in the callback so changes take effect
immediately without restarting the stream.
"""

from __future__ import annotations

import logging
import math
import queue
import threading
import wave
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

try:
    import sounddevice as sd
    _SD_AVAILABLE = True
    # Force WASAPI on Windows — lower latency, no device-name ambiguity
    for _api in sd.query_hostapis():
        if "WASAPI" in _api.get("name", ""):
            sd.default.device = (
                _api["default_input_device"],
                _api["default_output_device"],
            )
            break
except Exception:                  # noqa: BLE001
    _SD_AVAILABLE = False
    logger.warning("sounddevice not available — audio output disabled")

def _resolve_wasapi_device(name: str):
    """Resolve a device *name* to its WASAPI device index.

    sounddevice raises an error when a name matches multiple host APIs
    (e.g. DirectSound *and* WASAPI).  This finds the WASAPI index explicitly.
    Uses substring matching to handle truncated or suffixed device names.
    Falls back to the default device if no WASAPI match is found.
    """
    if not _SD_AVAILABLE:
        return name
    try:
        wasapi_ids: set = set()
        for api in sd.query_hostapis():
            if "WASAPI" in api.get("name", ""):
                wasapi_ids = set(api["devices"])
                break
        for idx, dev in enumerate(sd.query_devices()):
            dev_name = dev.get("name", "")
            if idx in wasapi_ids and (dev_name == name
                                      or name in dev_name
                                      or dev_name in name):
                return idx
    except Exception:  # noqa: BLE001
        pass
    # Name didn't match any WASAPI device — return None so sounddevice
    # uses the default output instead of crashing on an ambiguous name.
    logger.warning("WASAPI device %r not found, using default output", name)
    return None


AUDIO_RATE = 48_000
CHANNELS = 2          # always stereo output; mono sources are upmixed in write()
DEFAULT_BLOCKSIZE = 4096


class AudioOutput:
    """Manages the audio output stream for demodulated radio audio."""

    def __init__(
        self,
        sample_rate: int = AUDIO_RATE,
        device: Optional[str] = None,
        blocksize: int = DEFAULT_BLOCKSIZE,
    ) -> None:
        self.sample_rate = sample_rate
        self.device = device
        self.blocksize = blocksize
        self.volume: float = 0.75       # 0.0 – 1.0
        self.squelch: float = -80.0     # dBm; signals below this → silence
        self.muted: bool = False
        self.signal_db: float = -120.0  # last measured signal strength

        # Ducking: smoothly reduce radio volume while probe tone plays
        self._duck_target: float = 1.0   # 1.0 = full, 0.0 = silent
        self._duck_level: float = 1.0    # current level (ramped in callback)

        self._audio_queue: queue.Queue = queue.Queue(maxsize=128)
        self._leftover = np.zeros((0, CHANNELS), dtype=np.float32)
        self._stream: Optional["sd.OutputStream"] = None
        self._recording: bool = False
        self._wav_file: Optional[wave.Wave_write] = None
        self._lock = threading.Lock()
        self.audio_underruns: int = 0    # callback couldn't fill buffer
        self.audio_overruns: int = 0     # write() dropped (queue full)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        if not _SD_AVAILABLE:
            return
        try:
            kwargs: dict = dict(
                samplerate=self.sample_rate,
                channels=CHANNELS,
                dtype="float32",
                blocksize=self.blocksize,
                callback=self._callback,
            )
            if self.device:
                resolved = _resolve_wasapi_device(self.device)
                if resolved is not None:
                    kwargs["device"] = resolved
            self._stream = sd.OutputStream(**kwargs)
            self._stream.start()
            logger.info("Audio output started at %d Hz", self.sample_rate)
        except Exception as exc:   # noqa: BLE001
            logger.error("Could not open audio output: %s", exc)

    def stop(self) -> None:
        self.stop_recording()
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:      # noqa: BLE001
                pass
            self._stream = None
        self._leftover = np.zeros((0, CHANNELS), dtype=np.float32)

    def pause(self) -> None:
        """Pause audio output. Stops and closes the stream, drains the queue.
        Call resume() to recreate a fresh stream."""
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:      # noqa: BLE001
                pass
            self._stream = None
        # Drain stale audio so resume doesn't burst old samples
        self._leftover = np.zeros((0, CHANNELS), dtype=np.float32)
        while not self._audio_queue.empty():
            try:
                self._audio_queue.get_nowait()
            except queue.Empty:
                break

    def resume(self) -> None:
        """Resume audio after a pause by creating a fresh stream."""
        self.start()

    def duck(self, level: float) -> None:
        """Set duck target (0.0–1.0). Radio volume ramps smoothly to this."""
        self._duck_target = max(0.0, min(1.0, level))

    # ------------------------------------------------------------------
    # Sample input
    # ------------------------------------------------------------------

    def write(self, audio: np.ndarray) -> None:
        """Push audio samples to the output queue.

        Accepts either (N,) mono or (N, 2) stereo float32 arrays.
        Mono input is duplicated to both channels before queuing.
        Called from the DSP thread — non-blocking, drops if full.
        """
        if audio.size == 0:
            return

        # Normalise to (N, 2) stereo
        a = audio.astype(np.float32)
        if a.ndim == 1:
            stereo = np.stack([a, a], axis=1)   # upmix mono → both channels
        else:
            stereo = a                           # already (N, 2)

        try:
            self._audio_queue.put_nowait(stereo)
        except queue.Full:
            self.audio_overruns += 1

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def start_recording(self, path: str = "") -> str:
        """Begin writing audio to a WAV file. Returns the file path."""
        if self._recording:
            return ""
        if not path:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = str(Path.home() / f"accessdr_{ts}.wav")
        try:
            self._wav_file = wave.open(path, "wb")
            self._wav_file.setnchannels(CHANNELS)
            self._wav_file.setsampwidth(2)           # 16-bit
            self._wav_file.setframerate(self.sample_rate)
            self._recording = True
            logger.info("Recording started: %s", path)
            return path
        except Exception as exc:   # noqa: BLE001
            logger.error("Could not start recording: %s", exc)
            return ""

    def stop_recording(self) -> None:
        """Stop recording and close the WAV file."""
        self._recording = False
        if self._wav_file is not None:
            try:
                self._wav_file.close()
            except Exception:      # noqa: BLE001
                pass
            self._wav_file = None
            logger.info("Recording stopped")

    # ------------------------------------------------------------------
    # sounddevice callback (audio thread)
    # ------------------------------------------------------------------

    def _callback(
        self,
        outdata: np.ndarray,
        frames: int,
        time,                      # noqa: ANN001
        status,                    # noqa: ANN001
    ) -> None:
        """Fill *outdata* (frames, 2) with demodulated audio."""
        # Accumulate leftover + queue chunks until we have enough
        parts = []
        collected = len(self._leftover)
        if collected > 0:
            parts.append(self._leftover)

        while collected < frames:
            try:
                chunk = self._audio_queue.get_nowait()   # shape (N, 2)
            except queue.Empty:
                break
            parts.append(chunk)
            collected += len(chunk)

        if parts:
            buf = np.concatenate(parts) if len(parts) > 1 else parts[0]
        else:
            buf = self._leftover  # empty array

        take = min(len(buf), frames)
        combined = np.zeros((frames, 2), dtype=np.float32)
        combined[:take] = buf[:take]
        self._leftover = buf[take:] if take < len(buf) else np.zeros((0, CHANNELS), dtype=np.float32)

        if take < frames:
            self.audio_underruns += 1

        # Squelch
        if self.signal_db < self.squelch:
            combined[:] = 0.0

        # Volume + mute + ducking
        if self.muted:
            combined[:] = 0.0
        else:
            duck_target = self._duck_target
            duck_level = self._duck_level
            if abs(duck_level - duck_target) > 0.001:
                # ~15 ms exponential ramp to avoid clicks
                alpha = 1.0 - math.exp(-1.0 / (self.sample_rate * 0.015))
                k = 1.0 - alpha
                idx = np.arange(1, frames + 1, dtype=np.float64)
                ramp = duck_target + (duck_level - duck_target) * (k ** idx)
                self._duck_level = float(ramp[-1])
                combined *= (self.volume * ramp.astype(np.float32))[:, np.newaxis]
            else:
                self._duck_level = duck_target
                combined *= self.volume * duck_target

        outdata[:] = combined

        # Record (convert float → int16, interleaved stereo)
        if self._recording and self._wav_file is not None:
            try:
                pcm = (combined * 32767.0).astype(np.int16)  # (frames, 2)
                self._wav_file.writeframes(pcm.tobytes())
            except Exception:      # noqa: BLE001
                pass

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def list_devices() -> list:
        """Return output devices from the WASAPI host API only."""
        if not _SD_AVAILABLE:
            return []
        try:
            wasapi_devs: set = set()
            for api in sd.query_hostapis():
                if "WASAPI" in api.get("name", ""):
                    wasapi_devs = set(api["devices"])
                    break
            return [
                d for i, d in enumerate(sd.query_devices())
                if i in wasapi_devs
            ]
        except Exception:          # noqa: BLE001
            return []
