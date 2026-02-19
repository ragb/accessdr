"""
tasks.py -- Invoke build tasks for AccessDR.

Usage:
    invoke --list          # show all tasks
    invoke i18n-build      # extract + update + compile translations
    invoke build           # i18n + PyInstaller freeze
    invoke installer       # i18n + freeze + NSIS installer
    invoke clean           # remove build artifacts
    invoke run             # launch app from source
"""

from __future__ import annotations

import os
import sys

from invoke import task, Context

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
VENV_SCRIPTS = os.path.join(PROJECT_ROOT, ".venv", "Scripts")
PYTHON = os.path.join(VENV_SCRIPTS, "python.exe")
PYBABEL = os.path.join(VENV_SCRIPTS, "pybabel.exe")
PYINSTALLER = os.path.join(VENV_SCRIPTS, "pyinstaller.exe")
MAKENSIS = r"C:\Program Files (x86)\NSIS\makensis.exe"

LOCALE_DIR = os.path.join(PROJECT_ROOT, "locale")
POT_FILE = os.path.join(LOCALE_DIR, "accessdr.pot")
BABEL_CFG = os.path.join(PROJECT_ROOT, "babel.cfg")
SPEC_FILE = os.path.join(PROJECT_ROOT, "accessdr.spec")
NSI_FILE = os.path.join(PROJECT_ROOT, "installer", "accessdr.nsi")
DOMAIN = "accessdr"

# Read version from accessdr_version.py so it can be reused
_version_ns: dict = {}
exec(open(os.path.join(PROJECT_ROOT, "accessdr_version.py")).read(), _version_ns)
VERSION: str = _version_ns["__version__"]


def _q(path: str) -> str:
    """Quote a path for shell use."""
    return f'"{path}"'


# ---------------------------------------------------------------------------
# i18n tasks
# ---------------------------------------------------------------------------
@task
def i18n_extract(c: Context) -> None:
    """Extract translatable strings into locale/accessdr.pot."""
    c.run(
        f'{_q(PYBABEL)} extract'
        f' -F {_q(BABEL_CFG)}'
        f' -o {_q(POT_FILE)}'
        f' -k "_ N_ ngettext"'
        f' --project={DOMAIN}'
        f' --version={VERSION}'
        f' --copyright-holder="AccessDR Contributors"'
        f' .',
        echo=True,
    )


@task
def i18n_update(c: Context) -> None:
    """Merge new strings from .pot into existing .po catalogues."""
    c.run(
        f'{_q(PYBABEL)} update'
        f' -i {_q(POT_FILE)}'
        f' -d {_q(LOCALE_DIR)}'
        f' -D {DOMAIN}'
        f' --no-fuzzy-matching',
        echo=True,
    )


@task
def i18n_compile(c: Context) -> None:
    """Compile all .po files to binary .mo."""
    c.run(
        f'{_q(PYBABEL)} compile'
        f' -d {_q(LOCALE_DIR)}'
        f' -D {DOMAIN}'
        f' --statistics',
        echo=True,
    )


@task
def i18n_init(c: Context, lang: str = "") -> None:
    """Initialise a new language: invoke i18n-init --lang=fr_FR"""
    if not lang:
        print("Usage: invoke i18n-init --lang=<code>  (e.g. fr_FR)")
        sys.exit(1)
    c.run(
        f'{_q(PYBABEL)} init'
        f' -i {_q(POT_FILE)}'
        f' -d {_q(LOCALE_DIR)}'
        f' -l {lang}'
        f' -D {DOMAIN}',
        echo=True,
    )
    print(f"Created locale/{lang}/LC_MESSAGES/{DOMAIN}.po")
    print("Translate it, then run: invoke i18n-compile")


@task(pre=[i18n_extract, i18n_update, i18n_compile])
def i18n_build(c: Context) -> None:
    """Full i18n pipeline: extract -> update -> compile."""
    print("[i18n] Done.")


# ---------------------------------------------------------------------------
# Build tasks
# ---------------------------------------------------------------------------
@task(pre=[i18n_build])
def build(c: Context) -> None:
    """Freeze app with PyInstaller (runs i18n first)."""
    c.run(f'{_q(PYINSTALLER)} --noconfirm {_q(SPEC_FILE)}', echo=True)
    exe = os.path.join(PROJECT_ROOT, "dist", "AccessDR", "AccessDR.exe")
    if os.path.isfile(exe):
        print(f"[build] OK: {exe}")
    else:
        print("[build] WARNING: exe not found after build")
        sys.exit(1)


@task(pre=[build])
def installer(c: Context) -> None:
    """Build NSIS installer (runs build first)."""
    if not os.path.isfile(MAKENSIS):
        print(f"[installer] NSIS not found at {MAKENSIS}")
        print("[installer] Install with: winget install NSIS.NSIS")
        sys.exit(1)
    os.makedirs(os.path.join(PROJECT_ROOT, "dist", "installer"), exist_ok=True)
    c.run(f'{_q(MAKENSIS)} {_q(NSI_FILE)}', echo=True)
    setup = os.path.join(
        PROJECT_ROOT, "dist", "installer", f"AccessDR-{VERSION}-setup.exe"
    )
    if os.path.isfile(setup):
        print(f"[installer] OK: {setup}")
    else:
        print("[installer] WARNING: setup exe not found after build")


# ---------------------------------------------------------------------------
# Utility tasks
# ---------------------------------------------------------------------------
@task
def clean(c: Context) -> None:
    """Remove build artifacts (build/, dist/)."""
    for d in ["build", "dist"]:
        path = os.path.join(PROJECT_ROOT, d)
        if os.path.isdir(path):
            c.run(f'rmdir /s /q "{path}"', echo=True)
            print(f"[clean] Removed {d}/")
    # .mo files (regenerated by i18n-compile)
    for root, _dirs, files in os.walk(LOCALE_DIR):
        for f in files:
            if f.endswith(".mo"):
                os.remove(os.path.join(root, f))
                print(f"[clean] Removed {os.path.relpath(os.path.join(root, f), PROJECT_ROOT)}")
    print("[clean] Done.")


@task
def run(c: Context) -> None:
    """Launch AccessDR from source."""
    c.run(f'{_q(PYTHON)} main.py', echo=True)
