"""
ui/panels/band_tree.py — shared helpers for the bands tree.

Groups a SceneStore's bands by service category into a wx.TreeCtrl, used
by both the VFO band selector and the Bands manager dialog so they stay
consistent. Tree controls are read naturally by screen readers (group
level, expand/collapse).
"""

from __future__ import annotations

from typing import Optional

import wx
from config.scenes import Scene, SceneStore
from ui.formatting import fmt_freq

UNGROUPED = N_("General")


def group_order() -> list:
    """Display order for band groups: General, then the service order."""
    from config.bands import GROUP_ORDER
    return [UNGROUPED] + list(GROUP_ORDER)


def band_summary(s: Scene) -> str:
    """Leaf label: name plus range and mode (so the mode is always visible)."""
    if s.unbounded:
        return s.name
    return f"{s.name}  ({fmt_freq(s.freq_start)}–{fmt_freq(s.freq_end)}, {s.mode})"


def populate(tree: wx.TreeCtrl, root, store: SceneStore) -> None:
    """Rebuild *tree* under *root*: group nodes with band leaves (data=Scene)."""
    tree.DeleteChildren(root)
    groups: dict = {}
    for s in store.get_all():
        groups.setdefault(s.group or UNGROUPED, []).append(s)
    ordered = [g for g in group_order() if g in groups]
    ordered += [g for g in groups if g not in ordered]
    for g in ordered:
        node = tree.AppendItem(root, g)
        for s in groups[g]:
            leaf = tree.AppendItem(node, band_summary(s))
            tree.SetItemData(leaf, s)
        tree.Expand(node)


def selected(tree: wx.TreeCtrl) -> Optional[Scene]:
    """Return the Scene for the selected leaf, or None (e.g. a group node)."""
    item = tree.GetSelection()
    if not item.IsOk():
        return None
    return tree.GetItemData(item)


def select_band(tree: wx.TreeCtrl, root, name: str) -> None:
    """Select the leaf for the band named *name*, if present (no event guard)."""
    group, gck = tree.GetFirstChild(root)
    while group.IsOk():
        leaf, lck = tree.GetFirstChild(group)
        while leaf.IsOk():
            s = tree.GetItemData(leaf)
            if s is not None and s.name == name:
                tree.SelectItem(leaf)
                tree.EnsureVisible(leaf)
                return
            leaf, lck = tree.GetNextChild(group, lck)
        group, gck = tree.GetNextChild(root, gck)
