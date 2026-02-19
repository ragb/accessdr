"""
PyInstaller hook for accessible_output2.

Collects:
- All screen-reader client DLLs from accessible_output2/lib/
- All output sub-modules (auto-detected at import time)
- The platform_utils dependency
"""

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

hiddenimports = (
    collect_submodules("accessible_output2")
    + collect_submodules("platform_utils")
)

datas = collect_data_files("accessible_output2")
