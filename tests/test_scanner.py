"""Tests for the band / channel-map scanner core logic."""

import core.scanner as scanner_mod
from core.scanner import Scanner


def test_band_range_scan_tunes_expected_freqs(monkeypatch):
    """A band (range) scan steps start→stop inclusive by step."""
    monkeypatch.setattr(scanner_mod, "DWELL_SECONDS", 0.0)
    monkeypatch.setattr(scanner_mod.time, "sleep", lambda *_a: None)

    tuned = []
    sc = Scanner(
        set_frequency_cb=lambda f: tuned.append(f),
        get_signal_db_cb=lambda: -200.0,  # below squelch → nothing "found"
    )
    sc.start(100_000_000, 100_200_000, 100_000, squelch_db=-60.0)
    sc._thread.join(timeout=5)

    assert tuned == [100_000_000, 100_100_000, 100_200_000]


def test_channel_list_scan_reports_labels(monkeypatch):
    """A channel-map (list) scan tunes each freq and labels found signals."""
    monkeypatch.setattr(scanner_mod, "DWELL_SECONDS", 0.0)
    monkeypatch.setattr(scanner_mod.time, "sleep", lambda *_a: None)

    tuned = []
    found = []
    sc = Scanner(
        set_frequency_cb=lambda f: tuned.append(f),
        get_signal_db_cb=lambda: -10.0,  # above squelch → every target "found"
    )
    sc.on_signal_found = found.append

    freqs = [446_006_250, 446_018_750, 446_031_250]
    labels = ["CH1 Alpha", "CH2 Bravo", "CH3 Charlie"]
    sc.start_list(freqs, squelch_db=-60.0, labels=labels)
    sc._thread.join(timeout=5)

    assert tuned == freqs
    assert [r.freq_hz for r in found] == freqs
    assert [r.label for r in found] == labels


def test_zero_step_falls_back(monkeypatch):
    """A band with no step (0) must not hang on a zero-increment loop."""
    monkeypatch.setattr(scanner_mod, "DWELL_SECONDS", 0.0)
    monkeypatch.setattr(scanner_mod.time, "sleep", lambda *_a: None)

    tuned = []
    sc = Scanner(
        set_frequency_cb=lambda f: tuned.append(f),
        get_signal_db_cb=lambda: -200.0,
    )
    sc.start(100_000_000, 100_050_000, 0, squelch_db=-60.0)
    sc._thread.join(timeout=5)

    # Fallback step is 100 kHz → just the start frequency fits in this range.
    assert tuned == [100_000_000]
