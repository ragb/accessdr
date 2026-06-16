"""
ui/dialogs/html_view.py — Accessible in-app HTML viewing via wx.html2.WebView.

``wx.html.HtmlWindow`` is a custom renderer that screen readers cannot read
(NVDA/JAWS see an opaque control).  ``wx.html2.WebView`` with the Edge/WebView2
backend embeds the system browser engine, whose HTML *is* exposed through the
accessibility tree — so the content reads like a normal web page.

This module provides:
  - :func:`make_webview` — create a WebView preferring the accessible Edge
    backend, falling back to the platform default.
  - :class:`HtmlViewFrame` — a modeless, keyboard-navigable viewer used for the
    user guide and other long-form HTML.
"""

from __future__ import annotations

import pathlib
from typing import Optional

import wx
import wx.html2 as _h2


def webview_available() -> bool:
    """True if any WebView backend can be created on this system."""
    try:
        return bool(_h2.WebView.IsBackendAvailable(_h2.WebViewBackendDefault))
    except Exception:   # noqa: BLE001
        return False


def make_webview(parent: wx.Window, name: str = "HTML view") -> _h2.WebView:
    """Create a WebView, preferring the accessible Edge (WebView2) backend."""
    backend = _h2.WebViewBackendDefault
    try:
        if _h2.WebView.IsBackendAvailable(_h2.WebViewBackendEdge):
            backend = _h2.WebViewBackendEdge
    except Exception:   # noqa: BLE001
        pass
    wv = _h2.WebView.New(parent, backend=backend, name=name)
    # We render local/trusted content only — no in-page navigation to the web.
    wv.EnableContextMenu(False)
    return wv


class HtmlViewFrame(wx.Frame):
    """Modeless accessible HTML viewer (Esc closes).

    Pass *path* for a local HTML file or *html* for an inline document.
    """

    def __init__(
        self,
        parent: Optional[wx.Window],
        title: str,
        path: Optional[str] = None,
        html: Optional[str] = None,
        size: tuple[int, int] = (760, 640),
    ) -> None:
        style = wx.DEFAULT_FRAME_STYLE
        if parent is not None:
            style |= wx.FRAME_FLOAT_ON_PARENT  # asserts without a parent
        super().__init__(parent, title=title, style=style)
        self.SetName(title)
        self._web = make_webview(self, name=title)
        if path is not None:
            self._web.LoadURL(pathlib.Path(path).resolve().as_uri())
        elif html is not None:
            self._web.SetPage(html, "")
        self.SetSize(size)
        self.Centre()
        self.Bind(wx.EVT_CHAR_HOOK, self._on_key)
        # Focus the web content so the screen reader enters document/browse mode.
        wx.CallAfter(self._web.SetFocus)

    def _on_key(self, event: wx.KeyEvent) -> None:
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self.Close()
        else:
            event.Skip()
