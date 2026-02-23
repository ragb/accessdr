"""Shared fixtures for AccessDR tests."""

from __future__ import annotations

import sys
import os

# Ensure project root is on sys.path so ``import core...`` etc. resolve
# when running pytest from any working directory.
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)
