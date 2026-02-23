"""
main.py — AccessDR application entry point.

Initialises the wx.App and opens the main window.
"""

import builtins
import io
import logging
import os
import sys

# PyInstaller windowed mode sets sys.stderr/stdout to None — redirect to
# devnull so that logging, print(), and faulthandler don't crash.
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")

import faulthandler
faulthandler.enable()

# Install a no-op _() so that all module-level _("...") calls resolve
# before wx.App exists and i18n.install() can set up the real one.
if not hasattr(builtins, "_"):
    builtins.__dict__["_"] = lambda s: s
if not hasattr(builtins, "N_"):
    builtins.__dict__["N_"] = lambda s: s
if not hasattr(builtins, "ngettext"):
    builtins.__dict__["ngettext"] = lambda s, p, n: s if n == 1 else p

import wx

from accessdr_version import __version__
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

        # Install real gettext translations now that wx.App exists
        from i18n import install
        install(self)

        title = _("AccessDR v{version}").format(version=__version__)
        frame = MainWindow(None, title=title)
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
