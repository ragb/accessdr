"""Tests for core.dsp.rds — RDS (Radio Data System) decoder.

Covers:
  - CRC-10 polynomial correctness and syndrome computation
  - Block sync acquisition from bitstream
  - Group 0A/0B Programme Service (PS) name decode
  - Group 2A/2B Radio Text (RT) decode
  - Programme Type (PTY) extraction
  - Full DSP signal chain: carrier derivation, product demod, clock recovery
  - Bit rate accuracy and differential BPSK correctness
  - Robustness to noise and carrier phase offsets
  - Reset behaviour on retune
"""

from __future__ import annotations

import numpy as np
import pytest
from scipy import signal as sp_signal

from core.dsp.rds import (
    RDSDecoder,
    _crc10,
    _OFFSET_A,
    _OFFSET_B,
    _OFFSET_C,
    _OFFSET_Cp,
    _OFFSET_D,
)

# -----------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------

def _raw_crc(data_16: int) -> int:
    """Compute the raw CRC-10 for 16-bit data (before XOR with offset)."""
    block = data_16 << 10
    for i in range(25, 9, -1):
        if block & (1 << i):
            block ^= 0x5B9 << (i - 10)
    return block & 0x3FF


def _make_block_bits(data_16: int, offset: int) -> list[int]:
    """Encode a 26-bit RDS block: 16 data bits + 10 check bits."""
    check = _raw_crc(data_16) ^ offset
    bits: list[int] = []
    for i in range(15, -1, -1):
        bits.append((data_16 >> i) & 1)
    for i in range(9, -1, -1):
        bits.append((check >> i) & 1)
    return bits


def _make_group_bits(
    pi: int,
    blk_b: int,
    blk_c: int,
    blk_d: int,
    *,
    c_prime: bool = False,
) -> list[int]:
    """Build a complete 104-bit RDS group (blocks A-B-C-D)."""
    offset_c = _OFFSET_Cp if c_prime else _OFFSET_C
    return (
        _make_block_bits(pi, _OFFSET_A)
        + _make_block_bits(blk_b, _OFFSET_B)
        + _make_block_bits(blk_c, offset_c)
        + _make_block_bits(blk_d, _OFFSET_D)
    )


def _feed_bits(decoder: RDSDecoder, bits: list[int]) -> None:
    """Feed a list of raw decoded bits directly into the protocol layer."""
    for b in bits:
        decoder._process_bit(b)


# -----------------------------------------------------------------------
# CRC-10
# -----------------------------------------------------------------------

class TestCRC10:
    """Verify CRC-10 polynomial and syndrome computation."""

    def test_syndrome_matches_offset_a(self):
        data = 0xABCD
        check = _raw_crc(data) ^ _OFFSET_A
        assert _crc10(data, check) == _OFFSET_A

    def test_syndrome_matches_offset_b(self):
        data = 0x1234
        check = _raw_crc(data) ^ _OFFSET_B
        assert _crc10(data, check) == _OFFSET_B

    def test_syndrome_matches_offset_c(self):
        data = 0x5678
        check = _raw_crc(data) ^ _OFFSET_C
        assert _crc10(data, check) == _OFFSET_C

    def test_syndrome_matches_offset_c_prime(self):
        data = 0x9ABC
        check = _raw_crc(data) ^ _OFFSET_Cp
        assert _crc10(data, check) == _OFFSET_Cp

    def test_syndrome_matches_offset_d(self):
        data = 0xDEF0
        check = _raw_crc(data) ^ _OFFSET_D
        assert _crc10(data, check) == _OFFSET_D

    @pytest.mark.parametrize("offset", [_OFFSET_A, _OFFSET_B, _OFFSET_C, _OFFSET_D, _OFFSET_Cp])
    def test_all_offsets_with_zero_data(self, offset):
        check = _raw_crc(0x0000) ^ offset
        assert _crc10(0x0000, check) == offset

    @pytest.mark.parametrize("offset", [_OFFSET_A, _OFFSET_B, _OFFSET_C, _OFFSET_D, _OFFSET_Cp])
    def test_all_offsets_with_max_data(self, offset):
        check = _raw_crc(0xFFFF) ^ offset
        assert _crc10(0xFFFF, check) == offset

    def test_wrong_check_bits_give_wrong_syndrome(self):
        data = 0x1234
        check = _raw_crc(data) ^ _OFFSET_A
        # Flip one bit in check
        bad_check = check ^ 0x001
        assert _crc10(data, bad_check) != _OFFSET_A

    def test_bit_error_in_data_gives_wrong_syndrome(self):
        data = 0x1234
        check = _raw_crc(data) ^ _OFFSET_A
        bad_data = data ^ 0x0010  # flip one bit
        assert _crc10(bad_data, check) != _OFFSET_A


# -----------------------------------------------------------------------
# Block sync
# -----------------------------------------------------------------------

class TestBlockSync:
    """Verify sync acquisition from raw bitstream."""

    def test_sync_on_block_a(self):
        decoder = RDSDecoder(240_000)
        bits = _make_block_bits(0x1234, _OFFSET_A)
        _feed_bits(decoder, bits)
        assert decoder._synced
        assert decoder._debug_syncs == 1
        assert decoder._block_idx == 1  # expecting block B next

    def test_sync_on_block_b(self):
        decoder = RDSDecoder(240_000)
        bits = _make_block_bits(0x5678, _OFFSET_B)
        _feed_bits(decoder, bits)
        assert decoder._synced
        assert decoder._block_idx == 2

    def test_sync_on_block_c_prime(self):
        decoder = RDSDecoder(240_000)
        bits = _make_block_bits(0x9ABC, _OFFSET_Cp)
        _feed_bits(decoder, bits)
        assert decoder._synced
        assert decoder._block_idx == 3

    def test_no_sync_on_random_26_bits(self):
        """Random bits should rarely produce a valid sync (p ≈ 5/1024)."""
        rng = np.random.default_rng(42)
        decoder = RDSDecoder(240_000)
        # Feed 10000 random bits — may get a few false syncs, but mostly not
        bits = rng.integers(0, 2, size=10000).tolist()
        _feed_bits(decoder, bits)
        # With ~10000/26 ≈ 385 attempts and p ≈ 0.005, expect < 5 false syncs
        # The important thing is that it doesn't crash
        assert decoder._debug_syncs < 20  # generous upper bound

    def test_sync_lost_after_many_failures(self):
        decoder = RDSDecoder(240_000)
        # Sync on a valid block
        bits = _make_block_bits(0x1234, _OFFSET_A)
        _feed_bits(decoder, bits)
        assert decoder._synced
        # Feed 55 blocks of all-zeros — deterministic bad data that won't
        # accidentally match any offset syndrome.  Threshold is 50.
        _feed_bits(decoder, [0] * (26 * 55))
        assert not decoder._synced


# -----------------------------------------------------------------------
# Programme Service (PS) — Group 0A
# -----------------------------------------------------------------------

class TestProgrammeService:
    """Verify PS name assembly from group type 0A."""

    def _send_ps(self, decoder: RDSDecoder, name: str, pi: int = 0x1234) -> None:
        """Send 4 group-0A messages to spell out an 8-char PS name."""
        name = name.ljust(8)[:8]
        for seg in range(4):
            blk_b = 0x0000 | seg  # group 0A, segment address
            c1, c2 = ord(name[seg * 2]), ord(name[seg * 2 + 1])
            blk_d = (c1 << 8) | c2
            _feed_bits(decoder, _make_group_bits(pi, blk_b, 0, blk_d))

    def test_decode_full_ps(self):
        decoder = RDSDecoder(240_000)
        self._send_ps(decoder, "TEST FM")
        assert decoder.station_name == "TEST FM"

    def test_decode_ps_with_special_chars(self):
        decoder = RDSDecoder(240_000)
        self._send_ps(decoder, "FM 98.5")
        assert decoder.station_name == "FM 98.5"

    def test_ps_trims_trailing_spaces(self):
        decoder = RDSDecoder(240_000)
        self._send_ps(decoder, "RDS ")
        assert decoder.station_name == "RDS"

    def test_ps_callback_fires(self):
        decoder = RDSDecoder(240_000)
        received: list[str] = []
        decoder.set_on_station_change(received.append)
        self._send_ps(decoder, "HELLO FM")
        assert received == ["HELLO FM"]

    def test_ps_callback_only_on_change(self):
        decoder = RDSDecoder(240_000)
        received: list[str] = []
        decoder.set_on_station_change(received.append)
        self._send_ps(decoder, "RADIO 1")
        self._send_ps(decoder, "RADIO 1")  # same name again
        assert received == ["RADIO 1"]  # only one callback

    def test_ps_segments_out_of_order(self):
        decoder = RDSDecoder(240_000)
        name = "ABCDEFGH"
        pi = 0x1234
        # Send segments 3, 1, 0, 2 (out of order)
        for seg in [3, 1, 0, 2]:
            blk_b = 0x0000 | seg
            c1, c2 = ord(name[seg * 2]), ord(name[seg * 2 + 1])
            blk_d = (c1 << 8) | c2
            _feed_bits(decoder, _make_group_bits(pi, blk_b, 0, blk_d))
        assert decoder.station_name == "ABCDEFGH"


# -----------------------------------------------------------------------
# Radio Text (RT) — Group 2A
# -----------------------------------------------------------------------

class TestRadioText:
    """Verify Radio Text decode from group type 2A."""

    def _send_rt_2a(
        self,
        decoder: RDSDecoder,
        text: str,
        pi: int = 0x1234,
        ab_flag: int = 0,
    ) -> None:
        """Send group-2A messages to transmit radio text.

        Pads to a multiple of 4 chars and sends the appropriate segments.
        """
        # Pad to multiple of 4
        padded = text.ljust(((len(text) + 3) // 4) * 4)
        n_segments = len(padded) // 4
        for seg in range(n_segments):
            blk_b = (0x2 << 12) | (ab_flag << 4) | seg
            idx = seg * 4
            chars = padded[idx:idx + 4]
            blk_c = (ord(chars[0]) << 8) | ord(chars[1])
            blk_d = (ord(chars[2]) << 8) | ord(chars[3])
            _feed_bits(decoder, _make_group_bits(pi, blk_b, blk_c, blk_d))

    def test_decode_short_rt(self):
        decoder = RDSDecoder(240_000)
        # First establish sync with a group 0A
        _feed_bits(decoder, _make_group_bits(0x1234, 0, 0, 0))
        self._send_rt_2a(decoder, "Hello World")
        assert "Hello World" in decoder.radio_text

    def test_rt_ab_flag_clears_buffer(self):
        decoder = RDSDecoder(240_000)
        _feed_bits(decoder, _make_group_bits(0x1234, 0, 0, 0))
        self._send_rt_2a(decoder, "Old text here", ab_flag=0)
        assert "Old text" in decoder.radio_text
        # New message with flipped A/B flag should clear
        self._send_rt_2a(decoder, "New!", ab_flag=1)
        assert "New!" in decoder.radio_text
        assert "Old" not in decoder.radio_text


# -----------------------------------------------------------------------
# Programme Type (PTY)
# -----------------------------------------------------------------------

class TestProgrammeType:
    """Verify PTY extraction from block B."""

    @pytest.mark.parametrize(
        "pty_code, expected",
        [(1, "News"), (3, "Sports"), (5, "Rock"), (15, "Classical")],
    )
    def test_pty_extracted(self, pty_code: int, expected: str):
        decoder = RDSDecoder(240_000)
        blk_b = pty_code << 5  # PTY in bits 5-9
        # PTY requires confirmation (same code seen twice)
        _feed_bits(decoder, _make_group_bits(0x1234, blk_b, 0, 0))
        _feed_bits(decoder, _make_group_bits(0x1234, blk_b, 0, 0))
        assert decoder.program_type == expected


# -----------------------------------------------------------------------
# Group counting and block statistics
# -----------------------------------------------------------------------

class TestGroupStats:
    """Verify group decode counting and block pass/fail stats."""

    def test_four_clean_groups(self):
        decoder = RDSDecoder(240_000)
        for seg in range(4):
            _feed_bits(
                decoder,
                _make_group_bits(0x1234, seg, 0, (ord("A") << 8) | ord("B")),
            )
        assert decoder._debug_groups == 4
        # First group: block A triggers sync (1 sync + 3 decoded blocks).
        # Remaining 3 groups: 12 decoded blocks.  Total = 15.
        assert decoder._debug_block_ok == 15
        assert decoder._debug_block_fail == 0

    def test_single_bit_error_corrected(self):
        decoder = RDSDecoder(240_000)
        # First valid group to establish sync
        _feed_bits(decoder, _make_group_bits(0x1234, 0, 0, 0))
        # Corrupt exactly 1 bit in second group's block C — CRC should correct it
        bits = _make_group_bits(0x1234, 1, 0, 0)
        bits[52 + 5] ^= 1  # flip a single bit in block C
        _feed_bits(decoder, bits)
        assert decoder._synced
        # Single-bit error correction means this block should pass, not fail
        assert decoder._debug_block_fail == 0

    def test_one_corrupted_block_does_not_lose_sync(self):
        decoder = RDSDecoder(240_000)
        # First valid group to establish sync
        _feed_bits(decoder, _make_group_bits(0x1234, 0, 0, 0))
        # Corrupt 2 bits in second group's block C (block_idx=2)
        # — exceeds single-bit CRC error-correction capability
        bits = _make_group_bits(0x1234, 1, 0, 0)
        bits[52 + 5] ^= 1  # flip bit 1 in block C
        bits[52 + 8] ^= 1  # flip bit 2 in block C
        _feed_bits(decoder, bits)
        # Should still be synced (1 error < 10 threshold)
        assert decoder._synced
        assert decoder._debug_block_fail >= 1


# -----------------------------------------------------------------------
# Reset
# -----------------------------------------------------------------------

class TestReset:
    """Verify reset clears all decoded state."""

    def test_reset_clears_ps_and_rt(self):
        decoder = RDSDecoder(240_000)
        # Decode some data
        name = "RADIO 1 "
        for seg in range(4):
            blk_b = seg
            c1, c2 = ord(name[seg * 2]), ord(name[seg * 2 + 1])
            _feed_bits(
                decoder,
                _make_group_bits(0x1234, blk_b, 0, (c1 << 8) | c2),
            )
        assert decoder.station_name == "RADIO 1"

        decoder.reset()
        assert decoder.station_name == ""
        assert decoder.radio_text == ""
        assert decoder.program_type == ""
        assert not decoder._synced


# -----------------------------------------------------------------------
# DSP signal chain
# -----------------------------------------------------------------------

class TestDSPChain:
    """Test the full analogue signal path: carrier, demod, clock, bits."""

    RATE = 240_000

    def _make_mpx_and_pilot(
        self, duration_s: float, *, phase_offset_deg: float = 0.0
    ) -> tuple[np.ndarray, np.ndarray]:
        """Generate a synthetic MPX with 19 kHz pilot and 57 kHz RDS carrier.

        Returns (mpx, pilot_filtered).
        """
        n = int(self.RATE * duration_s)
        t = np.arange(n) / self.RATE
        pilot = 0.08 * np.cos(2 * np.pi * 19_000 * t)
        phase_rad = np.deg2rad(phase_offset_deg)
        rds = 0.02 * np.cos(2 * np.pi * 57_000 * t + phase_rad)
        mpx = pilot + rds

        pilot_sos = sp_signal.butter(
            4, [18_000, 20_000], btype="bandpass", fs=self.RATE, output="sos",
        )
        pilot_filtered = sp_signal.sosfilt(pilot_sos, pilot)
        return mpx, pilot_filtered

    def test_bit_rate_accuracy(self):
        """Verify extracted bit rate matches 1187.5 bps within 5%."""
        decoder = RDSDecoder(self.RATE)
        duration = 1.0
        mpx, pilot = self._make_mpx_and_pilot(duration)

        chunk_size = 6400
        for start in range(0, len(mpx), chunk_size):
            end = min(start + chunk_size, len(mpx))
            decoder.process(mpx[start:end], pilot[start:end])

        expected = int(1187.5 * duration)
        ratio = decoder._debug_bits / expected
        assert 0.95 <= ratio <= 1.05, (
            f"Bit rate off: got {decoder._debug_bits} bits in {duration}s "
            f"(expected ~{expected}, ratio={ratio:.3f})"
        )

    def test_constant_carrier_gives_all_zeros(self):
        """A constant-phase carrier should decode as all 0-bits (no phase change)."""
        decoder = RDSDecoder(self.RATE)
        mpx, pilot = self._make_mpx_and_pilot(0.5)

        chunk_size = 6400
        for start in range(0, len(mpx), chunk_size):
            end = min(start + chunk_size, len(mpx))
            decoder.process(mpx[start:end], pilot[start:end])

        total = decoder._debug_bit_ones + decoder._debug_bit_zeros
        assert total > 100, f"Too few bits extracted: {total}"
        zero_pct = decoder._debug_bit_zeros / total
        assert zero_pct > 0.95, (
            f"Expected mostly 0-bits for constant carrier, got {zero_pct:.1%} zeros"
        )

    def test_carrier_phase_offset_still_decodes(self):
        """Differential decode should work even with carrier phase offset."""
        decoder = RDSDecoder(self.RATE)
        # 45° offset — product demod amplitude is cos(45°) ≈ 0.71 (still strong)
        mpx, pilot = self._make_mpx_and_pilot(0.5, phase_offset_deg=45.0)

        chunk_size = 6400
        for start in range(0, len(mpx), chunk_size):
            end = min(start + chunk_size, len(mpx))
            decoder.process(mpx[start:end], pilot[start:end])

        total = decoder._debug_bit_ones + decoder._debug_bit_zeros
        assert total > 100
        zero_pct = decoder._debug_bit_zeros / total
        assert zero_pct > 0.90, (
            f"Phase offset decode failed: {zero_pct:.1%} zeros (expected >90%)"
        )

    def test_180_degree_offset_still_decodes(self):
        """180° offset flips all signs, but differential XOR cancels it."""
        decoder = RDSDecoder(self.RATE)
        mpx, pilot = self._make_mpx_and_pilot(0.5, phase_offset_deg=180.0)

        chunk_size = 6400
        for start in range(0, len(mpx), chunk_size):
            end = min(start + chunk_size, len(mpx))
            decoder.process(mpx[start:end], pilot[start:end])

        total = decoder._debug_bit_ones + decoder._debug_bit_zeros
        assert total > 100
        zero_pct = decoder._debug_bit_zeros / total
        assert zero_pct > 0.90, (
            f"180° offset decode failed: {zero_pct:.1%} zeros (expected >90%)"
        )

    def test_chunked_processing_continuous(self):
        """Verify no state corruption across chunk boundaries."""
        decoder = RDSDecoder(self.RATE)
        mpx, pilot = self._make_mpx_and_pilot(0.5)

        # Process in very small chunks to stress boundary handling
        chunk_size = 1024
        for start in range(0, len(mpx), chunk_size):
            end = min(start + chunk_size, len(mpx))
            decoder.process(mpx[start:end], pilot[start:end])

        total = decoder._debug_bit_ones + decoder._debug_bit_zeros
        assert total > 100
        zero_pct = decoder._debug_bit_zeros / total
        assert zero_pct > 0.90

    def test_no_pilot_skips_processing(self):
        """Zero pilot signal should cause process() to return early."""
        decoder = RDSDecoder(self.RATE)
        n = 6400
        mpx = np.random.randn(n).astype(np.float64) * 0.01
        pilot = np.zeros(n, dtype=np.float64)
        decoder.process(mpx, pilot)
        assert decoder._debug_bits == 0

    def test_rds_snr_measurement(self):
        """Verify _measure_rds_snr returns positive dB for signal with RDS."""
        decoder = RDSDecoder(self.RATE)
        n = int(self.RATE * 0.1)
        t = np.arange(n) / self.RATE
        # Strong 57 kHz tone in the RDS band
        mpx = 0.1 * np.cos(2 * np.pi * 57_000 * t)
        snr = decoder._measure_rds_snr(mpx)
        assert snr > 5.0, f"Expected positive SNR for RDS carrier, got {snr:.1f} dB"

    def test_rds_snr_noise_only(self):
        """Noise-only MPX should show moderate apparent SNR from peak detection.

        Peak-bin detection over ~400 bins vs median of ~600 bins naturally
        reads ~11 dB for white noise (order statistics: peak ≈ ln(N)/ln(2)
        above median for exponentially-distributed power bins).
        """
        decoder = RDSDecoder(self.RATE)
        rng = np.random.default_rng(42)
        mpx = rng.standard_normal(24000) * 0.01
        snr = decoder._measure_rds_snr(mpx)
        assert snr < 20.0, f"Noise-only SNR too high: {snr:.1f} dB"


# -----------------------------------------------------------------------
# End-to-end BPSK signal decode
# -----------------------------------------------------------------------

def _generate_rds_bpsk_mpx(
    groups: list[list[int]],
    rate: int = 240_000,
    *,
    rds_amplitude: float = 0.02,
    pilot_amplitude: float = 0.08,
    phase_offset_deg: float = 0.0,
    noise_amplitude: float = 0.0,
) -> tuple[np.ndarray, np.ndarray]:
    """Synthesize an MPX signal with BPSK-modulated RDS data.

    Parameters
    ----------
    groups : list of [pi, blk_b, blk_c, blk_d] 16-bit ints
        Each entry is a complete RDS group to transmit.
    rate : sample rate (Hz)
    rds_amplitude : amplitude of the 57 kHz RDS subcarrier
    pilot_amplitude : amplitude of the 19 kHz pilot
    phase_offset_deg : carrier phase offset (tests differential robustness)
    noise_amplitude : additive white Gaussian noise level (0 = none)

    Returns
    -------
    mpx, pilot_filtered : np.ndarray pair at *rate*
    """
    # 1. Encode groups into a differential BPSK bitstream
    raw_bits: list[int] = []
    for pi, blk_b, blk_c, blk_d in groups:
        raw_bits.extend(_make_group_bits(pi, blk_b, blk_c, blk_d))

    # 2. Differential encode: transmit sign[n] = sign[n-1] XOR data[n]
    #    (0 = no phase change, 1 = phase flip)
    symbols: list[int] = []
    prev = 1  # start with positive phase
    for b in raw_bits:
        prev = prev ^ b  # XOR: same phase for 0, flip for 1
        symbols.append(1 if prev else -1)

    # 3. Generate baseband at 1187.5 bps
    samples_per_bit = rate / 1187.5
    n_samples = int(len(symbols) * samples_per_bit) + int(rate * 0.05)  # + 50ms lead-in
    lead_in = int(rate * 0.05)

    # Build per-sample symbol waveform (NRZ — constant within each bit period)
    sym_signal = np.ones(n_samples, dtype=np.float64)
    for i, sym in enumerate(symbols):
        start = lead_in + int(i * samples_per_bit)
        end = lead_in + int((i + 1) * samples_per_bit)
        if end > n_samples:
            end = n_samples
        if start < n_samples:
            sym_signal[start:end] = sym

    # 4. Modulate onto 57 kHz carrier
    t = np.arange(n_samples) / rate
    phase_rad = np.deg2rad(phase_offset_deg)
    carrier = np.cos(2 * np.pi * 57_000 * t + phase_rad)
    rds_signal = rds_amplitude * sym_signal * carrier

    # 5. Generate pilot
    pilot = pilot_amplitude * np.cos(2 * np.pi * 19_000 * t)

    # 6. Combine MPX
    mpx = pilot + rds_signal

    if noise_amplitude > 0:
        rng = np.random.default_rng(123)
        mpx += rng.standard_normal(n_samples) * noise_amplitude

    # 7. Filter pilot through BPF (same as demodulator uses)
    pilot_sos = sp_signal.butter(
        4, [18_000, 20_000], btype="bandpass", fs=rate, output="sos",
    )
    pilot_filtered = sp_signal.sosfilt(pilot_sos, pilot)

    return mpx, pilot_filtered


class TestEndToEnd:
    """Full signal-chain tests: BPSK modulated RDS → decoded PS/RT/PTY."""

    RATE = 240_000

    def _make_ps_groups(
        self, name: str, pi: int = 0x1234, pty: int = 0
    ) -> list[list[int]]:
        """Build 4 group-0A messages encoding an 8-char PS name."""
        name = name.ljust(8)[:8]
        groups = []
        for seg in range(4):
            blk_b = (pty << 5) | seg  # group 0A, PTY, segment
            c1, c2 = ord(name[seg * 2]), ord(name[seg * 2 + 1])
            blk_d = (c1 << 8) | c2
            groups.append([pi, blk_b, 0, blk_d])
        return groups

    def _make_rt_groups(
        self, text: str, pi: int = 0x1234, ab_flag: int = 0
    ) -> list[list[int]]:
        """Build group-2A messages encoding radio text."""
        padded = text.ljust(((len(text) + 3) // 4) * 4)
        groups = []
        for seg in range(len(padded) // 4):
            blk_b = (0x2 << 12) | (ab_flag << 4) | seg
            idx = seg * 4
            chars = padded[idx:idx + 4]
            blk_c = (ord(chars[0]) << 8) | ord(chars[1])
            blk_d = (ord(chars[2]) << 8) | ord(chars[3])
            groups.append([pi, blk_b, blk_c, blk_d])
        return groups

    def _feed_mpx(
        self, decoder: RDSDecoder, mpx: np.ndarray, pilot: np.ndarray,
        chunk_size: int = 6400,
    ) -> None:
        for start in range(0, len(mpx), chunk_size):
            end = min(start + chunk_size, len(mpx))
            decoder.process(mpx[start:end], pilot[start:end])

    def test_decode_ps_from_bpsk(self):
        """Full chain: BPSK signal → PS name decode."""
        decoder = RDSDecoder(self.RATE)
        # Repeat PS groups several times — first occurrence acquires sync,
        # subsequent ones carry the actual data.
        groups = self._make_ps_groups("TEST FM") * 6
        mpx, pilot = _generate_rds_bpsk_mpx(groups, self.RATE)
        self._feed_mpx(decoder, mpx, pilot)

        assert decoder._debug_syncs > 0, "No sync acquired"
        assert decoder._debug_groups > 0, f"No groups decoded (syncs={decoder._debug_syncs})"
        assert decoder.station_name == "TEST FM", (
            f"Expected 'TEST FM', got {decoder.station_name!r} "
            f"(syncs={decoder._debug_syncs}, groups={decoder._debug_groups}, "
            f"blk_ok={decoder._debug_block_ok}, blk_fail={decoder._debug_block_fail})"
        )

    def test_decode_ps_with_phase_offset(self):
        """Differential decode should handle arbitrary carrier phase."""
        decoder = RDSDecoder(self.RATE)
        groups = self._make_ps_groups("PHASE90") * 6
        mpx, pilot = _generate_rds_bpsk_mpx(
            groups, self.RATE, phase_offset_deg=90.0,
        )
        self._feed_mpx(decoder, mpx, pilot)

        assert decoder._debug_syncs > 0, "No sync with 90° phase offset"
        assert decoder.station_name == "PHASE90", (
            f"Got {decoder.station_name!r} with 90° offset"
        )

    def test_decode_pty_from_bpsk(self):
        """Full chain: PTY code in block B → programme type string."""
        decoder = RDSDecoder(self.RATE)
        groups = self._make_ps_groups("PTY TEST", pty=5) * 6  # 5 = Rock
        mpx, pilot = _generate_rds_bpsk_mpx(groups, self.RATE)
        self._feed_mpx(decoder, mpx, pilot)

        assert decoder.program_type == "Rock", (
            f"Expected 'Rock', got {decoder.program_type!r}"
        )

    def test_decode_rt_from_bpsk(self):
        """Full chain: group 2A BPSK signal → radio text decode."""
        decoder = RDSDecoder(self.RATE)
        # Send a sync group first, then RT groups, repeat several times
        sync_groups = self._make_ps_groups("RTTEST") * 2
        rt_groups = self._make_rt_groups("Hello World")
        groups = sync_groups + rt_groups * 4
        mpx, pilot = _generate_rds_bpsk_mpx(groups, self.RATE)
        self._feed_mpx(decoder, mpx, pilot)

        assert decoder._debug_groups > 0, "No groups decoded"
        assert "Hello World" in decoder.radio_text, (
            f"Expected 'Hello World' in RT, got {decoder.radio_text!r}"
        )

    def test_decode_with_noise(self):
        """PS decode under moderate noise (SNR ~20 dB)."""
        decoder = RDSDecoder(self.RATE)
        groups = self._make_ps_groups("NOISY") * 12  # more repeats for noise
        mpx, pilot = _generate_rds_bpsk_mpx(
            groups, self.RATE, noise_amplitude=0.002,
        )
        self._feed_mpx(decoder, mpx, pilot)

        # With moderate noise, we expect at least some syncs and groups
        assert decoder._debug_syncs > 0, "No sync under noise"
        # PS may or may not fully decode depending on BER — just verify groups work
        assert decoder._debug_groups > 0, (
            f"No groups decoded under noise "
            f"(syncs={decoder._debug_syncs}, blk_fail={decoder._debug_block_fail})"
        )


# -----------------------------------------------------------------------
# Decoder construction
# -----------------------------------------------------------------------

class TestConstruction:
    """Verify decoder initialisation at various sample rates."""

    def test_default_240k(self):
        d = RDSDecoder(240_000)
        assert d._decim_factor == 20
        assert abs(d._internal_rate - 12_000) < 1

    def test_baseband_192k(self):
        d = RDSDecoder(192_000)
        assert d._decim_factor == max(1, 192_000 // 11875)
        assert d._internal_rate > 0
        assert abs(d._bits_per_sample - 1187.5 / d._internal_rate) < 1e-10

    def test_baseband_below_nyquist_raises(self):
        """RDS requires >120 kHz sample rate (57 kHz subcarrier).

        At 48 kHz the 54-60 kHz BPF exceeds Nyquist, so construction
        should raise ValueError from scipy's filter design.
        """
        with pytest.raises(ValueError):
            RDSDecoder(48_000)
