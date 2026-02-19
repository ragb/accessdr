"""
PyInstaller runtime hook — add the exe and _MEIPASS directories to the
DLL search path so that rtlsdr.dll, pthreadVC2.dll, etc. are found by
ctypes.  PyInstaller 6.x places binaries under _internal/ (== _MEIPASS).
"""

import os
import sys

exe_dir = os.path.dirname(sys.executable)
os.add_dll_directory(exe_dir)

# PyInstaller 6.x: binaries live in _MEIPASS (_internal/ next to the exe)
meipass = getattr(sys, "_MEIPASS", None)
if meipass and meipass != exe_dir:
    os.add_dll_directory(meipass)
