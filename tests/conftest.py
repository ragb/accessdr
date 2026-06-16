"""Shared fixtures for AccessDR tests."""

from __future__ import annotations

import builtins
import sys
import os

# Ensure project root is on sys.path so ``import core...`` etc. resolve
# when running pytest from any working directory.
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

# Install no-op gettext builtins so modules that mark strings with _() / N_()
# at import time (config.bands, config.modes, …) load without a wx.App.
# Mirrors the bootstrap in main.py.
if not hasattr(builtins, "_"):
    builtins.__dict__["_"] = lambda s: s
if not hasattr(builtins, "N_"):
    builtins.__dict__["N_"] = lambda s: s
if not hasattr(builtins, "ngettext"):
    builtins.__dict__["ngettext"] = lambda s, p, n: s if n == 1 else p

import pytest


@pytest.fixture(scope="session")
def wx_app():
    """A single wx.App for the whole test session (required to build widgets)."""
    import wx
    app = wx.App()
    yield app


@pytest.fixture(autouse=True)
def _silence_speech():
    """Stop tests from driving the screen reader."""
    try:
        from accessibility import speech
        speech.output = lambda *a, **k: None
    except Exception:
        pass
    yield
