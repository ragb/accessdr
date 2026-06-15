"""
ui/panels/channels_panel.py — Channel Manager content panel (MR mode).

Holds the working UI for managing numbered channel slots grouped into
named channel maps: switch/create/delete maps, add/edit (upsert by
number)/delete channels, store the current VFO to a slot, load a channel,
and import/export a map as JSON.  Hostable in a dialog or a notebook tab.
"""

from __future__ import annotations

import json
from typing import Callable, Optional, Tuple

import wx
from accessibility import speech
from config.channels import Channel, ChannelMap, ChannelMapStore
from config.modes import BW_OPTIONS, MODES
from ui.formatting import fmt_freq, parse_freq


def bw_label(mode: str, value: int) -> str:
    """Human label for a bandwidth value, falling back to a kHz string."""
    for bw, label in BW_OPTIONS.get(mode, []):
        if bw == value:
            return label
    return f"{value / 1000:.1f} kHz"


class ChannelsPanel(wx.Panel):
    """Channel-memory management controls (no frame chrome)."""

    def __init__(
        self,
        parent: wx.Window,
        store: ChannelMapStore,
        on_load: Optional[Callable[[Channel], None]] = None,
        get_current: Optional[Callable[[], Tuple[int, str, int]]] = None,
        on_changed: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__(parent)
        self.SetName("Channels panel")
        self._store = store
        self._on_load_cb = on_load
        self._get_current_cb = get_current
        self._on_changed_cb = on_changed
        self._build_ui()
        self._refresh_maps()
        self._refresh_list()
        self._refresh_bw_choices("WFM")

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        sizer = wx.BoxSizer(wx.VERTICAL)

        # --- Map selector row ---
        map_box = wx.StaticBox(self, label=_("Channel Map"))
        map_sizer = wx.StaticBoxSizer(map_box, wx.HORIZONTAL)
        self._map_choice = wx.Choice(self, name="Channel map")
        self._map_choice.Bind(wx.EVT_CHOICE, self._on_map_change)
        new_map_btn = wx.Button(self, label=_("New Map"), name="New map")
        del_map_btn = wx.Button(self, label=_("Delete Map"), name="Delete map")
        imp_btn = wx.Button(self, label=_("Import…"), name="Import map")
        exp_btn = wx.Button(self, label=_("Export…"), name="Export map")
        new_map_btn.Bind(wx.EVT_BUTTON, self._on_new_map)
        del_map_btn.Bind(wx.EVT_BUTTON, self._on_delete_map)
        imp_btn.Bind(wx.EVT_BUTTON, self._on_import)
        exp_btn.Bind(wx.EVT_BUTTON, self._on_export)
        map_sizer.Add(self._map_choice, 1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        for b in (new_map_btn, del_map_btn, imp_btn, exp_btn):
            map_sizer.Add(b, 0, wx.RIGHT, 4)
        sizer.Add(map_sizer, 0, wx.EXPAND | wx.ALL, 8)

        # --- Channel list ---
        self._list = wx.ListCtrl(
            self,
            style=wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.BORDER_SUNKEN,
            name="Channels list",
        )
        self._list.InsertColumn(0, _("Ch"), width=50)
        self._list.InsertColumn(1, _("Label"), width=200)
        self._list.InsertColumn(2, _("Frequency"), width=130)
        self._list.InsertColumn(3, _("Mode"), width=70)
        self._list.InsertColumn(4, _("Bandwidth"), width=90)
        sizer.Add(self._list, 1, wx.EXPAND | wx.ALL, 8)

        # --- Add / edit form ---
        form_box = wx.StaticBox(self, label=_("Channel"))
        form_sizer = wx.StaticBoxSizer(form_box, wx.VERTICAL)
        grid = wx.FlexGridSizer(cols=2, vgap=6, hgap=8)
        grid.AddGrowableCol(1)

        grid.Add(wx.StaticText(self, label=_("Number:")), 0, wx.ALIGN_CENTER_VERTICAL)
        self._num_ctrl = wx.SpinCtrl(self, min=1, max=999, name="Channel number")
        grid.Add(self._num_ctrl, 0)

        grid.Add(wx.StaticText(self, label=_("Label:")), 0, wx.ALIGN_CENTER_VERTICAL)
        self._label_ctrl = wx.TextCtrl(self, name="Channel label")
        grid.Add(self._label_ctrl, 1, wx.EXPAND)

        grid.Add(
            wx.StaticText(self, label=_("Frequency (MHz or kHz):")),
            0, wx.ALIGN_CENTER_VERTICAL,
        )
        self._freq_ctrl = wx.TextCtrl(self, name="Channel frequency")
        grid.Add(self._freq_ctrl, 1, wx.EXPAND)

        grid.Add(wx.StaticText(self, label=_("Mode:")), 0, wx.ALIGN_CENTER_VERTICAL)
        self._mode_ctrl = wx.Choice(self, choices=MODES, name="Channel mode")
        self._mode_ctrl.SetSelection(0)
        self._mode_ctrl.Bind(wx.EVT_CHOICE, self._on_mode_change)
        grid.Add(self._mode_ctrl, 0)

        grid.Add(wx.StaticText(self, label=_("Bandwidth:")), 0, wx.ALIGN_CENTER_VERTICAL)
        self._bw_ctrl = wx.Choice(self, name="Channel bandwidth")
        grid.Add(self._bw_ctrl, 0)

        form_sizer.Add(grid, 0, wx.EXPAND | wx.ALL, 6)

        form_btns = wx.BoxSizer(wx.HORIZONTAL)
        save_btn = wx.Button(self, label=_("Save Channel"), name="Save channel")
        vfo_btn = wx.Button(self, label=_("Store Current VFO"), name="Store current VFO")
        save_btn.Bind(wx.EVT_BUTTON, self._on_save_channel)
        vfo_btn.Bind(wx.EVT_BUTTON, self._on_store_vfo)
        form_btns.Add(save_btn, 0, wx.RIGHT, 6)
        form_btns.Add(vfo_btn, 0)
        form_sizer.Add(form_btns, 0, wx.ALL, 4)
        sizer.Add(form_sizer, 0, wx.EXPAND | wx.ALL, 8)

        # --- Action buttons (Load / Delete) ---
        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        load_btn = wx.Button(self, label=_("Load Selected"), name="Load selected channel")
        del_btn = wx.Button(self, label=_("Delete Selected"), name="Delete selected channel")
        load_btn.Bind(wx.EVT_BUTTON, self._on_load_selected)
        del_btn.Bind(wx.EVT_BUTTON, self._on_delete)
        for b in (load_btn, del_btn):
            btn_row.Add(b, 0, wx.RIGHT, 6)
        sizer.Add(btn_row, 0, wx.ALL, 8)

        self.SetSizer(sizer)
        self._list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._on_load_selected)
        self._list.Bind(wx.EVT_LIST_ITEM_SELECTED, self._on_select)
        self._refresh_bw_choices("WFM")

    # ------------------------------------------------------------------
    # Refresh helpers
    # ------------------------------------------------------------------

    def _refresh_maps(self) -> None:
        self._map_choice.Set([m.name for m in self._store.maps])
        self._map_choice.SetSelection(self._store.active)

    def _refresh_list(self) -> None:
        self._list.DeleteAllItems()
        cmap = self._store.active_map()
        if cmap is None:
            return
        for ch in cmap.sorted_channels():
            idx = self._list.InsertItem(self._list.GetItemCount(), str(ch.number))
            self._list.SetItem(idx, 1, ch.label)
            self._list.SetItem(idx, 2, fmt_freq(ch.frequency))
            self._list.SetItem(idx, 3, ch.mode)
            self._list.SetItem(idx, 4, bw_label(ch.mode, ch.bandwidth))

    def _refresh_bw_choices(self, mode: str, select_value: Optional[int] = None) -> None:
        options = BW_OPTIONS.get(mode, [])
        self._bw_ctrl.Set([label for _bw, label in options])
        if options:
            sel = 0
            if select_value is not None:
                for i, (bw, _label) in enumerate(options):
                    if bw == select_value:
                        sel = i
                        break
            self._bw_ctrl.SetSelection(sel)

    def _selected_channel(self) -> Optional[Channel]:
        idx = self._list.GetFirstSelected()
        cmap = self._store.active_map()
        if idx < 0 or cmap is None:
            return None
        return cmap.sorted_channels()[idx]

    def _form_bandwidth(self) -> int:
        mode = self._mode_ctrl.GetStringSelection()
        options = BW_OPTIONS.get(mode, [])
        sel = self._bw_ctrl.GetSelection()
        if 0 <= sel < len(options):
            return options[sel][0]
        return options[0][0] if options else 0

    def _notify_changed(self) -> None:
        self._store.save()
        if self._on_changed_cb:
            self._on_changed_cb()

    # ------------------------------------------------------------------
    # Map events
    # ------------------------------------------------------------------

    def _on_map_change(self, _event: wx.CommandEvent) -> None:
        self._store.set_active(self._map_choice.GetSelection())
        self._refresh_list()
        self._notify_changed()
        cmap = self._store.active_map()
        if cmap is not None:
            speech.output(_("Map {name}").format(name=cmap.name))

    def _on_new_map(self, _event: wx.CommandEvent) -> None:
        dlg = wx.TextEntryDialog(self, _("Map name:"), _("New Channel Map"))
        if dlg.ShowModal() == wx.ID_OK:
            name = dlg.GetValue().strip()
            if name:
                self._store.maps.append(ChannelMap(name))
                self._store.set_active(len(self._store.maps) - 1)
                self._refresh_maps()
                self._refresh_list()
                self._notify_changed()
                speech.output(_("Map {name} created.").format(name=name))
        dlg.Destroy()

    def _on_delete_map(self, _event: wx.CommandEvent) -> None:
        if len(self._store.maps) <= 1:
            speech.output(_("Cannot delete the last map."))
            return
        cmap = self._store.active_map()
        del self._store.maps[self._store.active]
        self._store.set_active(self._store.active)  # clamp
        self._refresh_maps()
        self._refresh_list()
        self._notify_changed()
        if cmap is not None:
            speech.output(_("Map {name} deleted.").format(name=cmap.name))

    # ------------------------------------------------------------------
    # Channel events
    # ------------------------------------------------------------------

    def _on_mode_change(self, _event: wx.CommandEvent) -> None:
        self._refresh_bw_choices(self._mode_ctrl.GetStringSelection())

    def _on_select(self, _event) -> None:  # noqa: ANN001
        ch = self._selected_channel()
        if ch is None:
            return
        self._num_ctrl.SetValue(ch.number)
        self._label_ctrl.SetValue(ch.label)
        self._freq_ctrl.SetValue(fmt_freq(ch.frequency))
        self._mode_ctrl.SetStringSelection(ch.mode)
        self._refresh_bw_choices(ch.mode, ch.bandwidth)

    def _on_save_channel(self, _event: wx.CommandEvent) -> None:
        cmap = self._store.active_map()
        if cmap is None:
            return
        label = self._label_ctrl.GetValue().strip()
        if not label:
            speech.output(_("Please enter a label."))
            return
        try:
            freq_hz = parse_freq(self._freq_ctrl.GetValue().strip(), default_unit="mhz")
        except ValueError:
            speech.output(_("Invalid frequency."))
            return
        number = self._num_ctrl.GetValue()
        mode = self._mode_ctrl.GetStringSelection()
        bandwidth = self._form_bandwidth()
        # Upsert by number.
        existing = next((c for c in cmap.channels if c.number == number), None)
        if existing is not None:
            existing.label = label
            existing.frequency = freq_hz
            existing.mode = mode
            existing.bandwidth = bandwidth
        else:
            cmap.channels.append(Channel(number, label, freq_hz, mode, bandwidth))
        self._refresh_list()
        self._notify_changed()
        speech.output(
            _("Saved channel {n}, {label}.").format(n=number, label=label)
        )

    def _on_store_vfo(self, _event: wx.CommandEvent) -> None:
        cmap = self._store.active_map()
        if cmap is None or self._get_current_cb is None:
            return
        freq_hz, mode, bandwidth = self._get_current_cb()
        number = cmap.next_number()
        self._num_ctrl.SetValue(number)
        self._label_ctrl.SetValue("")
        self._freq_ctrl.SetValue(fmt_freq(freq_hz))
        if mode in MODES:
            self._mode_ctrl.SetStringSelection(mode)
        self._refresh_bw_choices(mode, bandwidth)
        self._label_ctrl.SetFocus()
        speech.output(
            _("Storing {freq} to channel {n}. Enter a label and save.").format(
                freq=fmt_freq(freq_hz), n=number
            )
        )

    def _on_load_selected(self, _event) -> None:  # noqa: ANN001
        ch = self._selected_channel()
        if ch is None:
            speech.output(_("No channel selected."))
            return
        if self._on_load_cb:
            self._on_load_cb(ch)

    def _on_delete(self, _event) -> None:  # noqa: ANN001
        ch = self._selected_channel()
        cmap = self._store.active_map()
        if ch is None or cmap is None:
            speech.output(_("No channel selected."))
            return
        cmap.channels.remove(ch)
        self._refresh_list()
        self._notify_changed()
        speech.output(_("Deleted channel {n}.").format(n=ch.number))

    # ------------------------------------------------------------------
    # Import / export (single map as JSON)
    # ------------------------------------------------------------------

    def _on_export(self, _event: wx.CommandEvent) -> None:
        cmap = self._store.active_map()
        if cmap is None:
            return
        with wx.FileDialog(
            self, _("Export channel map"), defaultFile=f"{cmap.name}.json",
            wildcard="JSON (*.json)|*.json",
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
        ) as fd:
            if fd.ShowModal() != wx.ID_OK:
                return
            payload = {
                "name": cmap.name,
                "channels": [vars(c) for c in cmap.sorted_channels()],
            }
            try:
                with open(fd.GetPath(), "w", encoding="utf-8") as fh:
                    json.dump(payload, fh, indent=2)
                speech.output(_("Map exported."))
            except OSError as exc:
                speech.output(_("Export failed: {err}").format(err=exc))

    def _on_import(self, _event: wx.CommandEvent) -> None:
        with wx.FileDialog(
            self, _("Import channel map"),
            wildcard="JSON (*.json)|*.json",
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
        ) as fd:
            if fd.ShowModal() != wx.ID_OK:
                return
            try:
                with open(fd.GetPath(), "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                cmap = ChannelMap(
                    name=data.get("name", _("Imported")),
                    channels=[Channel(**c) for c in data.get("channels", [])],
                )
            except (OSError, json.JSONDecodeError, TypeError, KeyError) as exc:
                speech.output(_("Import failed: {err}").format(err=exc))
                return
        self._store.maps.append(cmap)
        self._store.set_active(len(self._store.maps) - 1)
        self._refresh_maps()
        self._refresh_list()
        self._notify_changed()
        speech.output(_("Map {name} imported.").format(name=cmap.name))
