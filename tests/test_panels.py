"""Panel-level tests for ChannelsPanel and ScenesPanel (need a wx.App)."""

from __future__ import annotations

import os

import wx

from config.channels import Channel, ChannelMap, ChannelMapStore
from config.scenes import SceneStore
from ui.panels.channels_panel import ChannelsPanel
from ui.panels.scenes_panel import ScenesPanel


# ----------------------------------------------------------------------
# Channels panel
# ----------------------------------------------------------------------

def _channels_panel(channels):
    frame = wx.Frame(None)
    store = ChannelMapStore(maps=[ChannelMap("M", channels)])
    store.save = lambda *a, **k: None        # don't touch the real file
    panel = ChannelsPanel(
        frame, store,
        on_load=lambda c: None,
        get_current=lambda: (98_000_000, "WFM", 200_000),
        on_changed=lambda: None,
    )
    return frame, store, panel


def test_move_swaps_numbers(wx_app):
    frame, store, panel = _channels_panel(
        [Channel(1, "A", 1), Channel(2, "B", 2), Channel(3, "C", 3)]
    )
    panel._list.Select(0)                    # CH1 (A)
    panel._on_move(+1)
    nums = {c.label: c.number for c in store.maps[0].channels}
    assert nums["A"] == 2 and nums["B"] == 1
    frame.Destroy()


def test_save_channel_with_squelch_and_overrides(wx_app):
    frame, store, panel = _channels_panel([])
    panel._num_ctrl.SetValue(5)
    panel._label_ctrl.SetValue("Rep")
    panel._freq_ctrl.SetValue("145.5")
    panel._mode_ctrl.SetStringSelection("NFM")
    panel._refresh_bw_choices("NFM")
    panel._squelch_ctrl.SetValue("-70")
    panel._pending_overrides = {"nfm_deviation": 2500}
    panel._on_save_channel(None)
    ch = store.maps[0].channels[0]
    assert ch.number == 5
    assert ch.frequency == 145_500_000
    assert ch.squelch == -70.0
    assert ch.nfm_deviation == 2500
    frame.Destroy()


def test_channel_ms_button_enable(wx_app):
    frame, store, panel = _channels_panel([])
    panel._mode_ctrl.SetStringSelection("NFM")
    panel._on_mode_change(None)
    assert panel._ms_btn.IsEnabled()
    panel._mode_ctrl.SetStringSelection("AM")
    panel._on_mode_change(None)
    assert not panel._ms_btn.IsEnabled()
    frame.Destroy()


# ----------------------------------------------------------------------
# Bands (scenes) panel
# ----------------------------------------------------------------------

def _scenes_panel(tmp_path):
    frame = wx.Frame(None)
    store = SceneStore()
    store.load(os.path.join(tmp_path, "missing.json"))   # seed defaults
    store.save = lambda *a, **k: None
    panel = ScenesPanel(
        frame, store,
        on_apply=lambda s: None,
        get_current=lambda: (98_000_000, "NFM", 12_500),
        on_changed=lambda: None,
    )
    return frame, store, panel


def test_read_form_carries_pending_overrides(wx_app, tmp_path):
    frame, store, panel = _scenes_panel(tmp_path)
    panel._name_ctrl.SetValue("TestBand")
    panel._start_ctrl.SetValue("446")
    panel._end_ctrl.SetValue("446.2")
    panel._mode_ctrl.SetStringSelection("NFM")
    panel._refresh_bw_choices("NFM")
    panel._pending_overrides = {"nfm_deviation": 2500}
    scene = panel._read_form()
    assert scene is not None
    assert scene.name == "TestBand"
    assert scene.nfm_deviation == 2500
    frame.Destroy()


def test_band_ms_button_enable(wx_app, tmp_path):
    frame, store, panel = _scenes_panel(tmp_path)
    panel._mode_ctrl.SetStringSelection("WFM")
    panel._on_mode_change(None)
    assert panel._ms_btn.IsEnabled()
    panel._mode_ctrl.SetStringSelection("CW")
    panel._on_mode_change(None)
    assert not panel._ms_btn.IsEnabled()
    frame.Destroy()
