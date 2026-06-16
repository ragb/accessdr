# -*- mode: python ; coding: utf-8 -*-
"""
accessdr.spec — PyInstaller spec for AccessDR.

Build with:
    .venv\\Scripts\\pyinstaller.exe accessdr.spec

Output:  dist\\AccessDR\\AccessDR.exe  (one-directory mode, no console)
"""

import os
import re

block_cipher = None
PROJ = os.path.abspath(".")

# Read version from accessdr_version.py
_ver_text = open(os.path.join(PROJ, "accessdr_version.py")).read()
_ver_match = re.search(r'__version__\s*=\s*"([^"]+)"', _ver_text)
_version = _ver_match.group(1) if _ver_match else "0.0.0"
# Windows FixedFileInfo needs four integers.  PEP 440 pre-release strings
# like "0.7.0b1" aren't directly parseable (int("0b1") fails), so pull out
# the numeric components — the pre-release number becomes the 4th field
# (e.g. "0.7.0b1" -> (0, 7, 0, 1), "1.2.3" -> (1, 2, 3, 0)).
_ver_nums = re.findall(r"\d+", _version) or ["0"]
_ver_parts = (_ver_nums + ["0", "0", "0", "0"])[:4]
_ver_tuple = tuple(int(x) for x in _ver_parts)

a = Analysis(
    ["main.py"],
    pathex=[PROJ],
    binaries=[
        (os.path.join(PROJ, "rtlsdr.dll"), "."),
        (os.path.join(PROJ, "pthreadVC2.dll"), "."),
        (os.path.join(PROJ, "msvcr100.dll"), "."),
    ],
    datas=[
        (os.path.join(PROJ, "locale"), "locale"),
        (os.path.join(PROJ, "build", "help"), "help"),
    ],
    hiddenimports=[
        # accessible_output2 — handled by hook, but list explicitly too
        "accessible_output2",
        "accessible_output2.outputs",
        "accessible_output2.outputs.auto",
        "accessible_output2.outputs.nvda",
        "accessible_output2.outputs.sapi5",
        "accessible_output2.outputs.jaws",
        "accessible_output2.outputs.dolphin",
        "accessible_output2.outputs.e_speak",
        "accessible_output2.outputs.pc_talker",
        "accessible_output2.outputs.sapi4",
        "accessible_output2.outputs.system_access",
        "accessible_output2.outputs.window_eyes",
        "accessible_output2.outputs.zdsr",
        "accessible_output2.outputs.voiceover",
        "accessible_output2.outputs.speech_dispatcher",
        # platform_utils
        "platform_utils",
        "platform_utils.paths",
        "platform_utils.blackhole",
        "platform_utils._winpaths",
        # pyrtlsdr
        "rtlsdr",
        "rtlsdr.rtlsdr",
        "rtlsdr.librtlsdr",
        # scipy signal processing
        "scipy.signal",
        "scipy.signal._signaltools",
        "scipy.signal._upfirdn",
        # other
        "cffi",
        "libloader",
        "sounddevice",
    ],
    hookspath=[os.path.join(PROJ, "build_hooks")],
    runtime_hooks=[os.path.join(PROJ, "build_hooks", "rthook_dll_dir.py")],
    excludes=[
        "tkinter",
        "matplotlib",
        "IPython",
        "pytest",
        "sphinx",
    ],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# Windows version resource embedded in AccessDR.exe
from PyInstaller.utils.win32.versioninfo import (
    VSVersionInfo, FixedFileInfo, StringFileInfo, StringTable,
    StringStruct, VarFileInfo, VarStruct,
)
_vinfo = VSVersionInfo(
    ffi=FixedFileInfo(filevers=_ver_tuple, prodvers=_ver_tuple),
    kids=[
        StringFileInfo([StringTable("040904B0", [
            StringStruct("CompanyName", "AccessDR Contributors"),
            StringStruct("FileDescription", "AccessDR — Accessible SDR Radio"),
            StringStruct("FileVersion", _version),
            StringStruct("ProductName", "AccessDR"),
            StringStruct("ProductVersion", _version),
            StringStruct("LegalCopyright", "MIT License"),
        ])]),
        VarFileInfo([VarStruct("Translation", [0x0409, 0x04B0])]),
    ],
)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AccessDR",
    version=_vinfo,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,                  # no console window
    icon=os.path.join(PROJ, "accessdr.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="AccessDR",
)
