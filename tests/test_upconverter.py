"""Tests for upconverter-offset frequency mapping in RadioController."""

from __future__ import annotations

from config.settings import Settings
from ui.radio_controller import RadioController


class _FakeSDR:
    def __init__(self):
        self.freq = None

    def set_frequency(self, hz):
        self.freq = hz


def _controller(offset: int) -> RadioController:
    s = Settings()
    s.upconverter_offset = offset
    rc = RadioController(s, audio=object(), noise_blanker=object())
    rc._sdr = _FakeSDR()           # inject; no hardware touched
    return rc


def test_no_offset_passthrough():
    rc = _controller(0)
    rc.set_frequency(27_000_000)
    assert rc._sdr.freq == 27_000_000


def test_offset_added_to_hw_freq():
    rc = _controller(125_000_000)      # Ham It Up
    rc.set_frequency(27_000_000)       # CB display freq
    assert rc._sdr.freq == 152_000_000


def test_hw_freq_helper():
    rc = _controller(120_000_000)      # SpyVerter
    assert rc._hw_freq(7_100_000) == 127_100_000   # 40m
    assert rc._hw_freq(0) == 120_000_000
