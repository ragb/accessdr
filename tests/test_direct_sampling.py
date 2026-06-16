"""Tests for direct-sampling plumbing (RTL HF mode)."""

from __future__ import annotations

import numpy as np

from core.sdr_backends import DummyBackend, PyRtlSdrBackend, SDRBackend
from core.sdr_device import SDRDevice


class _RecordingBackend(SDRBackend):
    """Captures the values passed to backend methods."""

    def __init__(self):
        self.direct_sampling = None
        self.opened_config = None

    def open(self, device_index, config):
        self.opened_config = config
        return True

    def close(self):
        pass

    def stream_loop(self, *a, **k):
        pass

    def set_direct_sampling(self, mode):
        self.direct_sampling = mode


def test_device_default_off():
    assert SDRDevice().direct_sampling == 0


def test_device_setter_updates_attr_without_backend():
    dev = SDRDevice()
    dev.set_direct_sampling(2)
    assert dev.direct_sampling == 2  # no backend yet; attr still recorded


def test_device_setter_delegates_to_backend():
    dev = SDRDevice()
    rec = _RecordingBackend()
    dev._backend = rec
    dev.set_direct_sampling(1)
    assert rec.direct_sampling == 1
    assert dev.direct_sampling == 1


def test_open_config_includes_direct_sampling(monkeypatch):
    import core.sdr_device as sd
    rec = _RecordingBackend()
    monkeypatch.setattr(sd, "create_backend", lambda settings: rec)
    dev = SDRDevice()
    dev.direct_sampling = 2
    assert dev.open() is True
    assert rec.opened_config["direct_sampling"] == 2


def test_dummy_backend_noop_safe():
    DummyBackend().set_direct_sampling(2)  # must not raise


def test_pyrtlsdr_setter_safe_without_handle():
    be = PyRtlSdrBackend()
    be._dev_handle = None
    be.set_direct_sampling(2)  # guarded by handle check; must not raise
