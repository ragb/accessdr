"""Tests for config.scenes — band scene model and persistence."""

from __future__ import annotations

import os

from config.scenes import (
    FREE_SCENE_NAME,
    Scene,
    SceneStore,
    default_scenes,
)


def test_free_scene_is_unbounded():
    free = Scene(FREE_SCENE_NAME)
    assert free.unbounded
    assert free.landing_freq() is None


def test_bounded_scene_lands_at_default_then_start():
    s = Scene("FM", 88_000_000, 108_000_000, default_freq=98_000_000)
    assert not s.unbounded
    assert s.landing_freq() == 98_000_000
    s2 = Scene("Air", 118_000_000, 137_000_000)
    assert s2.landing_freq() == 118_000_000  # falls back to band start


def test_default_scenes_include_free_and_bands():
    names = [s.name for s in default_scenes()]
    assert FREE_SCENE_NAME in names
    assert "FM Radio" in names
    assert "PMR446" in names


def test_default_scenes_include_hf_and_shortwave():
    by_name = {s.name: s for s in default_scenes()}
    assert "40m Ham" in by_name and by_name["40m Ham"].mode == "LSB"
    assert "20m Ham" in by_name and by_name["20m Ham"].mode == "USB"
    assert "49m SW" in by_name and by_name["49m SW"].mode == "AM"
    assert "CB 27m" in by_name
    assert by_name["49m SW"].freq_start == 5_900_000
    assert by_name["49m SW"].step == 5_000        # SW 5 kHz raster
    assert by_name["AM Radio"].step == 9_000       # MW 9 kHz
    assert by_name["Airband"].bandwidth == 10_000  # explicit per-band bw
    assert by_name["PMR446"].nfm_deviation == 2_500  # per-mode override


def test_default_scenes_have_groups():
    by_name = {s.name: s for s in default_scenes()}
    assert by_name[FREE_SCENE_NAME].group == "General"
    assert by_name["40m Ham"].group == "Amateur"
    assert by_name["49m SW"].group == "Shortwave"
    assert by_name["FM Radio"].group == "Broadcast"
    assert by_name["PMR446"].group == "PMR / CB"


def test_load_merges_new_default_bands(tmp_path):
    # A saved plan with only the free scene should gain the default bands.
    path = os.path.join(tmp_path, "scenes.json")
    SceneStore(scenes=[Scene(FREE_SCENE_NAME)]).save(path)
    store = SceneStore()
    store.load(path)
    names = [s.name for s in store.scenes]
    assert "40m Ham" in names           # merged in
    assert names[0] == FREE_SCENE_NAME  # existing entry preserved/first


def test_merge_keeps_user_edits(tmp_path):
    path = os.path.join(tmp_path, "scenes.json")
    # User edited FM Radio; merge must not overwrite it.
    edited = Scene("FM Radio", 88_000_000, 108_000_000, "WFM", 150_000)
    SceneStore(scenes=[edited]).save(path)
    store = SceneStore()
    store.load(path)
    fm = store.by_name("FM Radio")
    assert fm.bandwidth == 150_000     # user's value, not the default


def test_load_missing_seeds_defaults(tmp_path):
    store = SceneStore()
    store.load(os.path.join(tmp_path, "nope.json"))
    assert store.by_name(FREE_SCENE_NAME) is not None
    assert len(store.scenes) > 1


def test_round_trip(tmp_path):
    path = os.path.join(tmp_path, "scenes.json")
    store = SceneStore()
    store.load(os.path.join(tmp_path, "missing.json"))  # seed defaults
    store.add(Scene("Custom", 144_000_000, 146_000_000, "NFM", 12_500, 12_500))
    store.save(path)

    fresh = SceneStore()
    fresh.load(path)
    custom = fresh.by_name("Custom")
    assert custom is not None
    assert custom.freq_start == 144_000_000
    assert custom.mode == "NFM"
    assert custom.step == 12_500


def test_free_scene_created_if_absent():
    store = SceneStore(scenes=[Scene("FM", 88_000_000, 108_000_000)])
    free = store.free_scene()
    assert free.name == FREE_SCENE_NAME
    assert store.scenes[0].name == FREE_SCENE_NAME  # inserted at front


def test_corrupt_file_falls_back_to_defaults(tmp_path):
    path = os.path.join(tmp_path, "bad.json")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("{ not valid json")
    store = SceneStore()
    store.load(path)
    assert store.by_name(FREE_SCENE_NAME) is not None
