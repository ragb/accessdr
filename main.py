"""
main.py — AccessDR application entry point.

Initialises the wx.App and opens the main window.
"""

import logging
import sys
import wx
from ui.main_window import MainWindow

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s %(name)s: %(message)s",
    stream=sys.stderr,
)


class AccessDRApp(wx.App):
    """Top-level wx application."""

    def OnInit(self) -> bool:
        self.SetAppName("AccessDR")
        frame = MainWindow(None, title="AccessDR — Accessible SDR Radio")
        self.SetTopWindow(frame)
        frame.Show()
        return True

    def OnExit(self) -> int:
        return super().OnExit()


def main() -> None:
    app = AccessDRApp(redirect=False)
    app.MainLoop()


if __name__ == "__main__":
    main()
