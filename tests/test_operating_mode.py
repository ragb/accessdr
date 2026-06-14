"""Tests for core.operating_mode — VFO/MR navigation controller."""

from __future__ import annotations

from config.channels import Channel, ChannelMap
from config.scenes import FREE_SCENE_NAME, Scene
from core.operating_mode import (
    FREQ_FLOOR_HZ,
    OperatingState,
    OpMode,
)


def _fm_scene() -> Scene:
    return Scene("FM", 88_000_000, 108_000_000, "WFM", 200_000, 100_000)


def _free_scene() -> Scene:
    return Scene(FREE_SCENE_NAME)


# ----------------------------------------------------------------------
# Mode toggling
# ----------------------------------------------------------------------

def test_toggle_mode():
    st = OperatingState(_free_scene())
    assert st.mode is OpMode.VFO
    assert st.toggle_mode() is OpMode.MR
    assert st.toggle_mode() is OpMode.VFO


# ----------------------------------------------------------------------
# VFO stepping — free (unbounded) scene reproduces legacy behaviour
# ----------------------------------------------------------------------

def test_free_vfo_uses_fallback_step():
    st = OperatingState(_free_scene())
    res = st.step(+1, 100_000_000, fallback_step=1_000)
    assert res.mode is OpMode.VFO
    assert res.frequency == 100_001_000
    assert not res.at_edge


def test_free_vfo_floor():
    st = OperatingState(_free_scene())
    res = st.step(-1, FREQ_FLOOR_HZ, fallback_step=1_000)
    assert res.frequency == FREQ_FLOOR_HZ
    assert res.at_edge


# ----------------------------------------------------------------------
# VFO stepping — bounded scene clamps to band edges and uses scene step
# ----------------------------------------------------------------------

def test_bounded_vfo_uses_scene_step():
    st = OperatingState(_fm_scene())
    res = st.step(+1, 98_000_000, fallback_step=1_000)
    assert res.frequency == 98_100_000  # 100 kHz scene step, not 1 kHz fallback


def test_bounded_vfo_clamps_high_edge():
    st = OperatingState(_fm_scene())
    res = st.step(+1, 107_950_000, fallback_step=1_000)
    assert res.frequency == 108_000_000
    assert res.at_edge


def test_bounded_vfo_clamps_low_edge():
    st = OperatingState(_fm_scene())
    res = st.step(-1, 88_050_000, fallback_step=1_000)
    assert res.frequency == 88_000_000
    assert res.at_edge


# ----------------------------------------------------------------------
# MR stepping — channel walk with wrap-around
# ----------------------------------------------------------------------

def _map() -> ChannelMap:
    return ChannelMap("M", [
        Channel(1, "A", 145_000_000, "NFM", 12_500),
        Channel(2, "B", 146_000_000, "NFM", 12_500),
        Channel(3, "C", 147_000_000, "NFM", 12_500),
    ])


def test_mr_steps_forward():
    st = OperatingState(_free_scene(), _map(), mode=OpMode.MR)
    res = st.step(+1, 0, fallback_step=1_000)
    assert res.mode is OpMode.MR
    assert res.channel.label == "B"
    assert res.channel_index == 1


def test_mr_wraps_around():
    st = OperatingState(_free_scene(), _map(), mode=OpMode.MR)
    st.channel_index = 2
    res = st.step(+1, 0, fallback_step=1_000)
    assert res.channel.label == "A"
    assert res.channel_index == 0


def test_mr_wraps_backwards():
    st = OperatingState(_free_scene(), _map(), mode=OpMode.MR)
    res = st.step(-1, 0, fallback_step=1_000)
    assert res.channel.label == "C"
    assert res.channel_index == 2


def test_mr_empty_map_returns_no_channel():
    st = OperatingState(_free_scene(), ChannelMap("Empty", []), mode=OpMode.MR)
    res = st.step(+1, 0, fallback_step=1_000)
    assert res.channel is None


def test_mr_no_map_returns_no_channel():
    st = OperatingState(_free_scene(), None, mode=OpMode.MR)
    res = st.step(+1, 0, fallback_step=1_000)
    assert res.channel is None


def test_unsorted_map_walks_in_number_order():
    m = ChannelMap("M", [
        Channel(3, "C", 3),
        Channel(1, "A", 1),
        Channel(2, "B", 2),
    ])
    st = OperatingState(_free_scene(), m, mode=OpMode.MR)
    assert st.current_channel().label == "A"  # index 0 of sorted
    res = st.step(+1, 0, fallback_step=1_000)
    assert res.channel.label == "B"


# ----------------------------------------------------------------------
# Context switching
# ----------------------------------------------------------------------

def test_set_channel_map_resets_index():
    st = OperatingState(_free_scene(), _map(), mode=OpMode.MR)
    st.channel_index = 2
    st.set_channel_map(_map())
    assert st.channel_index == 0


def test_effective_step_prefers_scene():
    bounded = OperatingState(_fm_scene())
    assert bounded.effective_step(1_000) == 100_000
    free = OperatingState(_free_scene())
    assert free.effective_step(1_000) == 1_000
