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
        self._pending_overrides: dict = {}   # mode overrides for the form
        self._build_ui()
        self._refresh_maps()
        self._refresh_list()
        self._refresh_bw_choices("WFM")
        self._update_ms_btn()

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
        new_map_btn.Bind(wx.EVT_BUTTON, self._on_new_map)
        del_map_btn.Bind(wx.EVT_BUTTON, self._on_delete_map)
        map_sizer.Add(self._map_choice, 1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        for b in (new_map_btn, del_map_btn):
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
        self._list.InsertColumn(3, _("Modulation"), width=80)
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

        grid.Add(wx.StaticText(self, label=_("Modulation:")), 0, wx.ALIGN_CENTER_VERTICAL)
        mode_box = wx.BoxSizer(wx.HORIZONTAL)
        self._mode_ctrl = wx.Choice(self, choices=MODES, name="Channel modulation")
        self._mode_ctrl.SetSelection(0)
        self._mode_ctrl.Bind(wx.EVT_CHOICE, self._on_mode_change)
        self._ms_btn = wx.Button(self, label=_("Settings…"), name="Channel modulation settings")
        self._ms_btn.Bind(wx.EVT_BUTTON, self._on_mode_settings)
        mode_box.Add(self._mode_ctrl, 0, wx.RIGHT, 6)
        mode_box.Add(self._ms_btn, 0)
        grid.Add(mode_box, 0)

        grid.Add(wx.StaticText(self, label=_("Bandwidth:")), 0, wx.ALIGN_CENTER_VERTICAL)
        self._bw_ctrl = wx.Choice(self, name="Channel bandwidth")
        grid.Add(self._bw_ctrl, 0)

        grid.Add(wx.StaticText(self, label=_("Squelch sensitivity (0–10, optional):")), 0, wx.ALIGN_CENTER_VERTICAL)
        self._squelch_ctrl = wx.TextCtrl(self, name="Channel squelch sensitivity")
        grid.Add(self._squelch_ctrl, 0)

        form_sizer.Add(grid, 0, wx.EXPAND | wx.ALL, 6)

        form_btns = wx.BoxSizer(wx.HORIZONTAL)
        save_btn = wx.Button(self, label=_("Save Channel"), name="Save channel")
        vfo_btn = wx.Button(self, label=_("Store Current VFO"), name="Store current VFO")
        save_btn.Bind(wx.EVT_BUTTON, self._on_save_channel)
        vfo_btn.Bind(wx.EVT_BUTTON, self._on_store_vfo)
        for b in (save_btn, vfo_btn):
            form_btns.Add(b, 0, wx.RIGHT, 6)
        form_sizer.Add(form_btns, 0, wx.ALL, 4)
        sizer.Add(form_sizer, 0, wx.EXPAND | wx.ALL, 8)

        # --- Action buttons (Load / Move / Delete / Import / Export) ---
        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        load_btn = wx.Button(self, label=_("Load Selected"), name="Load selected channel")
        up_btn = wx.Button(self, label=_("Move Up"), name="Move channel up")
        down_btn = wx.Button(self, label=_("Move Down"), name="Move channel down")
        del_btn = wx.Button(self, label=_("Delete Selected"), name="Delete selected channel")
        imp_btn = wx.Button(self, label=_("Import…"), name="Import map")
        exp_btn = wx.Button(self, label=_("Export…"), name="Export map")
        load_btn.Bind(wx.EVT_BUTTON, self._on_load_selected)
        up_btn.Bind(wx.EVT_BUTTON, lambda e: self._on_move(-1))
        down_btn.Bind(wx.EVT_BUTTON, lambda e: self._on_move(+1))
        del_btn.Bind(wx.EVT_BUTTON, self._on_delete)
        imp_btn.Bind(wx.EVT_BUTTON, self._on_import)
        exp_btn.Bind(wx.EVT_BUTTON, self._on_export)
        for b in (load_btn, up_btn, down_btn, del_btn, imp_btn, exp_btn):
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

    # Per-mode override attributes carried with the channel.
    _OVERRIDE_KEYS = (
        "nfm_deviation", "nfm_ctcss_notch", "wfm_deemphasis",
        "wfm_stereo_mode", "wfm_hiblend_enabled", "wfm_rds_enabled",
    )

    def _update_ms_btn(self) -> None:
        """Enable the Settings… button only if the form modulation has settings."""
        from config.mode_params import params_for
        if hasattr(self, "_ms_btn"):
            self._ms_btn.Enable(bool(params_for(self._mode_ctrl.GetStringSelection())))

    def _on_mode_change(self, _event: wx.CommandEvent) -> None:
        self._refresh_bw_choices(self._mode_ctrl.GetStringSelection())
        self._pending_overrides = {}     # overrides are mode-specific
        self._update_ms_btn()

    def _on_select(self, _event) -> None:  # noqa: ANN001
        ch = self._selected_channel()
        if ch is None:
            return
        self._num_ctrl.SetValue(ch.number)
        self._label_ctrl.SetValue(ch.label)
        self._freq_ctrl.SetValue(fmt_freq(ch.frequency))
        self._mode_ctrl.SetStringSelection(ch.mode)
        self._refresh_bw_choices(ch.mode, ch.bandwidth)
        self._squelch_ctrl.SetValue("" if ch.squelch_sensitivity is None else str(ch.squelch_sensitivity))
        self._pending_overrides = {k: getattr(ch, k) for k in self._OVERRIDE_KEYS}
        self._update_ms_btn()

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
        sq_text = self._squelch_ctrl.GetValue().strip()
        try:
            squelch_sensitivity = int(sq_text) if sq_text else None
        except ValueError:
            speech.output(_("Invalid squelch sensitivity."))
            return
        # Upsert by number.
        existing = next((c for c in cmap.channels if c.number == number), None)
        if existing is None:
            existing = Channel(number, label, freq_hz, mode, bandwidth)
            cmap.channels.append(existing)
        else:
            existing.label = label
            existing.frequency = freq_hz
            existing.mode = mode
            existing.bandwidth = bandwidth
        existing.squelch_sensitivity = squelch_sensitivity
        # Carry the modulation overrides edited via the Settings… button.
        for key, val in self._pending_overrides.items():
            setattr(existing, key, val)
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
        self._squelch_ctrl.SetValue("")
        self._pending_overrides = {}
        self._update_ms_btn()
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

    def _select_row(self, idx: int) -> None:
        if 0 <= idx < self._list.GetItemCount():
            self._list.Select(idx)
            self._list.Focus(idx)
            self._list.EnsureVisible(idx)

    def _on_move(self, direction: int) -> None:
        """Reorder by swapping the selected channel's number with its neighbour."""
        ch = self._selected_channel()
        cmap = self._store.active_map()
        if ch is None or cmap is None:
            speech.output(_("No channel selected."))
            return
        chans = cmap.sorted_channels()
        idx = chans.index(ch)
        tgt = idx + direction
        if not 0 <= tgt < len(chans):
            speech.output(_("Already at the edge."))
            return
        other = chans[tgt]
        ch.number, other.number = other.number, ch.number
        self._refresh_list()
        self._notify_changed()
        self._select_row(tgt)
        speech.output(_("Channel {n}.").format(n=ch.number))

    def _on_mode_settings(self, _event: wx.CommandEvent) -> None:
        import types
        from config.mode_params import params_for
        from ui.dialogs.mode_settings_dialog import ModeSettingsDialog
        mode = self._mode_ctrl.GetStringSelection()
        params = params_for(mode)
        if not params:
            speech.output(_("No settings for {mode}.").format(mode=mode))
            return
        target = types.SimpleNamespace(**{p.key: self._pending_overrides.get(p.key) for p in params})
        dlg = ModeSettingsDialog(
            self, mode, target, is_override=True,
            title=_("{mode} settings").format(mode=mode),
        )
        if dlg.ShowModal() == wx.ID_OK:
            for p in params:
                self._pending_overrides[p.key] = getattr(target, p.key)
            speech.output(_("Modulation settings updated. Save the channel to apply."))
        dlg.Destroy()

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
