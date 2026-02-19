# -*- mode: python ; coding: utf-8 -*-
"""
accessdr.spec — PyInstaller spec for AccessDR.

Build with:
    .venv\\Scripts\\pyinstaller.exe accessdr.spec

Output:  dist\\AccessDR\\AccessDR.exe  (one-directory mode, no console)
"""

import os

block_cipher = None
PROJ = os.path.abspath(".")

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

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AccessDR",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,                  # no console window
    icon=None,                      # TODO: add icon when available
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
