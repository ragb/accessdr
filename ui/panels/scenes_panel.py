"""
ui/panels/scenes_panel.py — Bands manager content panel (VFO band presets).

A *band* is a VFO preset (frequency range + demod setup). Bands are shown
in a tree grouped by service category (Broadcast, Shortwave, Amateur, …),
which keeps a large band plan navigable — and tree controls are read
naturally by screen readers (level, expand/collapse).

Hostable in a dialog (the Bands manager) or, in principle, a tab.
"""

from __future__ import annotations

import json
from typing import Callable, Optional, Tuple

import wx
from accessibility import speech
from config.modes import BW_OPTIONS, MODES, STEP_LABELS, STEPS
from config.scenes import Scene, SceneStore
from ui.formatting import fmt_freq, parse_freq

# Step choice: a leading "follow tuning step" entry maps to step == 0.
_STEP_VALUES = [0] + STEPS
_DEEMPH_CHOICES = [("", N_("(no override)")), ("50", "50 µs"), ("75", "75 µs")]
_UNGROUPED = N_("General")


def _parse_opt_freq(text: str) -> Optional[int]:
    """Parse an optional frequency field; blank → None."""
    text = text.strip()
    if not text:
        return None
    return parse_freq(text, default_unit="mhz")


def _group_order() -> list:
    """Display order for band groups: General, then the service order."""
    from config.bands import GROUP_ORDER
    return [_UNGROUPED] + list(GROUP_ORDER)


class ScenesPanel(wx.Panel):
    """Band-preset management controls (tree + edit form), no frame chrome."""

    def __init__(
        self,
        parent: wx.Window,
        store: SceneStore,
        on_apply: Optional[Callable[[Scene], None]] = None,
        get_current: Optional[Callable[[], Tuple[int, str, int]]] = None,
        on_changed: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__(parent)
        self.SetName("Bands panel")
        self._store = store
        self._on_apply_cb = on_apply
        self._get_current_cb = get_current
        self._on_changed_cb = on_changed
        self._build_ui()
        self._refresh_tree()
        self._refresh_bw_choices("WFM")

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        sizer = wx.BoxSizer(wx.VERTICAL)

        # Band tree (grouped by service)
        self._tree = wx.TreeCtrl(
            self,
            style=wx.TR_HIDE_ROOT | wx.TR_HAS_BUTTONS | wx.TR_SINGLE
            | wx.TR_FULL_ROW_HIGHLIGHT | wx.BORDER_SUNKEN,
            name="Bands tree",
        )
        self._root = self._tree.AddRoot("bands")
        sizer.Add(self._tree, 1, wx.EXPAND | wx.ALL, 8)

        # Edit form
        form_box = wx.StaticBox(self, label=_("Band"))
        form_sizer = wx.StaticBoxSizer(form_box, wx.VERTICAL)
        grid = wx.FlexGridSizer(cols=2, vgap=6, hgap=8)
        grid.AddGrowableCol(1)

        def _row(label_text: str, ctrl: wx.Window) -> None:
            grid.Add(wx.StaticText(self, label=label_text), 0, wx.ALIGN_CENTER_VERTICAL)
            grid.Add(ctrl, 1, wx.EXPAND)

        self._name_ctrl = wx.TextCtrl(self, name="Band name")
        _row(_("Name:"), self._name_ctrl)

        self._group_ctrl = wx.ComboBox(self, choices=_group_order(), name="Band group")
        _row(_("Group:"), self._group_ctrl)

        self._start_ctrl = wx.TextCtrl(self, name="Band start")
        _row(_("Band start (MHz, blank = unbounded):"), self._start_ctrl)

        self._end_ctrl = wx.TextCtrl(self, name="Band end")
        _row(_("Band end (MHz, blank = unbounded):"), self._end_ctrl)

        self._mode_ctrl = wx.Choice(self, choices=MODES, name="Band mode")
        self._mode_ctrl.SetSelection(0)
        self._mode_ctrl.Bind(wx.EVT_CHOICE, self._on_mode_change)
        _row(_("Mode:"), self._mode_ctrl)

        self._bw_ctrl = wx.Choice(self, name="Band bandwidth")
        _row(_("Bandwidth:"), self._bw_ctrl)

        self._step_ctrl = wx.Choice(
            self,
            choices=[_("Follow tuning step")] + [_(s) for s in STEP_LABELS],
            name="Band step",
        )
        self._step_ctrl.SetSelection(0)
        _row(_("Tuning step:"), self._step_ctrl)

        self._default_ctrl = wx.TextCtrl(self, name="Default frequency")
        _row(_("Default frequency (MHz, optional):"), self._default_ctrl)

        form_sizer.Add(grid, 0, wx.EXPAND | wx.ALL, 6)

        # Advanced (optional demod overrides)
        adv_box = wx.StaticBox(self, label=_("Advanced overrides (optional)"))
        adv_sizer = wx.StaticBoxSizer(adv_box, wx.VERTICAL)
        adv_grid = wx.FlexGridSizer(cols=2, vgap=6, hgap=8)
        adv_grid.AddGrowableCol(1)

        def _adv_row(label_text: str, ctrl: wx.Window) -> None:
            adv_grid.Add(wx.StaticText(self, label=label_text), 0, wx.ALIGN_CENTER_VERTICAL)
            adv_grid.Add(ctrl, 1, wx.EXPAND)

        self._nfm_dev_ctrl = wx.TextCtrl(self, name="NFM deviation override")
        _adv_row(_("NFM deviation (Hz):"), self._nfm_dev_ctrl)

        self._deemph_ctrl = wx.Choice(
            self, choices=[lbl for _v, lbl in _DEEMPH_CHOICES],
            name="WFM de-emphasis override",
        )
        self._deemph_ctrl.SetSelection(0)
        _adv_row(_("WFM de-emphasis:"), self._deemph_ctrl)

        self._squelch_ctrl = wx.TextCtrl(self, name="Squelch override")
        _adv_row(_("Squelch (dBm):"), self._squelch_ctrl)

        adv_sizer.Add(adv_grid, 0, wx.EXPAND | wx.ALL, 6)
        form_sizer.Add(adv_sizer, 0, wx.EXPAND | wx.ALL, 4)

        form_btns = wx.BoxSizer(wx.HORIZONTAL)
        save_btn = wx.Button(self, label=_("Save Band"), name="Save band")
        vfo_btn = wx.Button(self, label=_("Store Current VFO"), name="Store current VFO as band")
        save_btn.Bind(wx.EVT_BUTTON, self._on_save_scene)
        vfo_btn.Bind(wx.EVT_BUTTON, self._on_store_vfo)
        form_btns.Add(save_btn, 0, wx.RIGHT, 6)
        form_btns.Add(vfo_btn, 0)
        form_sizer.Add(form_btns, 0, wx.ALL, 4)
        sizer.Add(form_sizer, 0, wx.EXPAND | wx.ALL, 8)

        # Action buttons (Apply / Delete / Import / Export)
        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        apply_btn = wx.Button(self, label=_("Apply Selected"), name="Apply selected band")
        del_btn = wx.Button(self, label=_("Delete Selected"), name="Delete selected band")
        imp_btn = wx.Button(self, label=_("Import…"), name="Import band plan")
        exp_btn = wx.Button(self, label=_("Export…"), name="Export band plan")
        apply_btn.Bind(wx.EVT_BUTTON, self._on_apply_selected)
        del_btn.Bind(wx.EVT_BUTTON, self._on_delete)
        imp_btn.Bind(wx.EVT_BUTTON, self._on_import)
        exp_btn.Bind(wx.EVT_BUTTON, self._on_export)
        for b in (apply_btn, del_btn, imp_btn, exp_btn):
            btn_row.Add(b, 0, wx.RIGHT, 6)
        sizer.Add(btn_row, 0, wx.ALL, 8)

        self.SetSizer(sizer)
        self._tree.Bind(wx.EVT_TREE_ITEM_ACTIVATED, self._on_apply_selected)
        self._tree.Bind(wx.EVT_TREE_SEL_CHANGED, self._on_select)

    # ------------------------------------------------------------------
    # Tree
    # ------------------------------------------------------------------

    def _band_summary(self, s: Scene) -> str:
        if s.unbounded:
            return s.name
        return f"{s.name}  ({fmt_freq(s.freq_start)}–{fmt_freq(s.freq_end)}, {s.mode})"

    def _refresh_tree(self) -> None:
        self._tree.DeleteChildren(self._root)
        # Group scenes by their group (blank → General).
        groups: dict = {}
        for s in self._store.get_all():
            groups.setdefault(s.group or _UNGROUPED, []).append(s)
        ordered = [g for g in _group_order() if g in groups]
        ordered += [g for g in groups if g not in ordered]
        for g in ordered:
            node = self._tree.AppendItem(self._root, g)
            for s in groups[g]:
                leaf = self._tree.AppendItem(node, self._band_summary(s))
                self._tree.SetItemData(leaf, s)
            self._tree.Expand(node)
        # Keep the group combo in sync with known groups.
        self._group_ctrl.Set(ordered or _group_order())

    def _selected_scene(self) -> Optional[Scene]:
        item = self._tree.GetSelection()
        if not item.IsOk():
            return None
        return self._tree.GetItemData(item)   # None for a group node

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
    # Form <-> band
    # ------------------------------------------------------------------

    def _on_mode_change(self, _event: wx.CommandEvent) -> None:
        self._refresh_bw_choices(self._mode_ctrl.GetStringSelection())

    def _on_select(self, _event) -> None:  # noqa: ANN001
        s = self._selected_scene()
        if s is None:
            return
        self._name_ctrl.SetValue(s.name)
        self._group_ctrl.SetValue(s.group)
        self._start_ctrl.SetValue("" if s.freq_start == 0 else fmt_freq(s.freq_start))
        self._end_ctrl.SetValue("" if s.freq_end == 0 else fmt_freq(s.freq_end))
        self._mode_ctrl.SetStringSelection(s.mode)
        self._refresh_bw_choices(s.mode, s.bandwidth)
        self._step_ctrl.SetSelection(
            _STEP_VALUES.index(s.step) if s.step in _STEP_VALUES else 0
        )
        self._default_ctrl.SetValue("" if s.default_freq is None else fmt_freq(s.default_freq))
        self._nfm_dev_ctrl.SetValue("" if s.nfm_deviation is None else str(s.nfm_deviation))
        deemph_vals = [v for v, _lbl in _DEEMPH_CHOICES]
        self._deemph_ctrl.SetSelection(
            deemph_vals.index(s.wfm_deemphasis) if s.wfm_deemphasis in deemph_vals else 0
        )
        self._squelch_ctrl.SetValue("" if s.squelch is None else f"{s.squelch:.0f}")

    def _read_form(self) -> Optional[Scene]:
        name = self._name_ctrl.GetValue().strip()
        if not name:
            speech.output(_("Please enter a band name."))
            return None
        try:
            start = _parse_opt_freq(self._start_ctrl.GetValue()) or 0
            end = _parse_opt_freq(self._end_ctrl.GetValue()) or 0
            default_freq = _parse_opt_freq(self._default_ctrl.GetValue())
        except ValueError:
            speech.output(_("Invalid frequency."))
            return None
        nfm_dev = self._nfm_dev_ctrl.GetValue().strip()
        squelch = self._squelch_ctrl.GetValue().strip()
        deemph = _DEEMPH_CHOICES[self._deemph_ctrl.GetSelection()][0]
        group = self._group_ctrl.GetValue().strip()
        try:
            return Scene(
                name=name,
                freq_start=start,
                freq_end=end,
                mode=self._mode_ctrl.GetStringSelection(),
                bandwidth=self._form_bandwidth(),
                step=_STEP_VALUES[self._step_ctrl.GetSelection()],
                default_freq=default_freq,
                nfm_deviation=int(nfm_dev) if nfm_dev else None,
                wfm_deemphasis=deemph or None,
                squelch=float(squelch) if squelch else None,
                group=group,
            )
        except ValueError:
            speech.output(_("Invalid numeric override."))
            return None

    def _on_save_scene(self, _event: wx.CommandEvent) -> None:
        scene = self._read_form()
        if scene is None:
            return
        existing = self._store.by_name(scene.name)
        if existing is not None:
            idx = self._store.scenes.index(existing)
            self._store.scenes[idx] = scene
        else:
            self._store.add(scene)
        self._refresh_tree()
        self._notify_changed()
        speech.output(_("Saved band {name}.").format(name=scene.name))

    def _on_store_vfo(self, _event: wx.CommandEvent) -> None:
        if self._get_current_cb is None:
            return
        freq_hz, mode, bandwidth = self._get_current_cb()
        self._name_ctrl.SetValue("")
        self._start_ctrl.SetValue("")
        self._end_ctrl.SetValue("")
        if mode in MODES:
            self._mode_ctrl.SetStringSelection(mode)
        self._refresh_bw_choices(mode, bandwidth)
        self._default_ctrl.SetValue(fmt_freq(freq_hz))
        self._name_ctrl.SetFocus()
        speech.output(
            _("Storing {freq} as a band. Enter a name and edges, then save.").format(
                freq=fmt_freq(freq_hz)
            )
        )

    def _on_apply_selected(self, _event) -> None:  # noqa: ANN001
        s = self._selected_scene()
        if s is None:
            speech.output(_("No band selected."))
            return
        if self._on_apply_cb:
            self._on_apply_cb(s)

    def _on_delete(self, _event) -> None:  # noqa: ANN001
        s = self._selected_scene()
        if s is None:
            speech.output(_("No band selected."))
            return
        self._store.scenes.remove(s)
        self._refresh_tree()
        self._notify_changed()
        speech.output(_("Deleted band {name}.").format(name=s.name))

    # ------------------------------------------------------------------
    # Import / export (whole band plan)
    # ------------------------------------------------------------------

    def _on_export(self, _event: wx.CommandEvent) -> None:
        with wx.FileDialog(
            self, _("Export band plan"), defaultFile="band-plan.json",
            wildcard="JSON (*.json)|*.json",
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
        ) as fd:
            if fd.ShowModal() != wx.ID_OK:
                return
            try:
                self._store.save(fd.GetPath())
                speech.output(_("Band plan exported."))
            except OSError as exc:
                speech.output(_("Export failed: {err}").format(err=exc))

    def _on_import(self, _event: wx.CommandEvent) -> None:
        with wx.FileDialog(
            self, _("Import band plan"),
            wildcard="JSON (*.json)|*.json",
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
        ) as fd:
            if fd.ShowModal() != wx.ID_OK:
                return
            try:
                with open(fd.GetPath(), "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                imported = [Scene(**item) for item in data]
            except (OSError, json.JSONDecodeError, TypeError, KeyError) as exc:
                speech.output(_("Import failed: {err}").format(err=exc))
                return
        by_name = {s.name: s for s in self._store.scenes}
        for s in imported:
            by_name[s.name] = s
        self._store.scenes = list(by_name.values())
        self._refresh_tree()
        self._notify_changed()
        speech.output(_("Band plan imported."))
