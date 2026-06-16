"""
tasks.py -- Invoke build tasks for AccessDR.

Usage:
    invoke --list          # show all tasks
    invoke fetch-dlls      # download RTL-SDR DLLs for build
    invoke i18n-build      # extract + update + compile translations
    invoke build-help      # convert docs/ markdown to HTML in build/help/
    invoke build           # fetch-dlls + i18n + help + PyInstaller freeze
    invoke installer       # fetch-dlls + i18n + freeze + NSIS installer
    invoke clean           # remove build artifacts
    invoke run             # launch app from source
"""

from __future__ import annotations

import os
import shutil
import sys

from invoke import task, Context


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))


def _find_tool(name: str) -> str:
    """Return the path to *name*, preferring .venv/Scripts, then PATH."""
    venv = os.path.join(PROJECT_ROOT, ".venv", "Scripts", name)
    if os.path.isfile(venv):
        return venv
    on_path = shutil.which(name)
    if on_path:
        return on_path
    return name   # fall back to bare name, let the shell resolve it


PYTHON = _find_tool("python.exe")
PYBABEL = _find_tool("pybabel.exe")
PYINSTALLER = _find_tool("pyinstaller.exe")
MAKENSIS = shutil.which("makensis") or r"C:\Program Files (x86)\NSIS\makensis.exe"

RTLSDR_DLL_URL = (
    # v2.1.0 static w64 build — exports the full librtlsdr API (GPIO,
    # set_dithering, set_and_get_tuner_bandwidth) that pyrtlsdr >= 0.4.0
    # binds eagerly; the older v0.9.0 static build did not.
    "https://github.com/librtlsdr/librtlsdr/releases/download/"
    "v2.1.0/rtlsdr-bin-w64_static.zip"
)

HELP_SRC_DIR = os.path.join(PROJECT_ROOT, "docs")
HELP_OUT_DIR = os.path.join(PROJECT_ROOT, "build", "help")

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
# DLL fetch
# ---------------------------------------------------------------------------
@task
def fetch_dlls(c: Context) -> None:
    """Download RTL-SDR DLLs into the project root (skips if already present)."""
    dll_path = os.path.join(PROJECT_ROOT, "rtlsdr.dll")
    if os.path.isfile(dll_path) and os.path.getsize(dll_path) > 0:
        print("[fetch-dlls] rtlsdr.dll already present, skipping.")
        return

    import io
    import urllib.request
    import zipfile

    print(f"[fetch-dlls] Downloading from {RTLSDR_DLL_URL} ...")
    with urllib.request.urlopen(RTLSDR_DLL_URL) as resp:
        data = resp.read()

    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        # Static build ships librtlsdr.dll — rename to rtlsdr.dll for pyrtlsdr
        for name in zf.namelist():
            if name.endswith("librtlsdr.dll"):
                with open(dll_path, "wb") as f:
                    f.write(zf.read(name))
                print(f"[fetch-dlls] Extracted {name} -> rtlsdr.dll")
                break
        else:
            print("[fetch-dlls] ERROR: librtlsdr.dll not found in archive")
            sys.exit(1)

    # Create stub files for pthreadVC2/msvcr100 (not needed by static build,
    # but referenced in the PyInstaller spec so they must exist)
    for stub in ("pthreadVC2.dll", "msvcr100.dll"):
        stub_path = os.path.join(PROJECT_ROOT, stub)
        if not os.path.isfile(stub_path) or os.path.getsize(stub_path) == 0:
            open(stub_path, "wb").close()
            print(f"[fetch-dlls] Created stub {stub}")

    print("[fetch-dlls] Done.")


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
# Help build
# ---------------------------------------------------------------------------
_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{
    font-family: system-ui, -apple-system, sans-serif;
    max-width: 52em; margin: 2em auto; padding: 0 1em;
    line-height: 1.6;
  }}
  table {{ border-collapse: collapse; width: 100%; }}
  th, td {{ border: 1px solid #888; padding: .4em .6em; text-align: left; }}
  th {{ background: #eee; }}
  @media (prefers-color-scheme: dark) {{
    th {{ background: #333; }}
  }}
  kbd {{
    display: inline-block; padding: .1em .4em;
    border: 1px solid #888; border-radius: 3px;
    font-family: inherit; font-size: .9em;
    background: #f4f4f4;
  }}
  @media (prefers-color-scheme: dark) {{
    kbd {{ background: #333; }}
  }}
  code {{ padding: .1em .3em; border-radius: 3px; background: #f4f4f4; }}
  @media (prefers-color-scheme: dark) {{
    code {{ background: #333; }}
  }}
</style>
</head>
<body>
{body}
</body>
</html>
"""


def _keys_to_kbd(text: str) -> str:
    """Replace ``++key++`` markers with ``<kbd>Key</kbd>`` HTML.

    Handles combos like ``++ctrl+q++`` → ``<kbd>Ctrl</kbd>+<kbd>Q</kbd>``.
    """
    import re

    def _repl(m: re.Match) -> str:
        raw = m.group(1)
        parts = raw.split("+")
        rendered = []
        for p in parts:
            p = p.strip()
            nice = {
                "ctrl": "Ctrl", "shift": "Shift", "alt": "Alt",
                "enter": "Enter", "escape": "Escape", "space": "Space",
                "backspace": "Backspace", "page-up": "Page Up",
                "page-down": "Page Down", "up": "Up", "down": "Down",
                "left": "Left", "right": "Right", "plus": "+",
            }.get(p.lower(), p.upper() if len(p) == 1 else p.capitalize())
            rendered.append(f"<kbd>{nice}</kbd>")
        return "+".join(rendered)

    return re.sub(r"\+\+(.+?)\+\+", _repl, text)


@task
def build_help(c: Context) -> None:
    """Convert docs/user-guide.md to standalone HTML in build/help/."""
    import markdown as md

    src = os.path.join(HELP_SRC_DIR, "user-guide.md")
    if not os.path.isfile(src):
        print(f"[build-help] ERROR: {src} not found")
        sys.exit(1)

    os.makedirs(HELP_OUT_DIR, exist_ok=True)

    text = open(src, encoding="utf-8").read()
    text = _keys_to_kbd(text)
    # "toc" gives every heading a slug id so the in-document links (and the
    # [TOC] marker) actually resolve; "tables" for the reference tables.
    body = md.markdown(text, extensions=["tables", "toc"])
    html = _HTML_TEMPLATE.format(title="AccessDR User Guide", body=body)

    out = os.path.join(HELP_OUT_DIR, "user-guide.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[build-help] {out}")
    print("[build-help] Done.")


# ---------------------------------------------------------------------------
# Build tasks
# ---------------------------------------------------------------------------
@task(pre=[fetch_dlls, i18n_build, build_help])
def build(c: Context) -> None:
    """Freeze app with PyInstaller (fetches DLLs + runs i18n first)."""
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
    c.run(f'{_q(MAKENSIS)} /DVERSION={VERSION} {_q(NSI_FILE)}', echo=True)
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
def test(c: Context) -> None:
    """Run the test suite with pytest."""
    pytest = _find_tool("pytest.exe")
    c.run(f'{_q(pytest)} -v', echo=True)


@task
def run(c: Context) -> None:
    """Launch AccessDR from source."""
    c.run(f'{_q(PYTHON)} main.py', echo=True)
