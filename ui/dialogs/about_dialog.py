"""
ui/dialogs/about_dialog.py — About dialog for AccessDR.

Displays application name, version, author, license, project URL,
and key dependencies in an HTML panel.
"""

from __future__ import annotations

import wx

from accessdr_version import __version__
from ui.dialogs.html_view import make_webview, webview_available


class AboutDialog(wx.Dialog):
    """Modal About dialog showing application information."""

    def __init__(self, parent: wx.Window) -> None:
        super().__init__(
            parent,
            id=wx.ID_ANY,
            title=_("About AccessDR"),
            style=wx.DEFAULT_DIALOG_STYLE,
        )
        self.SetName("About AccessDR")
        self._build_ui()
        self.Fit()
        self.Centre()

    def _build_ui(self) -> None:
        sizer = wx.BoxSizer(wx.VERTICAL)

        html = self._build_html()
        if webview_available():
            # Accessible HTML via wx.html2.WebView (Edge/WebView2) — the screen
            # reader reads the rendered page natively, no manual announcement.
            view = make_webview(self, name="About AccessDR")
            view.SetPage(html, "")
            view.SetMinSize((440, 320))
        else:
            import wx.html as _wxhtml
            view = _wxhtml.HtmlWindow(self, size=(440, 320))
            view.SetBorders(10)
            view.SetPage(html)
        sizer.Add(view, 1, wx.EXPAND | wx.ALL, 8)

        btn_sizer = wx.StdDialogButtonSizer()
        ok_btn = wx.Button(self, wx.ID_OK)
        ok_btn.SetDefault()
        btn_sizer.AddButton(ok_btn)
        btn_sizer.Realize()
        sizer.Add(btn_sizer, 0, wx.EXPAND | wx.ALL, 8)

        self.SetSizer(sizer)
        self.Bind(wx.EVT_BUTTON, self._on_ok, id=wx.ID_OK)
        self.Bind(wx.EVT_CHAR_HOOK, self._on_key)

    def _build_html(self) -> str:
        return (
            "<html><body>"
            "<h2>AccessDR</h2>"
            "<p><b>{version_label}:</b> {version}</p>"
            "<p>{description}</p>"
            "<p><b>{author_label}:</b> Rui Batista</p>"
            "<p><b>{license_label}:</b> "
            '<a href="https://github.com/ragb/accessdr/blob/master/LICENSE">MIT</a></p>'
            "<p><b>{project_label}:</b> "
            '<a href="https://github.com/ragb/accessdr">github.com/ragb/accessdr</a></p>'
            "<p><b>{deps_label}:</b><br>"
            "wxPython, NumPy, SciPy, pyrtlsdr, sounddevice, accessible_output2</p>"
            "</body></html>"
        ).format(
            version_label=_("Version"),
            version=__version__,
            description=_("Accessible SDR radio application for blind and visually impaired users."),
            author_label=_("Author"),
            license_label=_("License"),
            project_label=_("Project"),
            deps_label=_("Dependencies"),
        )

    def _on_ok(self, _event: wx.CommandEvent) -> None:
        self.EndModal(wx.ID_OK)

    def _on_key(self, event: wx.KeyEvent) -> None:
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self.EndModal(wx.ID_OK)
        else:
            event.Skip()
