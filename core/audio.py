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
except Exception:                  # noqa: BLE001
    _SD_AVAILABLE = False
    logger.warning("sounddevice not available — audio output disabled")

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

        self._audio_queue: queue.Queue = queue.Queue(maxsize=128)
        self._stream: Optional["sd.OutputStream"] = None
        self._recording: bool = False
        self._wav_file: Optional[wave.Wave_write] = None
        self._lock = threading.Lock()

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
                kwargs["device"] = self.device
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

        # Measure signal strength in dBFS (mean power across all samples/channels)
        rms = float(np.sqrt(np.mean(audio.astype(np.float64) ** 2)))
        rms = max(rms, 1e-10)
        self.signal_db = 20.0 * np.log10(rms)

        # Normalise to (N, 2) stereo
        a = audio.astype(np.float32)
        if a.ndim == 1:
            stereo = np.stack([a, a], axis=1)   # upmix mono → both channels
        else:
            stereo = a                           # already (N, 2)

        try:
            self._audio_queue.put_nowait(stereo)
        except queue.Full:
            pass  # drop — latency is more important than completeness

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
        combined = np.zeros((frames, 2), dtype=np.float32)
        samples_needed = frames
        offset = 0

        while samples_needed > 0:
            try:
                chunk = self._audio_queue.get_nowait()   # shape (N, 2)
            except queue.Empty:
                break
            take = min(len(chunk), samples_needed)
            combined[offset : offset + take] = chunk[:take]
            offset += take
            samples_needed -= take

            if take < len(chunk):
                # Put remainder back (best-effort)
                try:
                    self._audio_queue.put_nowait(chunk[take:])
                except queue.Full:
                    pass

        # Squelch
        if self.signal_db < self.squelch:
            combined[:] = 0.0

        # Volume + mute
        if self.muted:
            combined[:] = 0.0
        else:
            combined *= self.volume

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
        if not _SD_AVAILABLE:
            return []
        try:
            return list(sd.query_devices())
        except Exception:          # noqa: BLE001
            return []
