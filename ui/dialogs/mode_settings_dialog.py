"""
ui/dialogs/mode_settings_dialog.py — per-mode settings editor.

Generic dialog driven by config.mode_params. Edits a mode's settings on a
*target* object by attribute name. Two flavours:

  - ``is_override=False`` (the global Settings): concrete controls.
  - ``is_override=True``  (a band or channel): each control gains an
    "(inherit)" state, and an unset value means None.
"""

from __future__ import annotations

import wx
from accessibility import speech
from config.mode_params import params_for

_INHERIT = N_("(default)")


class ModeSettingsDialog(wx.Dialog):
    """Edit the settings for *mode* on *target* (Settings / Scene / Channel)."""

    def __init__(self, parent, mode: str, target, is_override: bool,
                 title: str = "") -> None:
        super().__init__(
            parent,
            title=title or _("{mode} settings").format(mode=mode),
            style=wx.DEFAULT_DIALOG_STYLE,
        )
        self.SetName("Modulation settings")
        self._mode = mode
        self._target = target
        self._is_override = is_override
        self._rows: list = []          # (param, control)
        self._build_ui()
        self.Fit()
        self.Centre()

    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        panel = wx.Panel(self)
        grid = wx.FlexGridSizer(cols=2, vgap=8, hgap=10)
        grid.AddGrowableCol(1)

        for p in params_for(self._mode):
            grid.Add(wx.StaticText(panel, label=_(p.label)), 0, wx.ALIGN_CENTER_VERTICAL)
            ctrl = self._make_control(panel, p)
            grid.Add(ctrl, 1, wx.EXPAND)
            self._rows.append((p, ctrl))

        outer = wx.BoxSizer(wx.VERTICAL)
        if self._is_override:
            outer.Add(
                wx.StaticText(panel, label=_("Leave as “(default)” to use the built-in default.")),
                0, wx.ALL, 8,
            )
        outer.Add(grid, 1, wx.EXPAND | wx.ALL, 12)
        panel.SetSizer(outer)

        dlg_sizer = wx.BoxSizer(wx.VERTICAL)
        dlg_sizer.Add(panel, 1, wx.EXPAND)
        btns = wx.StdDialogButtonSizer()
        ok = wx.Button(self, wx.ID_OK)
        ok.SetDefault()
        btns.AddButton(ok)
        btns.AddButton(wx.Button(self, wx.ID_CANCEL))
        btns.Realize()
        dlg_sizer.Add(btns, 0, wx.EXPAND | wx.ALL, 8)
        self.SetSizer(dlg_sizer)
        self.Bind(wx.EVT_BUTTON, self._on_ok, id=wx.ID_OK)

    def _make_control(self, panel, p):
        cur = getattr(self._target, p.key, None)
        if p.kind == "choice":
            values = ([None] if self._is_override else []) + [v for v, _l in p.choices]
            labels = ([_(_INHERIT)] if self._is_override else []) + [_(l) for _v, l in p.choices]
            ctrl = wx.Choice(panel, choices=labels, name=_(p.label))
            ctrl.SetSelection(values.index(cur) if cur in values else 0)
            ctrl._values = values        # stash for read-back
            return ctrl
        if p.kind == "bool":
            if self._is_override:
                values = [None, True, False]
                ctrl = wx.Choice(panel, choices=[_(_INHERIT), _("On"), _("Off")], name=_(p.label))
                ctrl.SetSelection(values.index(cur) if cur in values else 0)
                ctrl._values = values
                return ctrl
            ctrl = wx.CheckBox(panel, name=_(p.label))
            ctrl.SetValue(bool(cur))
            return ctrl
        # int
        if self._is_override:
            ctrl = wx.TextCtrl(panel, value="" if cur is None else str(cur), name=_(p.label))
            return ctrl
        ctrl = wx.SpinCtrl(panel, min=p.min, max=p.max,
                           value=str(cur if cur is not None else p.min), name=_(p.label))
        return ctrl

    def _read_control(self, p, ctrl):
        if p.kind in ("choice",) or (p.kind == "bool" and self._is_override):
            return ctrl._values[ctrl.GetSelection()]
        if p.kind == "bool":
            return ctrl.GetValue()
        # int
        if self._is_override:
            text = ctrl.GetValue().strip()
            return int(text) if text else None
        return ctrl.GetValue()

    def _on_ok(self, _event) -> None:
        for p, ctrl in self._rows:
            try:
                setattr(self._target, p.key, self._read_control(p, ctrl))
            except ValueError:
                speech.output(_("Invalid value for {label}.").format(label=_(p.label)))
                return
        self.EndModal(wx.ID_OK)
