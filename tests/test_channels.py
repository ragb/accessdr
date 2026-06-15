"""Tests for config.channels — channel memory model and persistence."""

from __future__ import annotations

import os

from config.channels import (
    Channel,
    ChannelMap,
    ChannelMapStore,
    default_maps,
)


def test_sorted_by_number():
    m = ChannelMap("M", [
        Channel(3, "C", 3),
        Channel(1, "A", 1),
        Channel(2, "B", 2),
    ])
    assert [c.number for c in m.sorted_channels()] == [1, 2, 3]


def test_next_number_fills_gaps():
    m = ChannelMap("M", [Channel(1, "A", 1), Channel(3, "C", 3)])
    assert m.next_number() == 2
    m.channels.append(Channel(2, "B", 2))
    assert m.next_number() == 4


def test_load_missing_seeds_defaults(tmp_path):
    store = ChannelMapStore()
    store.load(os.path.join(tmp_path, "nope.json"))
    assert store.active_map() is not None
    assert store.active_map().name == default_maps()[0].name


def test_default_maps_include_pmr_and_cb():
    names = [m.name for m in default_maps()]
    assert names == ["My Channels", "PMR446", "CB (CEPT FM)"]


def test_pmr446_map():
    pmr = next(m for m in default_maps() if m.name == "PMR446")
    assert len(pmr.channels) == 16
    assert pmr.channels[0].frequency == 446_006_250   # ch1
    assert pmr.channels[15].frequency == 446_193_750  # ch16
    assert all(c.mode == "NFM" and c.bandwidth == 12_500 for c in pmr.channels)


def test_cb_cept_map():
    cb = next(m for m in default_maps() if m.name == "CB (CEPT FM)")
    assert len(cb.channels) == 40
    assert cb.channels[0].frequency == 26_965_000    # ch1
    assert cb.channels[39].frequency == 27_405_000   # ch40
    # The standard CB anomaly: ch23 is higher than ch24/25.
    assert cb.channels[22].frequency == 27_255_000   # ch23
    assert cb.channels[23].frequency == 27_235_000   # ch24
    assert cb.channels[24].frequency == 27_245_000   # ch25
    assert all(c.mode == "NFM" for c in cb.channels)


def test_round_trip(tmp_path):
    path = os.path.join(tmp_path, "channels.json")
    store = ChannelMapStore(
        maps=[
            ChannelMap("Repeaters", [Channel(1, "R1", 145_500_000, "NFM", 12_500)]),
            ChannelMap("Air", [Channel(1, "Tower", 118_100_000, "AM", 8_000)]),
        ],
        active=1,
    )
    store.save(path)

    fresh = ChannelMapStore()
    fresh.load(path)
    assert len(fresh.maps) == 2
    assert fresh.active == 1
    assert fresh.active_map().name == "Air"
    ch = fresh.active_map().channels[0]
    assert ch.frequency == 118_100_000
    assert ch.bandwidth == 8_000


def test_active_clamped_when_out_of_range(tmp_path):
    path = os.path.join(tmp_path, "channels.json")
    store = ChannelMapStore(maps=[ChannelMap("Only", [])], active=9)
    store.save(path)
    fresh = ChannelMapStore()
    fresh.load(path)
    assert fresh.active == 0
    assert fresh.active_map().name == "Only"


def test_set_active_clamps():
    store = ChannelMapStore(maps=[ChannelMap("A"), ChannelMap("B")])
    store.set_active(5)
    assert store.active == 1
    store.set_active(-3)
    assert store.active == 0
