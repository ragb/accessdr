"""
config/scenes.py — Band scene model and JSON persistence.

A *scene* is a band-exploration preset for VFO mode: a named region of
spectrum with a demodulation setup, but no specific channels.  Loading a
scene configures the radio to roam a band (FM broadcast, air band, …).

The built-in "Free / Full Range" scene has ``freq_start == freq_end == 0``,
meaning *unbounded* — it reproduces classic free-style VFO tuning.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from typing import List, Optional

from config.paths import app_data_dir

SCENES_FILE = os.path.join(app_data_dir(), "scenes.json")

# Name of the built-in unbounded scene (free-style VFO).
FREE_SCENE_NAME = "Free / Full Range"


@dataclass
class Scene:
    name: str
    freq_start: int = 0              # Hz; 0,0 == unbounded (free tuning)
    freq_end: int = 0               # Hz
    mode: str = "WFM"
    bandwidth: int = 200_000        # Hz
    step: int = 0                   # Hz; 0 == follow the user's tuning step
    default_freq: Optional[int] = None  # where to land on load; None = band start
    # Optional demod overrides — None leaves the current setting untouched.
    nfm_deviation: Optional[int] = None
    wfm_deemphasis: Optional[str] = None
    squelch: Optional[float] = None

    @property
    def unbounded(self) -> bool:
        """True when the scene has no band edges (free-style VFO)."""
        return self.freq_start == 0 and self.freq_end == 0

    def landing_freq(self) -> Optional[int]:
        """Frequency to tune to when this scene is loaded."""
        if self.default_freq is not None:
            return self.default_freq
        if not self.unbounded:
            return self.freq_start
        return None


def default_scenes() -> List[Scene]:
    """Ship a default band plan: the free scene plus one scene per known band.

    Seeded from ``config.bands`` so the band list has a single source of
    truth (these scenes supersede the former Radio → Bands menu).
    """
    # Lazy import: config.bands uses N_() at module scope, so importing it
    # only here keeps config.scenes import-light for callers that never need
    # the defaults.
    from config.bands import BANDS

    scenes: List[Scene] = [Scene(FREE_SCENE_NAME)]
    for name, entry in BANDS.items():
        # entry is (lo, hi, mode, bandwidth, step) with an optional trailing
        # dict of per-mode overrides (nfm_deviation / wfm_deemphasis / squelch).
        lo, hi, mode, bandwidth, step, *rest = entry
        overrides = rest[0] if rest else {}
        scenes.append(Scene(
            name=name,
            freq_start=lo,
            freq_end=hi,
            mode=mode,
            bandwidth=bandwidth,
            step=step,
            default_freq=(lo + hi) // 2,
            **overrides,
        ))
    return scenes


@dataclass
class SceneStore:
    scenes: List[Scene] = field(default_factory=list)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def load(self, path: str = SCENES_FILE) -> None:
        """Load scenes from JSON (seeds defaults when file is missing).

        Any newly-shipped default bands not already present (by name) are
        merged in, so app updates add new bands without losing the user's
        own bands or edits.
        """
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            self.scenes = [Scene(**item) for item in data]
            self._merge_new_defaults()
        except FileNotFoundError:
            self.scenes = default_scenes()
        except (json.JSONDecodeError, TypeError, KeyError) as exc:
            print(f"[scenes] Could not load {path}: {exc}")
            self.scenes = default_scenes()

    def _merge_new_defaults(self) -> None:
        """Append default bands whose names aren't already in the plan."""
        have = {s.name for s in self.scenes}
        for d in default_scenes():
            if d.name not in have:
                self.scenes.append(d)

    def save(self, path: str = SCENES_FILE) -> None:
        """Persist scenes to JSON file."""
        with open(path, "w", encoding="utf-8") as fh:
            json.dump([asdict(s) for s in self.scenes], fh, indent=2)

    # ------------------------------------------------------------------
    # Lookup / CRUD helpers
    # ------------------------------------------------------------------

    def add(self, scene: Scene) -> Scene:
        self.scenes.append(scene)
        return scene

    def remove(self, index: int) -> None:
        del self.scenes[index]

    def get_all(self) -> List[Scene]:
        return list(self.scenes)

    def by_name(self, name: str) -> Optional[Scene]:
        for s in self.scenes:
            if s.name == name:
                return s
        return None

    def free_scene(self) -> Scene:
        """Return the free/unbounded scene, creating one if absent."""
        s = self.by_name(FREE_SCENE_NAME)
        if s is None:
            s = Scene(FREE_SCENE_NAME)
            self.scenes.insert(0, s)
        return s
