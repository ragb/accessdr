"""
core/operating_mode.py — VFO / MR operating-mode controller.

Pure logic (no wx) that decides what PageUp/PageDown navigation does:

  - **VFO** mode: step the frequency by the active scene's step, clamped to
    the scene's band edges.  An unbounded ("Free") scene reproduces classic
    free-style tuning with only a hard low-frequency floor.
  - **MR** mode: walk the numbered channels of the active map (wrap-around),
    returning the channel to load.

The controller never touches the radio or settings; it computes a
:class:`StepResult` that the UI layer applies.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from config.channels import Channel, ChannelMap
from config.scenes import Scene

# Hard floor for VFO tuning regardless of scene (matches legacy behaviour).
FREQ_FLOOR_HZ = 100_000


class OpMode(Enum):
    VFO = "VFO"
    MR = "MR"


@dataclass
class StepResult:
    """Outcome of a navigation step, applied by the UI."""
    mode: OpMode
    frequency: Optional[int] = None     # VFO: new tune frequency
    at_edge: bool = False               # VFO: clamped against a band edge
    channel: Optional[Channel] = None   # MR: channel to load
    channel_index: Optional[int] = None # MR: index within the active map


class OperatingState:
    """Holds the current mode, active scene, and active channel map."""

    def __init__(
        self,
        scene: Scene,
        channel_map: Optional[ChannelMap] = None,
        mode: OpMode = OpMode.VFO,
    ) -> None:
        self.mode = mode
        self.scene = scene
        self.channel_map = channel_map
        self.channel_index = 0

    # ------------------------------------------------------------------
    # Mode / context
    # ------------------------------------------------------------------

    def toggle_mode(self) -> OpMode:
        self.mode = OpMode.MR if self.mode is OpMode.VFO else OpMode.VFO
        return self.mode

    def set_scene(self, scene: Scene) -> None:
        self.scene = scene

    def set_channel_map(self, channel_map: Optional[ChannelMap]) -> None:
        self.channel_map = channel_map
        self.channel_index = 0

    def current_channel(self) -> Optional[Channel]:
        chans = self._channels()
        if not chans:
            return None
        self.channel_index = max(0, min(self.channel_index, len(chans) - 1))
        return chans[self.channel_index]

    # ------------------------------------------------------------------
    # VFO helpers
    # ------------------------------------------------------------------

    def effective_step(self, fallback_step: int) -> int:
        """Scene step when bounded, else the user's selected step."""
        return self.scene.step if self.scene.step > 0 else fallback_step

    def clamp(self, freq: int) -> tuple[int, bool]:
        """Clamp *freq* to the scene's band (and the hard floor).

        Returns ``(frequency, at_edge)``.
        """
        lo = FREQ_FLOOR_HZ
        hi = None
        if not self.scene.unbounded:
            lo = max(FREQ_FLOOR_HZ, self.scene.freq_start)
            hi = self.scene.freq_end
        at_edge = False
        if freq < lo:
            freq, at_edge = lo, True
        elif hi is not None and freq > hi:
            freq, at_edge = hi, True
        return freq, at_edge

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def step(self, direction: int, current_freq: int, fallback_step: int) -> StepResult:
        """Compute a navigation step for the current mode.

        *direction* is +1 (up) or -1 (down).
        """
        if self.mode is OpMode.VFO:
            return self._vfo_step(direction, current_freq, fallback_step)
        return self._mr_step(direction)

    def _vfo_step(self, direction: int, current_freq: int, fallback_step: int) -> StepResult:
        step = self.effective_step(fallback_step)
        target = current_freq + direction * step
        freq, at_edge = self.clamp(target)
        return StepResult(mode=OpMode.VFO, frequency=freq, at_edge=at_edge)

    def _mr_step(self, direction: int) -> StepResult:
        chans = self._channels()
        if not chans:
            return StepResult(mode=OpMode.MR)
        self.channel_index = (self.channel_index + direction) % len(chans)
        return StepResult(
            mode=OpMode.MR,
            channel=chans[self.channel_index],
            channel_index=self.channel_index,
        )

    # ------------------------------------------------------------------

    def _channels(self) -> list[Channel]:
        if self.channel_map is None:
            return []
        return self.channel_map.sorted_channels()
