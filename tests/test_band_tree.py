"""Tests for ui.panels.band_tree helpers (need a wx.App)."""

from __future__ import annotations

import os

import wx

from config.scenes import Scene, SceneStore
from ui.panels import band_tree


def test_group_order():
    go = band_tree.group_order()
    assert go[0] == band_tree.UNGROUPED      # "General" first
    assert "Amateur" in go and "Broadcast" in go


def test_band_summary():
    free = Scene("Free / Full Range", group="General")
    assert band_tree.band_summary(free) == "Free / Full Range"   # unbounded → name only
    fm = Scene("FM Radio", 88_000_000, 108_000_000, "WFM", group="Broadcast")
    summary = band_tree.band_summary(fm)
    assert "FM Radio" in summary and "WFM" in summary


def test_populate_select_and_read_back(wx_app, tmp_path):
    store = SceneStore()
    store.load(os.path.join(tmp_path, "missing.json"))   # seeds defaults
    frame = wx.Frame(None)
    tree = wx.TreeCtrl(frame, style=wx.TR_HIDE_ROOT)
    root = tree.AddRoot("r")
    band_tree.populate(tree, root, store)
    assert tree.GetChildrenCount(root, False) >= 6        # service groups

    band_tree.select_band(tree, root, "FM Radio")
    s = band_tree.selected(tree)
    assert s is not None and s.name == "FM Radio"
    frame.Destroy()
