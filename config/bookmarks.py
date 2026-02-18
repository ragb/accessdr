"""
config/bookmarks.py — Bookmark model and JSON persistence.

A bookmark stores a label, frequency (Hz), and demodulation mode.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from typing import List

BOOKMARKS_FILE = os.path.join(
    os.path.dirname(__file__), "..", "bookmarks.json"
)


@dataclass
class Bookmark:
    label: str
    frequency: int          # Hz
    mode: str = "WFM"


@dataclass
class BookmarkStore:
    bookmarks: List[Bookmark] = field(default_factory=list)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def load(self, path: str = BOOKMARKS_FILE) -> None:
        """Load bookmarks from JSON file (silently ignores missing file)."""
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            self.bookmarks = [Bookmark(**item) for item in data]
        except FileNotFoundError:
            self.bookmarks = []
        except (json.JSONDecodeError, TypeError, KeyError) as exc:
            print(f"[bookmarks] Could not load {path}: {exc}")
            self.bookmarks = []

    def save(self, path: str = BOOKMARKS_FILE) -> None:
        """Persist bookmarks to JSON file."""
        with open(path, "w", encoding="utf-8") as fh:
            json.dump([asdict(bm) for bm in self.bookmarks], fh, indent=2)

    # ------------------------------------------------------------------
    # CRUD helpers
    # ------------------------------------------------------------------

    def add(self, label: str, frequency: int, mode: str = "WFM") -> Bookmark:
        bm = Bookmark(label=label, frequency=frequency, mode=mode)
        self.bookmarks.append(bm)
        return bm

    def remove(self, index: int) -> None:
        del self.bookmarks[index]

    def get_all(self) -> List[Bookmark]:
        return list(self.bookmarks)
