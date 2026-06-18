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
    ).format(
        version_label=_("Version"),
        version=__version__,
        description=_("Accessible SDR radio application for blind and visually impaired users."),
        author_label=_("Author"),
        license_label=_("License"),
        project_label=_("Project"),
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


# In-document (#anchor) links: handle them in JS so they scroll AND move
# screen-reader focus to the target.  Without this the WebView treats a
# fragment click as a navigation that doesn't reliably scroll a SetPage'd
# document.  External http(s) links are left alone (the dialog opens those in
# the system browser).
_ANCHOR_JS = """
<script>
document.addEventListener('click', function (e) {
  var a = e.target.closest && e.target.closest('a[href^="#"]');
  if (!a) return;
  e.preventDefault();
  var id = decodeURIComponent(a.getAttribute('href').slice(1));
  var el = id ? document.getElementById(id) : document.body;
  if (!el) return;
  el.scrollIntoView();
  if (!el.hasAttribute('tabindex')) el.setAttribute('tabindex', '-1');
  el.focus();
}, true);
</script>
"""


def show_user_guide(parent) -> bool:
    """Show the user guide as an accessible HTML dialog.

    Returns False if the guide HTML isn't present (caller may fall back).
    """
    body = _user_guide_body()
    if body is None:
        return False
    from wx_accessible_webview import AccessibleHtmlDialog

    AccessibleHtmlDialog(
        parent, _("User Guide — AccessDR"), body + _ANCHOR_JS, size=(860, 700)
    ).show_modal()
    return True


# ---------------------------------------------------------------------------
# Keyboard shortcuts — grouped by where each key is live, mirroring the
# context sets in ui.keyboard_handler (Global / VFO / Memory).  Labels are
# N_()-marked for extraction and translated at render time.
# ---------------------------------------------------------------------------

SHORTCUT_GROUPS = [
    (N_("Global (any mode)"), [
        (N_("Start / Stop radio"), "F2"),
        (N_("Pause / Resume radio"), "Space"),
        (N_("Mute / Unmute"), "F3"),
        (N_("Volume up / down"), "F11 / F12"),
        (N_("Squelch sensitivity up / down"), "Shift+F11 / Shift+F12"),
        (N_("Squelch on / off"), "Ctrl+Shift+A"),
        (N_("Monitor (hold to defeat squelch)"), "L  (or F4)"),
        (N_("Read signal / status info"), "I"),
        (N_("Toggle VFO / Memory mode"), "V"),
        (N_("Channel up / down (Memory), or frequency step (VFO)"), "Page Up / Page Down"),
        (N_("Toggle recording"), "R"),
        (N_("Quit"), "Alt+F4"),
    ]),
    (N_("VFO — Tuning"), [
        (N_("Report LO frequency"), "Q"),
        (N_("Report listening frequency"), "O"),
        (N_("Enter LO frequency"), "Ctrl+Q"),
        (N_("Enter listening frequency"), "Ctrl+O"),
        (N_("Tune up / down by step"), "Up / Down"),
        (N_("Tune up / down by 10x step"), "Shift+Up / Shift+Down"),
        (N_("Cycle step size"), "S"),
        (N_("Previous / next band"), "[  /  ]"),
    ]),
    (N_("VFO — Modulation (press M, then a letter)"), [
        (N_("Wide FM"), "M  W"),
        (N_("Narrow FM"), "M  N"),
        ("AM", "M  A"),
        ("USB", "M  U"),
        ("LSB", "M  L"),
        ("CW", "M  C"),
        ("DSB", "M  D"),
    ]),
    (N_("VFO — Spectrum and Cursor"), [
        (N_("Speak top peaks"), "F"),
        (N_("Describe spectrum"), "G"),
        (N_("Zoom in / out"), "+  /  -"),
        (N_("Reset zoom"), "Backspace"),
        (N_("Sonification snapshot sweep"), "F5"),
        (N_("Toggle continuous sweep"), "Ctrl+F5"),
        (N_("Probe tone at cursor (hold)"), "Ctrl"),
        (N_("Move cursor while probing"), "Ctrl+Left / Ctrl+Right"),
        (N_("Step cursor left / right"), "Left / Right"),
        (N_("Reset cursor to centre, clear offset"), "C"),
        (N_("Speak cursor frequency and power"), "T"),
        (N_("Tune LO to cursor, clear offset"), "Ctrl+T"),
        (N_("Toggle demod follows cursor"), "Shift+C"),
    ]),
    (N_("Dialogs"), [
        (N_("RF Settings"), "Ctrl+R"),
        (N_("Spectrum Settings"), "Ctrl+S"),
        (N_("Audio Settings"), "Ctrl+D"),
        (N_("Recording Settings"), "Ctrl+E"),
        (N_("Scanner"), "Ctrl+N"),
        (N_("Channels"), "Ctrl+B"),
        (N_("Bands"), "Ctrl+Shift+B"),
        (N_("Remote SDR settings"), "Ctrl+G"),
        (N_("User Guide"), "Ctrl+H"),
        (N_("Keyboard Shortcuts (this window)"), "F1"),
    ]),
    (N_("Scanner (when open)"), [
        (N_("Hold on frequency"), "H"),
        (N_("Skip to next"), "K"),
        (N_("Stop scan"), "Escape"),
    ]),
]


def _shortcuts_body_html() -> str:
    """Render the grouped shortcuts as an HTML body fragment (one table/group)."""
    from html import escape

    out = []
    for group_title, rows in SHORTCUT_GROUPS:
        out.append("<h2>{}</h2>".format(escape(_(group_title))))
        out.append("<table><thead><tr><th>{}</th><th>{}</th></tr></thead><tbody>".format(
            escape(_("Action")), escape(_("Key(s)"))
        ))
        for label, key in rows:
            out.append("<tr><td>{}</td><td><kbd>{}</kbd></td></tr>".format(
                escape(_(label)), escape(key)
            ))
        out.append("</tbody></table>")
    return "\n".join(out)


def show_shortcuts(parent) -> None:
    """Show the keyboard-shortcut reference as an accessible HTML dialog."""
    from wx_accessible_webview import AccessibleHtmlDialog

    AccessibleHtmlDialog(
        parent, _("Keyboard Shortcuts — AccessDR"),
        _shortcuts_body_html(), size=(720, 640),
    ).show_modal()
