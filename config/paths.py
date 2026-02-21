"""
config/paths.py — Portable data-path helpers.

When running from source the project root is used.  When frozen with
PyInstaller, user data goes to ``%APPDATA%/AccessDR/`` and bundled
resources are read from ``sys._MEIPASS``.
"""

from __future__ import annotations

import os
import sys


def is_frozen() -> bool:
    """Return True when running inside a PyInstaller bundle."""
    return getattr(sys, "frozen", False)


def bundle_dir() -> str:
    """Return the directory that contains bundled data files.

    PyInstaller one-dir mode: ``sys._MEIPASS`` (the temp extract folder).
    Development:               the project root.
    """
    if is_frozen():
        return sys._MEIPASS  # type: ignore[attr-defined]
    return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def help_dir() -> str:
    """Return the directory containing bundled HTML help files.

    Frozen: ``<exe_dir>/help/``  (PyInstaller datas target).
    Dev:    ``<project_root>/build/help/``.
    """
    if is_frozen():
        return os.path.join(os.path.dirname(sys.executable), "help")
    return os.path.join(
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..")),
        "build", "help",
    )


def app_data_dir() -> str:
    """Return the directory for user-writable data (settings, bookmarks).

    Frozen: ``%APPDATA%/AccessDR/`` (created if missing).
    Dev:    the project root.
    """
    if is_frozen():
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
        path = os.path.join(base, "AccessDR")
        os.makedirs(path, exist_ok=True)
        return path
    return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
