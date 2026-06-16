"""
ui/dialogs/accessible_help.py — About box and User Guide as accessible HTML.

Uses the ``wx-accessible-webview`` package, which renders semantic HTML with
ARIA into a ``wx.html2.WebView`` so screen readers (NVDA *and* JAWS) read it as
a web page — and falls back to a read-only text control when no WebView backend
is available.

The dialogs create the WebView synchronously, so callers should invoke these
via ``wx.CallAfter`` (off the menu/key handler) to avoid the WebView2 COM
"input-synchronous call" guard.
"""

from __future__ import annotations

import os
import re

from accessdr_version import __version__
from config.paths import help_dir


def _about_body_html() -> str:
    return (
        "<h1>AccessDR</h1>"
        "<p><strong>{version_label}:</strong> {version}</p>"
        "<p>{description}</p>"
        "<p><strong>{author_label}:</strong> Rui Batista</p>"
        "<p><strong>{license_label}:</strong> "
        '<a href="https://github.com/ragb/accessdr/blob/master/LICENSE">MIT</a></p>'
        "<p><strong>{project_label}:</strong> "
        '<a href="https://github.com/ragb/accessdr">github.com/ragb/accessdr</a></p>'
        "<p><strong>{deps_label}:</strong><br>"
        "wxPython, NumPy, SciPy, pyrtlsdr, sounddevice, accessible_output2</p>"
    ).format(
        version_label=_("Version"),
        version=__version__,
        description=_("Accessible SDR radio application for blind and visually impaired users."),
        author_label=_("Author"),
        license_label=_("License"),
        project_label=_("Project"),
        deps_label=_("Dependencies"),
    )


def show_about(parent) -> None:
    """Show the About box as an accessible HTML dialog."""
    from wx_accessible_webview import AccessibleHtmlDialog

    AccessibleHtmlDialog(
        parent, _("About AccessDR"), _about_body_html(), size=(480, 380)
    ).show_modal()


def _user_guide_body() -> str | None:
    """Return the user-guide body HTML, or None if the guide isn't built."""
    path = os.path.join(help_dir(), "user-guide.html")
    if not os.path.isfile(path):
        return None
    try:
        text = open(path, encoding="utf-8").read()
    except OSError:
        return None
    # AccessibleHtmlDialog wraps the fragment in its own document, so hand it
    # the <body> contents rather than the whole standalone page.
    match = re.search(r"<body[^>]*>(.*)</body>", text, re.S | re.I)
    return match.group(1) if match else text


def show_user_guide(parent) -> bool:
    """Show the user guide as an accessible HTML dialog.

    Returns False if the guide HTML isn't present (caller may fall back).
    """
    body = _user_guide_body()
    if body is None:
        return False
    from wx_accessible_webview import AccessibleHtmlDialog

    AccessibleHtmlDialog(
        parent, _("User Guide — AccessDR"), body, size=(860, 700)
    ).show_modal()
    return True
