"""
ui/dialogs/scenes_dialog.py — Scene Manager dialog (VFO band presets).

Thin modal frame hosting :class:`ui.panels.scenes_panel.ScenesPanel`.
The working UI lives in the panel so it can also be embedded as a notebook
tab in the main window.
"""

from __future__ import annotations

from typing import Callable, Optional, Tuple

import wx
from accessibility import speech
from config.scenes import Scene, SceneStore
from ui.panels.scenes_panel import ScenesPanel


class ScenesDialog(wx.Frame):
    """Modeless band-scene manager frame."""

    def __init__(
        self,
        parent: wx.Window,
        store: SceneStore,
        on_apply: Optional[Callable[[Scene], None]] = None,
        get_current: Optional[Callable[[], Tuple[int, str, int]]] = None,
        on_changed: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__(
            parent,
            title=_("Scenes"),
            style=wx.DEFAULT_FRAME_STYLE | wx.FRAME_FLOAT_ON_PARENT,
        )
        self.SetName("Scenes dialog")

        sizer = wx.BoxSizer(wx.VERTICAL)
        self._panel = ScenesPanel(
            self, store, on_apply=on_apply,
            get_current=get_current, on_changed=on_changed,
        )
        sizer.Add(self._panel, 1, wx.EXPAND)

        close_btn = wx.Button(self, wx.ID_CLOSE, label=_("Close"))
        close_btn.Bind(wx.EVT_BUTTON, lambda e: self.Close())
        sizer.Add(close_btn, 0, wx.ALL, 8)

        self.SetSizer(sizer)
        self.SetSize(580, 640)
        self.Centre()
        self.Bind(wx.EVT_CHAR_HOOK, self._on_key)
        speech.output(_("Scenes dialog opened."))

    def _on_key(self, event: wx.KeyEvent) -> None:
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self.Close()
        else:
            event.Skip()
