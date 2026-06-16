"""Tests for the generic ModeSettingsDialog (need a wx.App)."""

from __future__ import annotations

import wx

from config.scenes import Scene
from config.settings import Settings
from ui.dialogs.mode_settings_dialog import ModeSettingsDialog


def _ctrl_for(dlg, key):
    for p, ctrl in dlg._rows:
        if p.key == key:
            return p, ctrl
    raise KeyError(key)


def test_global_concrete_read_write(wx_app):
    frame = wx.Frame(None)
    s = Settings()
    dlg = ModeSettingsDialog(frame, "WFM", s, is_override=False)
    assert len(dlg._rows) == 4            # deemphasis, stereo, hiblend, rds
    p, ctrl = _ctrl_for(dlg, "wfm_rds_enabled")   # concrete bool → checkbox
    ctrl.SetValue(False)
    assert dlg._read_control(p, ctrl) is False
    dlg.Destroy()
    frame.Destroy()


def test_override_blank_is_none_then_value(wx_app):
    frame = wx.Frame(None)
    band = Scene("x", mode="NFM")          # nfm_deviation is None (inherit)
    dlg = ModeSettingsDialog(frame, "NFM", band, is_override=True)
    p, ctrl = _ctrl_for(dlg, "nfm_deviation")     # override int → TextCtrl
    assert dlg._read_control(p, ctrl) is None      # blank == inherit/default
    ctrl.SetValue("2500")
    assert dlg._read_control(p, ctrl) == 2500
    dlg.Destroy()
    frame.Destroy()


def test_override_bool_has_inherit_state(wx_app):
    frame = wx.Frame(None)
    band = Scene("x", mode="WFM")
    dlg = ModeSettingsDialog(frame, "WFM", band, is_override=True)
    p, ctrl = _ctrl_for(dlg, "wfm_rds_enabled")   # override bool → 3-way choice
    # first option is the inherit/default sentinel -> None
    ctrl.SetSelection(0)
    assert dlg._read_control(p, ctrl) is None
    dlg.Destroy()
    frame.Destroy()
