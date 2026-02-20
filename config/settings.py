"""
config/settings.py — Application settings dataclass with JSON persistence.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from typing import Optional

from config.paths import app_data_dir

SETTINGS_FILE = os.path.join(app_data_dir(), "settings.json")


@dataclass
class Settings:
    # Radio
    device_index: int = 0
    frequency: int = 98_100_000      # Hz
    mode: str = "WFM"
    bandwidth: int = 200_000         # Hz
    sample_rate: int = 2_400_000     # sps
    gain: float = 30.0               # dB
    ppm: int = 0
    agc_mode: bool = False
    offset_tuning: bool = False
    tuner_bandwidth: int = 0         # Hz, 0 = auto

    # Audio
    volume: float = 0.75             # 0.0 – 1.0
    squelch: float = -80.0           # dBm
    muted: bool = False
    audio_device: Optional[str] = None
    recording_path: str = ""
    audio_buffer_size: int = 4096    # sounddevice blocksize (samples)

    # Spectrum / sonification
    fft_size: int = 1024
    sonification_enabled: bool = False
    sonification_min_hz: int = 200
    sonification_max_hz: int = 4000
    sonification_sweep_speed: float = 5.0   # seconds per sweep
    speech_peak_count: int = 3
    auto_announce_threshold: float = -60.0  # dBm

    # i18n — empty string means system default
    language: str = ""

    # Step
    step: int = 1_000               # Hz

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self, path: str = SETTINGS_FILE) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(asdict(self), fh, indent=2)

    @classmethod
    def load(cls, path: str = SETTINGS_FILE) -> "Settings":
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            # Filter to known fields only to tolerate schema changes
            known = {f for f in cls.__dataclass_fields__}
            filtered = {k: v for k, v in data.items() if k in known}
            return cls(**filtered)
        except FileNotFoundError:
            return cls()
        except (json.JSONDecodeError, TypeError) as exc:
            print(f"[settings] Could not load {path}: {exc}")
            return cls()
