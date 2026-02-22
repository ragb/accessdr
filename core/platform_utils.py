"""core/platform_utils.py — OS-specific process/thread priority helpers."""

from __future__ import annotations

import threading


def elevate_process_priority() -> None:
    """Set process priority to Above Normal on Windows."""
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        ABOVE_NORMAL_PRIORITY_CLASS = 0x00008000
        kernel32.SetPriorityClass(kernel32.GetCurrentProcess(),
                                  ABOVE_NORMAL_PRIORITY_CLASS)
    except Exception:  # noqa: BLE001
        pass


def elevate_dsp_priority(thread: threading.Thread) -> None:
    """Raise the DSP thread to THREAD_PRIORITY_HIGHEST on Windows."""
    try:
        import ctypes
        import ctypes.wintypes as wt  # noqa: F811
        THREAD_SET_INFORMATION = 0x0020
        THREAD_PRIORITY_HIGHEST = 2
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.OpenThread(THREAD_SET_INFORMATION, False,
                                     thread.native_id)
        if handle:
            kernel32.SetThreadPriority(handle, THREAD_PRIORITY_HIGHEST)
            kernel32.CloseHandle(handle)
    except Exception:  # noqa: BLE001
        pass
