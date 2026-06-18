"""Tests for the accessible keyboard-shortcuts HTML and the context sets."""

import ui.keyboard_handler as kb
from ui.dialogs.accessible_help import SHORTCUT_GROUPS, _shortcuts_body_html


def test_shortcuts_html_structure():
    html = _shortcuts_body_html()
    assert html
    # One <h2> + <table> per group.
    assert html.count("<h2>") == len(SHORTCUT_GROUPS)
    assert html.count("<table>") == len(SHORTCUT_GROUPS)
    # A known shortcut is present, and the old "--- Section ---" artifacts are gone.
    assert "Ctrl+Q" in html
    assert "---" not in html
    # Body fragment only — no full document wrapper.
    assert "<html" not in html.lower()


def test_context_sets_disjoint():
    g, v, c = kb.GLOBAL_ACTIONS, kb.VFO_ACTIONS, kb.CHANNELS_ACTIONS
    assert g.isdisjoint(v)
    assert g.isdisjoint(c)
    assert v.isdisjoint(c)


def test_keymap_actions_are_gated():
    """Every action reachable from a key belongs to exactly one context set,
    or is special-cased in _on_key (CLOSE_WINDOW, layered mode-select)."""
    special = {kb.CLOSE_WINDOW}
    reachable = set(kb.KEYMAP.values())
    union = kb.GLOBAL_ACTIONS | kb.VFO_ACTIONS | kb.CHANNELS_ACTIONS | special
    missing = reachable - union
    assert not missing, f"ungated actions: {missing}"
