"""
config/channels.py — Channel memory model and JSON persistence.

A *channel* is a numbered memory slot (like a Baofeng/Yaesu memory):
frequency, mode, bandwidth, and an optional label.  Channels are grouped
into named *channel maps* ("Local Repeaters", "Air Band", …); a store
holds several maps and tracks which one is active (MR mode).
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from typing import List, Optional

from config.paths import app_data_dir

CHANNELS_FILE = os.path.join(app_data_dir(), "channels.json")


@dataclass
class Channel:
    number: int
    label: str
    frequency: int                  # Hz
    mode: str = "WFM"
    bandwidth: int = 200_000        # Hz
    # Optional per-channel mode overrides — None inherits the global setting.
    # Attribute names match config.mode_params / Settings.
    nfm_deviation: Optional[int] = None
    nfm_ctcss_notch: Optional[bool] = None
    wfm_deemphasis: Optional[str] = None
    wfm_stereo_mode: Optional[str] = None
    wfm_hiblend_enabled: Optional[bool] = None
    wfm_rds_enabled: Optional[bool] = None
    squelch_sensitivity: Optional[int] = None  # per-channel sensitivity (0–10); None = keep


@dataclass
class ChannelMap:
    name: str
    channels: List[Channel] = field(default_factory=list)

    def sorted_channels(self) -> List[Channel]:
        return sorted(self.channels, key=lambda c: c.number)

    def next_number(self) -> int:
        used = {c.number for c in self.channels}
        n = 1
        while n in used:
            n += 1
        return n


# PMR446 analogue FM: 16 channels, 12.5 kHz spacing from 446.00625 MHz.
_PMR446_BASE_HZ = 446_006_250
_PMR446_STEP_HZ = 12_500

# CB CEPT 40-channel FM frequencies (Hz), in channel order. Channels 23–25
# are intentionally out of frequency sequence (the standard CB anomaly).
_CB_CEPT_HZ = [
    26_965_000, 26_975_000, 26_985_000, 27_005_000, 27_015_000,
    27_025_000, 27_035_000, 27_055_000, 27_065_000, 27_075_000,
    27_085_000, 27_105_000, 27_115_000, 27_125_000, 27_135_000,
    27_155_000, 27_165_000, 27_175_000, 27_185_000, 27_205_000,
    27_215_000, 27_225_000, 27_255_000, 27_235_000, 27_245_000,
    27_265_000, 27_275_000, 27_285_000, 27_295_000, 27_305_000,
    27_315_000, 27_325_000, 27_335_000, 27_345_000, 27_355_000,
    27_365_000, 27_375_000, 27_385_000, 27_395_000, 27_405_000,
]


def _pmr446_map() -> ChannelMap:
    return ChannelMap(
        "PMR446",
        [
            Channel(n, f"PMR {n}", _PMR446_BASE_HZ + (n - 1) * _PMR446_STEP_HZ,
                    "NFM", 12_500)
            for n in range(1, 17)
        ],
    )


def _cb_cept_fm_map() -> ChannelMap:
    return ChannelMap(
        "CB (CEPT FM)",
        [
            Channel(n, f"CB {n}", hz, "NFM", 12_500, nfm_deviation=2_000)
            for n, hz in enumerate(_CB_CEPT_HZ, start=1)
        ],
    )


def _cb_cept_am_map() -> ChannelMap:
    return ChannelMap(
        "CB (CEPT AM)",
        [
            Channel(n, f"CB {n}", hz, "AM", 6_000)
            for n, hz in enumerate(_CB_CEPT_HZ, start=1)
        ],
    )


def default_maps() -> List[ChannelMap]:
    """Ship an empty scratch map plus standard PMR446 and CB band maps."""
    return [
        ChannelMap("My Channels", []),
        _pmr446_map(),
        _cb_cept_fm_map(),
        _cb_cept_am_map(),
    ]


@dataclass
class ChannelMapStore:
    maps: List[ChannelMap] = field(default_factory=list)
    active: int = 0                 # index into maps

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def load(self, path: str = CHANNELS_FILE) -> None:
        """Load channel maps from JSON (seeds defaults when missing).

        Any newly-shipped default maps not already present (by name) are
        merged in, so app updates add maps without losing the user's own.
        """
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            self.maps = [
                ChannelMap(
                    name=m["name"],
                    channels=[Channel(**c) for c in m.get("channels", [])],
                )
                for m in data.get("maps", [])
            ]
            self.active = data.get("active", 0)
            if not self.maps:
                self.maps = default_maps()
            else:
                self._merge_new_defaults()
        except FileNotFoundError:
            self.maps = default_maps()
            self.active = 0
        except (json.JSONDecodeError, TypeError, KeyError) as exc:
            print(f"[channels] Could not load {path}: {exc}")
            self.maps = default_maps()
            self.active = 0
        self._clamp_active()

    def _merge_new_defaults(self) -> None:
        """Append default maps whose names aren't already present."""
        have = {m.name for m in self.maps}
        for d in default_maps():
            if d.name not in have:
                self.maps.append(d)

    def save(self, path: str = CHANNELS_FILE) -> None:
        """Persist channel maps to JSON file."""
        payload = {
            "active": self.active,
            "maps": [
                {"name": m.name, "channels": [asdict(c) for c in m.channels]}
                for m in self.maps
            ],
        }
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)

    # ------------------------------------------------------------------
    # Lookup helpers
    # ------------------------------------------------------------------

    def _clamp_active(self) -> None:
        if not self.maps:
            self.active = 0
        else:
            self.active = max(0, min(self.active, len(self.maps) - 1))

    def active_map(self) -> Optional[ChannelMap]:
        if not self.maps:
            return None
        self._clamp_active()
        return self.maps[self.active]

    def set_active(self, index: int) -> None:
        self.active = index
        self._clamp_active()
