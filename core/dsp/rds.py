"""
core/dsp/rds.py — RDS (Radio Data System) decoder for WFM broadcast.

Extracts station name (PS), radio text (RT), and programme type (PTY)
from the 57 kHz BPSK RDS subcarrier embedded in the FM MPX baseband.

RDS protocol summary (IEC 62106 / NRSC-4-B):
  - 57 kHz BPSK subcarrier, phase-locked to 3× the 19 kHz stereo pilot
  - 1187.5 bps = 19000/16 bits per second
  - Each group = 4 blocks × 26 bits = 104 bits total
  - Each block = 16 data bits + 10 check bits (CRC + offset word)
  - Offset words identify block position: A, B, C/C', D
  - Group type 0A/0B → Programme Service name (8 chars, 2 per group)
  - Group type 2A/2B → Radio Text (64 chars, 4 or 2 per group)
  - All groups carry PTY in bits 6–10 of block B
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

import numpy as np
from scipy import signal as sp_signal

from .filters import make_bandpass_iir, make_lowpass_iir

logger = logging.getLogger(__name__)

# CRC-10 generator polynomial for RDS: x^10 + x^8 + x^7 + x^5 + x^4 + x^3 + 1
_CRC_POLY = 0x1B9  # 0b110111001 (10-bit)

# Offset words for each block position (10 bits each)
_OFFSET_A  = 0x0FC
_OFFSET_B  = 0x198
_OFFSET_C  = 0x168
_OFFSET_Cp = 0x350
_OFFSET_D  = 0x1B4

_OFFSETS = [_OFFSET_A, _OFFSET_B, _OFFSET_C, _OFFSET_D]

# PTY codes (North America RBDS — broadly compatible with European RDS)
_PTY_NAMES = [
    "", "News", "Information", "Sports", "Talk", "Rock",
    "Classic Rock", "Adult Hits", "Soft Rock", "Top 40", "Country",
    "Oldies", "Soft", "Nostalgia", "Jazz", "Classical",
    "R&B", "Soft R&B", "Language", "Religious Music", "Religious Talk",
    "Personality", "Public", "College", "Spanish Talk", "Spanish Music",
    "Hip Hop", "", "", "Weather", "Test", "Emergency",
]

# Target internal sample rate for RDS bit extraction (~12 kHz = ~10 samples/bit)
_RDS_INTERNAL_RATE = 11875  # 10× the bit rate for clean clock recovery


def _crc10(data_bits: int, check_bits: int) -> int:
    """Compute CRC-10 syndrome for a 26-bit block (16 data + 10 check)."""
    block = (data_bits << 10) | check_bits
    for i in range(25, 9, -1):
        if block & (1 << i):
            block ^= _CRC_POLY << (i - 9)
    return block & 0x3FF


class RDSDecoder:
    """Decodes RDS data from the 240 kHz FM MPX baseband."""

    def __init__(self, baseband_rate: int) -> None:
        self._baseband_rate = baseband_rate
        self._on_station_change: Optional[Callable[[str], None]] = None

        # Public decoded fields
        self.station_name: str = ""
        self.radio_text: str = ""
        self.program_type: str = ""

        # PS assembly buffer (8 chars, built 2 at a time from group 0A/0B)
        self._ps_chars: list[str] = [""] * 8
        self._ps_segment_seen: int = 0  # bitmask of which 2-char segments received

        # RT assembly buffer (64 chars)
        self._rt_chars: list[str] = [""] * 64
        self._rt_ab_flag: int = -1  # A/B flag for RT version tracking

        # --- DSP filters ---
        # Bandpass 54–60 kHz to isolate RDS subcarrier
        self._rds_bpf = make_bandpass_iir(54_000, 60_000, baseband_rate, order=4)
        self._rds_bpf_zi = sp_signal.sosfilt_zi(self._rds_bpf) * 0.0

        # Lowpass for RDS demodulated baseband (2.4 kHz bandwidth for 1187.5 bps)
        self._rds_lpf = make_lowpass_iir(2_400, baseband_rate, order=4)
        self._rds_lpf_zi = sp_signal.sosfilt_zi(self._rds_lpf) * 0.0

        # Decimation: reduce sample rate to ~12 kHz for cheap per-sample processing.
        # At 240 kHz baseband, decimate by 20 → 12 kHz → ~10 samples per bit.
        self._decim_factor = max(1, baseband_rate // _RDS_INTERNAL_RATE)
        self._internal_rate = baseband_rate / self._decim_factor

        # --- Bit clock recovery ---
        self._bits_per_sample = 1187.5 / self._internal_rate
        self._clock_phase: float = 0.0
        self._last_demod_sign: float = 0.0

        # --- Differential decoding ---
        self._last_bit: int = 0

        # --- Block / group sync ---
        self._bit_buffer: list[int] = []
        self._synced: bool = False
        self._block_idx: int = 0  # which block in current group (0–3)
        self._group_blocks: list[int] = [0, 0, 0, 0]  # 16-bit data per block
        self._blocks_collected: int = 0
        self._sync_errors: int = 0

    def set_on_station_change(self, cb: Callable[[str], None]) -> None:
        """Register callback for station name changes."""
        self._on_station_change = cb

    def reset(self) -> None:
        """Clear all decoded data (call on retune)."""
        self.station_name = ""
        self.radio_text = ""
        self.program_type = ""
        self._ps_chars = [""] * 8
        self._ps_segment_seen = 0
        self._rt_chars = [""] * 64
        self._rt_ab_flag = -1
        self._bit_buffer.clear()
        self._synced = False
        self._block_idx = 0
        self._blocks_collected = 0
        self._sync_errors = 0
        self._clock_phase = 0.0
        self._last_demod_sign = 0.0
        self._last_bit = 0

    def process(self, mpx: np.ndarray, pilot: np.ndarray) -> None:
        """Feed MPX baseband + filtered 19 kHz pilot. Decodes RDS data.

        Parameters
        ----------
        mpx : np.ndarray
            Full MPX baseband at baseband_rate (240 kHz typical).
        pilot : np.ndarray
            Band-pass filtered 19 kHz pilot signal (same length as mpx).
        """
        if len(mpx) < 4:
            return

        # 1. Derive 57 kHz carrier from pilot: cos(3θ) = 4cos³(θ) − 3cos(θ)
        pilot_peak = np.max(np.abs(pilot))
        if pilot_peak < 1e-8:
            return  # no pilot → no stereo → probably no RDS
        pilot_norm = pilot / pilot_peak
        carrier_57k = 4.0 * pilot_norm ** 3 - 3.0 * pilot_norm

        # 2. Bandpass filter MPX at 54–60 kHz to isolate RDS subcarrier
        rds_band, self._rds_bpf_zi = sp_signal.sosfilt(
            self._rds_bpf, mpx, zi=self._rds_bpf_zi,
        )

        # 3. Product demodulation (multiply by 57 kHz carrier)
        demod = rds_band * carrier_57k * 2.0

        # 4. Lowpass at 2.4 kHz (RDS bandwidth)
        demod_lp, self._rds_lpf_zi = sp_signal.sosfilt(
            self._rds_lpf, demod, zi=self._rds_lpf_zi,
        )

        # 5. Decimate to ~12 kHz to keep the per-sample Python loop cheap
        #    (~1200 samples/chunk instead of ~24000)
        if self._decim_factor > 1:
            demod_lp = demod_lp[::self._decim_factor]

        # 6. Clock recovery and bit extraction
        self._extract_bits(demod_lp)

    def _extract_bits(self, demod: np.ndarray) -> None:
        """Recover clock from demodulated RDS signal and extract bits."""
        for sample in demod:
            self._clock_phase += self._bits_per_sample

            # Zero-crossing based clock adjustment
            sign = 1.0 if sample >= 0 else -1.0
            if sign != self._last_demod_sign:
                # Zero crossing detected — nudge clock towards mid-symbol
                error = self._clock_phase - 0.5
                self._clock_phase -= error * 0.1  # gentle correction
            self._last_demod_sign = sign

            if self._clock_phase >= 1.0:
                self._clock_phase -= 1.0
                # Sample at mid-symbol: hard decision
                raw_bit = 1 if sample >= 0 else 0

                # Differential (biphase) decoding: data = raw XOR last_raw
                decoded = raw_bit ^ self._last_bit
                self._last_bit = raw_bit

                self._process_bit(decoded)

    def _process_bit(self, bit: int) -> None:
        """Process one decoded bit — sync and assemble blocks/groups."""
        self._bit_buffer.append(bit)

        if not self._synced:
            # Search for block sync: try to match a 26-bit block with valid CRC
            if len(self._bit_buffer) >= 26:
                if self._try_sync():
                    return
                # Keep buffer bounded during search
                if len(self._bit_buffer) > 260:
                    self._bit_buffer = self._bit_buffer[-130:]
        else:
            # Collecting bits for current block
            if len(self._bit_buffer) >= 26:
                self._decode_block()

    def _try_sync(self) -> bool:
        """Try to find block sync in the bit buffer."""
        buf = self._bit_buffer
        if len(buf) < 26:
            return False

        # Try the last 26 bits
        bits_26 = buf[-26:]
        data_16 = 0
        for b in bits_26[:16]:
            data_16 = (data_16 << 1) | b
        check_10 = 0
        for b in bits_26[16:]:
            check_10 = (check_10 << 1) | b

        syndrome = _crc10(data_16, check_10)

        # Check against all offset words
        for block_pos, offset in enumerate(_OFFSETS):
            if syndrome == offset:
                self._synced = True
                self._group_blocks[block_pos] = data_16
                self._blocks_collected = 1 << block_pos
                self._sync_errors = 0
                self._bit_buffer.clear()
                self._block_idx = (block_pos + 1) % 4
                return True
        # Also check C' offset
        if syndrome == _OFFSET_Cp:
            self._synced = True
            self._group_blocks[2] = data_16
            self._blocks_collected = 1 << 2
            self._sync_errors = 0
            self._bit_buffer.clear()
            self._block_idx = 3
            return True

        return False

    def _decode_block(self) -> None:
        """Decode a 26-bit block from the bit buffer."""
        bits_26 = self._bit_buffer[:26]
        self._bit_buffer = self._bit_buffer[26:]

        data_16 = 0
        for b in bits_26[:16]:
            data_16 = (data_16 << 1) | b
        check_10 = 0
        for b in bits_26[16:]:
            check_10 = (check_10 << 1) | b

        syndrome = _crc10(data_16, check_10)

        # Determine expected offset for current block position
        expected = _OFFSETS[self._block_idx]
        valid = (syndrome == expected)

        # Block C can also use C' offset
        if not valid and self._block_idx == 2:
            valid = (syndrome == _OFFSET_Cp)

        if valid:
            self._group_blocks[self._block_idx] = data_16
            self._blocks_collected |= (1 << self._block_idx)
            self._sync_errors = 0
        else:
            self._sync_errors += 1
            if self._sync_errors > 10:
                # Lost sync — go back to searching
                self._synced = False
                self._blocks_collected = 0
                return

        # Advance to next block
        self._block_idx = (self._block_idx + 1) % 4

        # If we wrapped around (completed block D → block A), try to decode group
        if self._block_idx == 0:
            if self._blocks_collected == 0x0F:  # all 4 blocks valid
                self._decode_group()
            self._blocks_collected = 0

    def _decode_group(self) -> None:
        """Decode a complete RDS group (4 blocks)."""
        blk_a = self._group_blocks[0]
        blk_b = self._group_blocks[1]
        blk_c = self._group_blocks[2]
        blk_d = self._group_blocks[3]

        # Group type: bits 12–15 of block B (4 bits) + version bit 11
        group_type = (blk_b >> 12) & 0x0F
        version = (blk_b >> 11) & 0x01  # 0 = A, 1 = B

        # PTY: bits 5–9 of block B
        pty_code = (blk_b >> 5) & 0x1F
        if 0 < pty_code < len(_PTY_NAMES) and _PTY_NAMES[pty_code]:
            self.program_type = _PTY_NAMES[pty_code]

        if group_type == 0:
            # Group 0A/0B: Programme Service name (2 chars per group)
            self._decode_ps(blk_b, blk_d)
        elif group_type == 2:
            # Group 2A/2B: Radio Text
            self._decode_rt(blk_b, blk_c, blk_d, version)

    def _decode_ps(self, blk_b: int, blk_d: int) -> None:
        """Decode Programme Service name from group type 0."""
        segment = blk_b & 0x03  # 2-bit segment address (0–3)
        c1 = (blk_d >> 8) & 0xFF
        c2 = blk_d & 0xFF
        idx = segment * 2

        # Only accept printable ASCII
        ch1 = chr(c1) if 0x20 <= c1 < 0x7F else " "
        ch2 = chr(c2) if 0x20 <= c2 < 0x7F else " "

        self._ps_chars[idx] = ch1
        self._ps_chars[idx + 1] = ch2
        self._ps_segment_seen |= (1 << segment)

        # All 4 segments received → assemble station name
        if self._ps_segment_seen == 0x0F:
            new_name = "".join(self._ps_chars).strip()
            if new_name and new_name != self.station_name:
                self.station_name = new_name
                logger.info("RDS PS: %r", new_name)
                if self._on_station_change is not None:
                    self._on_station_change(new_name)

    def _decode_rt(self, blk_b: int, blk_c: int, blk_d: int,
                   version: int) -> None:
        """Decode Radio Text from group type 2."""
        ab_flag = (blk_b >> 4) & 0x01
        segment = blk_b & 0x0F  # 4-bit segment address

        # A/B flag toggle → clear RT buffer (new message)
        if ab_flag != self._rt_ab_flag:
            self._rt_ab_flag = ab_flag
            self._rt_chars = [""] * 64

        if version == 0:
            # 2A: 4 chars per group (2 from block C, 2 from block D)
            idx = segment * 4
            chars = [
                (blk_c >> 8) & 0xFF, blk_c & 0xFF,
                (blk_d >> 8) & 0xFF, blk_d & 0xFF,
            ]
        else:
            # 2B: 2 chars per group (from block D only)
            idx = segment * 2
            chars = [(blk_d >> 8) & 0xFF, blk_d & 0xFF]

        for i, c in enumerate(chars):
            pos = idx + i
            if pos >= 64:
                break
            if c == 0x0D:
                # Carriage return = end of message
                self.radio_text = "".join(
                    ch if ch else " " for ch in self._rt_chars[:pos]
                ).strip()
                return
            self._rt_chars[pos] = chr(c) if 0x20 <= c < 0x7F else " "

        # Build partial RT from what we have so far
        text = "".join(ch if ch else " " for ch in self._rt_chars).strip()
        if text:
            self.radio_text = text
