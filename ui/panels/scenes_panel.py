"""
ui/panels/scenes_panel.py — Scene Manager content panel (VFO band presets).

Holds the working UI for managing the band plan: add/edit (upsert by
name)/delete scenes, store the current VFO as a scene, apply a scene, and
import/export the whole band plan as JSON.  Hostable in a dialog or a
notebook tab.
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


def _parse_opt_freq(text: str) -> Optional[int]:
    """Parse an optional frequency field; blank → None."""
    text = text.strip()
    if not text:
        return None
    return parse_freq(text, default_unit="mhz")


class ScenesPanel(wx.Panel):
    """Band-scene management controls (no frame chrome)."""

    def __init__(
        self,
        parent: wx.Window,
        store: SceneStore,
        on_apply: Optional[Callable[[Scene], None]] = None,
        get_current: Optional[Callable[[], Tuple[int, str, int]]] = None,
        on_changed: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__(parent)
        self.SetName("Scenes panel")
        self._store = store
        self._on_apply_cb = on_apply
        self._get_current_cb = get_current
        self._on_changed_cb = on_changed
        self._build_ui()
        self._refresh_list()
        self._refresh_bw_choices("WFM")

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        sizer = wx.BoxSizer(wx.VERTICAL)

        # Import / export row
        top = wx.BoxSizer(wx.HORIZONTAL)
        imp_btn = wx.Button(self, label=_("Import…"), name="Import band plan")
        exp_btn = wx.Button(self, label=_("Export…"), name="Export band plan")
        imp_btn.Bind(wx.EVT_BUTTON, self._on_import)
        exp_btn.Bind(wx.EVT_BUTTON, self._on_export)
        top.Add(imp_btn, 0, wx.RIGHT, 4)
        top.Add(exp_btn, 0)
        sizer.Add(top, 0, wx.ALL, 8)

        # Scene list
        self._list = wx.ListCtrl(
            self,
            style=wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.BORDER_SUNKEN,
            name="Scenes list",
        )
        self._list.InsertColumn(0, _("Name"), width=160)
        self._list.InsertColumn(1, _("Band"), width=180)
        self._list.InsertColumn(2, _("Mode"), width=70)
        self._list.InsertColumn(3, _("Step"), width=90)
        sizer.Add(self._list, 1, wx.EXPAND | wx.ALL, 8)

        # Edit form
        form_box = wx.StaticBox(self, label=_("Scene"))
        form_sizer = wx.StaticBoxSizer(form_box, wx.VERTICAL)
        grid = wx.FlexGridSizer(cols=2, vgap=6, hgap=8)
        grid.AddGrowableCol(1)

        def _row(label_text: str, ctrl: wx.Window) -> None:
            grid.Add(wx.StaticText(self, label=label_text), 0, wx.ALIGN_CENTER_VERTICAL)
            grid.Add(ctrl, 1, wx.EXPAND)

        self._name_ctrl = wx.TextCtrl(self, name="Scene name")
        _row(_("Name:"), self._name_ctrl)

        self._start_ctrl = wx.TextCtrl(self, name="Band start")
        _row(_("Band start (MHz, blank = unbounded):"), self._start_ctrl)

        self._end_ctrl = wx.TextCtrl(self, name="Band end")
        _row(_("Band end (MHz, blank = unbounded):"), self._end_ctrl)

        self._mode_ctrl = wx.Choice(self, choices=MODES, name="Scene mode")
        self._mode_ctrl.SetSelection(0)
        self._mode_ctrl.Bind(wx.EVT_CHOICE, self._on_mode_change)
        _row(_("Mode:"), self._mode_ctrl)

        self._bw_ctrl = wx.Choice(self, name="Scene bandwidth")
        _row(_("Bandwidth:"), self._bw_ctrl)

        self._step_ctrl = wx.Choice(
            self,
            choices=[_("Follow tuning step")] + [_(s) for s in STEP_LABELS],
            name="Scene step",
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
        save_btn = wx.Button(self, label=_("Save Scene"), name="Save scene")
        vfo_btn = wx.Button(self, label=_("Store Current VFO"), name="Store current VFO as scene")
        save_btn.Bind(wx.EVT_BUTTON, self._on_save_scene)
        vfo_btn.Bind(wx.EVT_BUTTON, self._on_store_vfo)
        form_btns.Add(save_btn, 0, wx.RIGHT, 6)
        form_btns.Add(vfo_btn, 0)
        form_sizer.Add(form_btns, 0, wx.ALL, 4)
        sizer.Add(form_sizer, 0, wx.EXPAND | wx.ALL, 8)

        # Action buttons (Apply / Delete)
        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        apply_btn = wx.Button(self, label=_("Apply Selected"), name="Apply selected scene")
        del_btn = wx.Button(self, label=_("Delete Selected"), name="Delete selected scene")
        apply_btn.Bind(wx.EVT_BUTTON, self._on_apply_selected)
        del_btn.Bind(wx.EVT_BUTTON, self._on_delete)
        for b in (apply_btn, del_btn):
            btn_row.Add(b, 0, wx.RIGHT, 6)
        sizer.Add(btn_row, 0, wx.ALL, 8)

        self.SetSizer(sizer)
        self._list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._on_apply_selected)
        self._list.Bind(wx.EVT_LIST_ITEM_SELECTED, self._on_select)

    # ------------------------------------------------------------------
    # Refresh helpers
    # ------------------------------------------------------------------

    def _band_text(self, s: Scene) -> str:
        if s.unbounded:
            return _("Full range")
        return f"{fmt_freq(s.freq_start)} – {fmt_freq(s.freq_end)}"

    def _step_text(self, s: Scene) -> str:
        if s.step <= 0:
            return _("(follow)")
        try:
            return _(STEP_LABELS[STEPS.index(s.step)])
        except ValueError:
            return f"{s.step} Hz"

    def _refresh_list(self) -> None:
        self._list.DeleteAllItems()
        for s in self._store.get_all():
            idx = self._list.InsertItem(self._list.GetItemCount(), s.name)
            self._list.SetItem(idx, 1, self._band_text(s))
            self._list.SetItem(idx, 2, s.mode)
            self._list.SetItem(idx, 3, self._step_text(s))

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

    def _selected_scene(self) -> Optional[Scene]:
        idx = self._list.GetFirstSelected()
        scenes = self._store.get_all()
        if 0 <= idx < len(scenes):
            return scenes[idx]
        return None

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
    # Form <-> scene
    # ------------------------------------------------------------------

    def _on_mode_change(self, _event: wx.CommandEvent) -> None:
        self._refresh_bw_choices(self._mode_ctrl.GetStringSelection())

    def _on_select(self, _event) -> None:  # noqa: ANN001
        s = self._selected_scene()
        if s is None:
            return
        self._name_ctrl.SetValue(s.name)
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
            speech.output(_("Please enter a name."))
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
        self._refresh_list()
        self._notify_changed()
        speech.output(_("Saved scene {name}.").format(name=scene.name))

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
            _("Storing {freq} as a scene. Enter a name and band, then save.").format(
                freq=fmt_freq(freq_hz)
            )
        )

    def _on_apply_selected(self, _event) -> None:  # noqa: ANN001
        s = self._selected_scene()
        if s is None:
            speech.output(_("No scene selected."))
            return
        if self._on_apply_cb:
            self._on_apply_cb(s)

    def _on_delete(self, _event) -> None:  # noqa: ANN001
        s = self._selected_scene()
        if s is None:
            speech.output(_("No scene selected."))
            return
        self._store.scenes.remove(s)
        self._refresh_list()
        self._notify_changed()
        speech.output(_("Deleted scene {name}.").format(name=s.name))

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
        # Merge by name (imported wins), keeping existing order then new ones.
        by_name = {s.name: s for s in self._store.scenes}
        for s in imported:
            by_name[s.name] = s
        self._store.scenes = list(by_name.values())
        self._refresh_list()
        self._notify_changed()
        speech.output(_("Band plan imported."))
