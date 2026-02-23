"""
ui/dialogs/bookmarks_dialog.py — Bookmark manager dialog.

Displays saved frequency bookmarks, allows loading, adding, and
deleting entries.  Integrates with BookmarkStore for JSON persistence.
"""

from __future__ import annotations

from typing import Callable, Optional

import wx
from accessibility import speech
from config.bookmarks import Bookmark, BookmarkStore
from ui.formatting import fmt_freq, parse_freq


class BookmarksDialog(wx.Frame):
    """Modeless bookmark manager frame."""

    def __init__(
        self,
        parent: wx.Window,
        store: BookmarkStore,
        on_load: Optional[Callable[[Bookmark], None]] = None,
    ) -> None:
        super().__init__(
            parent,
            title=_("Bookmarks"),
            style=wx.DEFAULT_FRAME_STYLE | wx.FRAME_FLOAT_ON_PARENT,
        )
        self.SetName("Bookmarks dialog")
        self._store = store
        self._on_load_cb = on_load
        self._build_ui()
        self.SetSize(480, 420)
        self.Centre()
        self._refresh_list()
        speech.output(_("Bookmarks dialog opened."))

    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        # List
        self._list = wx.ListCtrl(
            panel,
            style=wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.BORDER_SUNKEN,
            name="Bookmarks list",
        )
        self._list.InsertColumn(0, _("Label"), width=200)
        self._list.InsertColumn(1, _("Frequency"), width=130)
        self._list.InsertColumn(2, _("Mode"), width=80)
        sizer.Add(self._list, 1, wx.EXPAND | wx.ALL, 8)

        # Add new bookmark section
        add_box = wx.StaticBox(panel, label=_("Add Bookmark"))
        add_sizer = wx.StaticBoxSizer(add_box, wx.VERTICAL)
        add_grid = wx.FlexGridSizer(cols=2, vgap=6, hgap=8)
        add_grid.AddGrowableCol(1)

        add_grid.Add(wx.StaticText(panel, label=_("Label:")), 0, wx.ALIGN_CENTER_VERTICAL)
        self._label_ctrl = wx.TextCtrl(panel, name="Bookmark label")
        add_grid.Add(self._label_ctrl, 1, wx.EXPAND)

        add_grid.Add(
            wx.StaticText(panel, label=_("Frequency (MHz or kHz):")), 0, wx.ALIGN_CENTER_VERTICAL
        )
        self._freq_ctrl = wx.TextCtrl(panel, name="Bookmark frequency")
        add_grid.Add(self._freq_ctrl, 1, wx.EXPAND)

        add_grid.Add(wx.StaticText(panel, label=_("Mode:")), 0, wx.ALIGN_CENTER_VERTICAL)
        self._mode_ctrl = wx.Choice(
            panel,
            choices=["WFM", "NFM", "AM", "USB", "LSB", "CW", "DSB"],
            name="Bookmark mode",
        )
        self._mode_ctrl.SetSelection(0)
        add_grid.Add(self._mode_ctrl, 1, wx.EXPAND)

        add_sizer.Add(add_grid, 0, wx.EXPAND | wx.ALL, 6)

        add_btn = wx.Button(panel, label=_("Add Bookmark"), name="Add bookmark")
        add_btn.Bind(wx.EVT_BUTTON, self._on_add)
        add_sizer.Add(add_btn, 0, wx.ALL, 4)
        sizer.Add(add_sizer, 0, wx.EXPAND | wx.ALL, 8)

        # Action buttons
        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        load_btn = wx.Button(panel, label=_("Load Selected"), name="Load selected bookmark")
        del_btn = wx.Button(panel, label=_("Delete Selected"), name="Delete selected bookmark")
        close_btn = wx.Button(panel, wx.ID_CLOSE, label=_("Close"))
        load_btn.Bind(wx.EVT_BUTTON, self._on_load_selected)
        del_btn.Bind(wx.EVT_BUTTON, self._on_delete)
        close_btn.Bind(wx.EVT_BUTTON, lambda e: self.Close())
        for b in (load_btn, del_btn, close_btn):
            btn_row.Add(b, 0, wx.RIGHT, 6)
        sizer.Add(btn_row, 0, wx.ALL, 8)

        panel.SetSizer(sizer)
        self._list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._on_load_selected)
        self.Bind(wx.EVT_CHAR_HOOK, self._on_key)

    # ------------------------------------------------------------------

    def _refresh_list(self) -> None:
        self._list.DeleteAllItems()
        for bm in self._store.get_all():
            idx = self._list.InsertItem(self._list.GetItemCount(), bm.label)
            self._list.SetItem(idx, 1, fmt_freq(bm.frequency))
            self._list.SetItem(idx, 2, bm.mode)

    def _on_add(self, _event: wx.CommandEvent) -> None:
        label = self._label_ctrl.GetValue().strip()
        freq_str = self._freq_ctrl.GetValue().strip()
        mode = self._mode_ctrl.GetStringSelection()

        if not label:
            speech.output(_("Please enter a label."))
            return
        try:
            freq_hz = parse_freq(freq_str, default_unit="mhz")
        except ValueError:
            speech.output(_("Invalid frequency."))
            return

        self._store.add(label, freq_hz, mode)
        self._store.save()
        self._refresh_list()
        self._label_ctrl.Clear()
        self._freq_ctrl.Clear()
        speech.output(
            _("Bookmark added: {label}, {freq}, {mode}.").format(
                label=label, freq=fmt_freq(freq_hz), mode=mode
            )
        )

    def _on_load_selected(self, _event) -> None:  # noqa: ANN001
        idx = self._list.GetFirstSelected()
        if idx < 0:
            speech.output(_("No bookmark selected."))
            return
        bm = self._store.get_all()[idx]
        if self._on_load_cb:
            self._on_load_cb(bm)
        speech.output(
            _("Loaded bookmark: {label}, {freq}, {mode}.").format(
                label=bm.label, freq=fmt_freq(bm.frequency), mode=bm.mode
            )
        )

    def _on_delete(self, _event: wx.CommandEvent) -> None:
        idx = self._list.GetFirstSelected()
        if idx < 0:
            speech.output(_("No bookmark selected."))
            return
        bm = self._store.get_all()[idx]
        self._store.remove(idx)
        self._store.save()
        self._refresh_list()
        speech.output(_("Deleted bookmark: {label}.").format(label=bm.label))

    def _on_key(self, event: wx.KeyEvent) -> None:
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self.Close()
        elif event.GetKeyCode() == wx.WXK_RETURN:
            self._on_load_selected(event)
        elif event.GetKeyCode() == wx.WXK_DELETE:
            self._on_delete(event)
        else:
            event.Skip()
