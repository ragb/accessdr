"""
ui/dialogs/channels_dialog.py — Channel Manager dialog (MR mode memories).

Thin modal frame hosting :class:`ui.panels.channels_panel.ChannelsPanel`.
The working UI lives in the panel so it can also be embedded as a notebook
tab in the main window.
"""

from __future__ import annotations

from typing import Callable, Optional, Tuple

import wx
from accessibility import speech
from config.channels import Channel, ChannelMapStore
from ui.panels.channels_panel import ChannelsPanel, bw_label  # noqa: F401 (re-export)


class ChannelsDialog(wx.Frame):
    """Modeless channel-memory manager frame."""

    def __init__(
        self,
        parent: wx.Window,
        store: ChannelMapStore,
        on_load: Optional[Callable[[Channel], None]] = None,
        get_current: Optional[Callable[[], Tuple[int, str, int]]] = None,
        on_changed: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__(
            parent,
            title=_("Channels"),
            style=wx.DEFAULT_FRAME_STYLE | wx.FRAME_FLOAT_ON_PARENT,
        )
        self.SetName("Channels dialog")

        sizer = wx.BoxSizer(wx.VERTICAL)
        self._panel = ChannelsPanel(
            self, store, on_load=on_load,
            get_current=get_current, on_changed=on_changed,
        )
        sizer.Add(self._panel, 1, wx.EXPAND)

        close_btn = wx.Button(self, wx.ID_CLOSE, label=_("Close"))
        close_btn.Bind(wx.EVT_BUTTON, lambda e: self.Close())
        sizer.Add(close_btn, 0, wx.ALL, 8)

        self.SetSizer(sizer)
        self.SetSize(560, 560)
        self.Centre()
        self.Bind(wx.EVT_CHAR_HOOK, self._on_key)
        speech.output(_("Channels dialog opened."))

    def _on_key(self, event: wx.KeyEvent) -> None:
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self.Close()
        else:
            event.Skip()
