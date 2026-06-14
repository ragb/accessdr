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


def default_maps() -> List[ChannelMap]:
    """Ship one starter map with a few common simplex frequencies."""
    return [
        ChannelMap(
            "My Channels",
            [
                Channel(1, "PMR446 Ch1", 446_006_250, "NFM", 12_500),
                Channel(2, "NOAA WX1", 162_400_000, "NFM", 12_500),
            ],
        ),
    ]


@dataclass
class ChannelMapStore:
    maps: List[ChannelMap] = field(default_factory=list)
    active: int = 0                 # index into maps

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def load(self, path: str = CHANNELS_FILE) -> None:
        """Load channel maps from JSON (seeds defaults when missing)."""
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
        except FileNotFoundError:
            self.maps = default_maps()
            self.active = 0
        except (json.JSONDecodeError, TypeError, KeyError) as exc:
            print(f"[channels] Could not load {path}: {exc}")
            self.maps = default_maps()
            self.active = 0
        self._clamp_active()

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
