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

Demodulation approach (based on PySDR architecture):
  Free-running complex LO at 3× the estimated pilot frequency shifts
  the 57 kHz RDS subcarrier to baseband.  LPF + decimation produces a
  complex baseband at ~20 kHz.  AGC normalises amplitude so the
  Mueller-Muller timing error detector operates at consistent scale.
  Cubic interpolation between samples gives sub-sample timing precision.
  Differential BPSK decode via Re{z[n]·conj(z[n-1])} is insensitive to
  constant and slowly-varying carrier phase offset.
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

import numpy as np
from scipy import signal as sp_signal


logger = logging.getLogger(__name__)

# CRC-10 generator polynomial for RDS: x^10 + x^8 + x^7 + x^5 + x^4 + x^3 + 1
_CRC_POLY = 0x5B9  # 0b10110111001 — full 11-bit generator including x^10

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


def _crc10(data_bits: int, check_bits: int) -> int:
    """Compute CRC-10 syndrome for a 26-bit block (16 data + 10 check)."""
    block = (data_bits << 10) | check_bits
    for i in range(25, 9, -1):
        if block & (1 << i):
            block ^= _CRC_POLY << (i - 10)
    return block & 0x3FF


def _build_single_bit_syndromes() -> dict[int, int]:
    """Pre-compute CRC-10 syndromes for all 26 single-bit error positions.

    Returns a dict mapping syndrome → bit position (0 = MSB of data).
    Used for single-bit error correction: if the CRC fails, XOR the
    received syndrome with the expected offset word; if the result is
    in this table, the block has exactly one bit error at the indicated
    position and can be corrected.
    """
    table: dict[int, int] = {}
    for pos in range(26):
        # Build a 26-bit block with a single 1-bit at position `pos`
        # pos=0 → MSB of data (bit 25), pos=25 → LSB of check (bit 0)
        bit_val = 1 << (25 - pos)
        data_16 = (bit_val >> 10) & 0xFFFF
        check_10 = bit_val & 0x3FF
        syn = _crc10(data_16, check_10)
        table[syn] = pos
    return table


_SINGLE_BIT_SYNDROMES = _build_single_bit_syndromes()


def _cubic_interp(buf: np.ndarray, idx: int, frac: float) -> complex:
    """Catmull-Rom cubic interpolation at buf[idx + frac]."""
    s0 = buf[idx - 1]
    s1 = buf[idx]
    s2 = buf[idx + 1]
    s3 = buf[idx + 2]
    a = -0.5 * s0 + 1.5 * s1 - 1.5 * s2 + 0.5 * s3
    b = s0 - 2.5 * s1 + 2.0 * s2 - 0.5 * s3
    c = -0.5 * s0 + 0.5 * s2
    d = s1
    return complex(((a * frac + b) * frac + c) * frac + d)


class RDSDecoder:
    """Decodes RDS data from the 240 kHz FM MPX baseband."""

    def __init__(self, baseband_rate: int) -> None:
        if baseband_rate < 114_001:
            raise ValueError(
                f"Sample rate {baseband_rate} Hz too low for RDS "
                f"(need >114 kHz for 57 kHz subcarrier)"
            )

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

        # PTY confirmation: only report after seeing the same code twice
        self._pty_candidate: int = -1
        self._pty_confirm_count: int = 0

        # --- Free-running LO for 57 kHz → baseband shift ---
        self._lo_phase: float = 0.0
        self._pilot_freq_est: float = 19_000.0

        # --- LPF for complex baseband (after frequency shift) ---
        from .filters import make_lowpass_iir
        self._rds_lpf = make_lowpass_iir(4_000, baseband_rate, order=4)
        self._rds_lpf_zi = sp_signal.sosfilt_zi(self._rds_lpf) * 0.0
        self._rds_lpf_zi_q = sp_signal.sosfilt_zi(self._rds_lpf) * 0.0

        # --- Decimation to ~20 kHz → ~16.8 samples/symbol ---
        _RDS_INTERNAL_RATE = 19_000
        self._decim_factor = max(1, baseband_rate // _RDS_INTERNAL_RATE)
        self._internal_rate = baseband_rate / self._decim_factor

        # --- Symbol timing recovery ---
        self._samples_per_symbol = self._internal_rate / 1187.5
        self._bits_per_sample = 1187.5 / self._internal_rate  # backward compat
        self._sample_buf = np.zeros(0, dtype=np.complex128)
        self._mm_pos: float = 1.0  # fractional position in sample buffer
        self._prev_sample: complex = 0j  # previous symbol sample (complex)
        self._mm_count: int = 0  # symbols seen
        self._mm_gain: float = 0.1  # zero-crossing PLL gain

        # --- AGC ---
        self._agc_gain: float = 1.0

        # --- Block / group sync ---
        self._bit_buffer: list[int] = []
        self._synced: bool = False
        self._block_idx: int = 0  # which block in current group (0–3)
        self._group_blocks: list[int] = [0, 0, 0, 0]  # 16-bit data per block
        self._blocks_collected: int = 0
        self._sync_errors: int = 0
        self._debug_chunks: int = 0
        self._debug_bits: int = 0
        self._debug_syncs: int = 0
        self._debug_groups: int = 0
        self._debug_block_ok: int = 0
        self._debug_block_fail: int = 0
        self._debug_bit_ones: int = 0   # count of decoded 1-bits
        self._debug_bit_zeros: int = 0  # count of decoded 0-bits

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
        self._pty_candidate = -1
        self._pty_confirm_count = 0
        self._bit_buffer.clear()
        self._synced = False
        self._block_idx = 0
        self._blocks_collected = 0
        self._sync_errors = 0
        self._lo_phase = 0.0
        self._pilot_freq_est = 19_000.0
        self._rds_lpf_zi = sp_signal.sosfilt_zi(self._rds_lpf) * 0.0
        self._rds_lpf_zi_q = sp_signal.sosfilt_zi(self._rds_lpf) * 0.0
        self._sample_buf = np.zeros(0, dtype=np.complex128)
        self._mm_pos = 1.0
        self._prev_sample = 0j
        self._mm_count = 0
        self._agc_gain = 1.0

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

        # 1. Check pilot presence
        pilot_peak_iir = float(np.max(np.abs(pilot)))
        if pilot_peak_iir < 1e-8:
            self._debug_chunks += 1
            return

        # 2. Estimate pilot frequency for carrier tracking
        if len(pilot) > 100:
            pilot_pow = float(np.mean(np.square(pilot)))
            if pilot_pow > 1e-12:
                r1 = float(np.mean(pilot[1:] * pilot[:-1])) / pilot_pow
                r1 = max(-1.0, min(1.0, r1))
                f_est = self._baseband_rate / (2.0 * np.pi) * float(np.arccos(r1))
                if 18_500 < f_est < 19_500:
                    self._pilot_freq_est += 0.3 * (f_est - self._pilot_freq_est)

        # 3. Free-running LO at 3× pilot frequency — shift 57 kHz to DC
        carrier_freq = 3.0 * self._pilot_freq_est
        n = len(mpx)
        phase_inc = 2.0 * np.pi * carrier_freq / self._baseband_rate
        phases = self._lo_phase + phase_inc * np.arange(n, dtype=np.float64)
        self._lo_phase = float((phases[-1] + phase_inc) % (2.0 * np.pi))
        lo = np.exp(-1j * phases)
        bb = mpx * lo

        # 4. Lowpass I and Q (4 kHz — covers RDS main lobe + transitions)
        bb_i, self._rds_lpf_zi = sp_signal.sosfilt(
            self._rds_lpf, bb.real, zi=self._rds_lpf_zi,
        )
        bb_q, self._rds_lpf_zi_q = sp_signal.sosfilt(
            self._rds_lpf, bb.imag, zi=self._rds_lpf_zi_q,
        )

        # 5. Decimate to ~20 kHz
        if self._decim_factor > 1:
            bb_i = bb_i[::self._decim_factor]
            bb_q = bb_q[::self._decim_factor]
        demod = (bb_i + 1j * bb_q).astype(np.complex128)

        # 6. AGC: normalise to ~unit RMS so M&M error scale is consistent
        rms = float(np.sqrt(np.mean(np.abs(demod) ** 2)))
        if rms > 1e-10:
            self._agc_gain += 0.3 * (1.0 / rms - self._agc_gain)
        demod = demod * self._agc_gain

        # 7. Mueller-Muller timing recovery + differential BPSK decode
        self._extract_bits(demod)

        # Debug: log RDS activity every ~5 seconds (~185 chunks at 37/s)
        self._debug_chunks += 1
        if self._debug_chunks % 185 == 0:
            rds_snr = self._measure_rds_snr(mpx)

            demod_re = demod.real
            signs = np.sign(demod_re)
            sign_changes = np.count_nonzero(np.diff(signs))
            sign_change_pct = 100.0 * sign_changes / max(len(signs) - 1, 1)

            if rms > 1e-10:
                above_half = np.count_nonzero(np.abs(demod) > 0.5 * rms * self._agc_gain)
                bimodal_pct = 100.0 * above_half / max(len(demod), 1)
            else:
                bimodal_pct = 0.0

            logger.info(
                "RDS debug: chunks=%d bits=%d synced=%s syncs=%d groups=%d "
                "blk_ok=%d blk_fail=%d rms=%.5f agc=%.1f pilot=%.5f "
                "ones=%d zeros=%d rds_snr=%.1fdB "
                "sign_chg=%.1f%% bimodal=%.1f%% pilot_f=%.1fHz",
                self._debug_chunks, self._debug_bits, self._synced,
                self._debug_syncs, self._debug_groups,
                self._debug_block_ok, self._debug_block_fail,
                rms, self._agc_gain, pilot_peak_iir,
                self._debug_bit_ones, self._debug_bit_zeros,
                rds_snr, sign_change_pct, bimodal_pct,
                self._pilot_freq_est,
            )

    def _measure_rds_snr(self, mpx: np.ndarray) -> float:
        """Measure RDS subcarrier SNR using peak-bin detection."""
        N = len(mpx)
        if N < 1024:
            return 0.0
        window = np.hanning(N)
        spectrum = np.abs(np.fft.rfft(mpx * window)) ** 2
        freq_res = self._baseband_rate / N

        def _bin(hz: float) -> int:
            return min(len(spectrum) - 1, max(0, int(round(hz / freq_res))))

        def _peak_power(lo_hz: float, hi_hz: float) -> float:
            lo, hi = _bin(lo_hz), _bin(hi_hz)
            if hi <= lo:
                return 1e-30
            return float(np.max(spectrum[lo:hi]))

        def _median_power(lo_hz: float, hi_hz: float) -> float:
            lo, hi = _bin(lo_hz), _bin(hi_hz)
            if hi <= lo:
                return 1e-30
            return float(np.median(spectrum[lo:hi]))

        pilot_peak = _peak_power(18_500, 19_500)
        rds_peak = _peak_power(55_000, 59_000)
        noise_floor = _median_power(70_000, 76_000)

        if noise_floor > 1e-30:
            pilot_snr = 10.0 * np.log10(pilot_peak / noise_floor)
            rds_snr = 10.0 * np.log10(rds_peak / noise_floor)
            logger.info(
                "MPX spectrum: pilot_peak=%.1fdB rds_peak=%.1fdB "
                "noise_floor=%.1fdB | pilot_snr=%.1fdB rds_snr=%.1fdB",
                10.0 * np.log10(max(pilot_peak, 1e-30)),
                10.0 * np.log10(max(rds_peak, 1e-30)),
                10.0 * np.log10(max(noise_floor, 1e-30)),
                pilot_snr, rds_snr,
            )
            return rds_snr

        return 0.0

    def _extract_bits(self, demod: np.ndarray) -> None:
        """Symbol-rate sampling with complex differential BPSK decode.

        Uses cubic interpolation at the nominal symbol rate.  Differential
        decode via Re{z[n] * conj(z[n-1])} is phase-invariant — works
        regardless of the carrier phase offset from the free-running LO.
        A slow PLL nudges the sampling phase toward symbol centres using
        amplitude dips at transitions (magnitude-based, also phase-invariant).
        """
        buf = np.concatenate([self._sample_buf, demod])
        sps = self._samples_per_symbol
        pos = self._mm_pos

        while True:
            idx = int(pos)
            if idx < 1 or idx + 2 >= len(buf):
                break
            frac = pos - idx

            sample = _cubic_interp(buf, idx, frac)

            if self._mm_count >= 1:
                prev = self._prev_sample

                # Clock recovery: detect phase flips via complex product.
                # A negative real product means the phase jumped ~180°
                # (symbol transition).  Interpolate the transition time
                # and nudge the clock.
                dp = (sample * prev.conjugate()).real
                if dp < 0:
                    mag_curr = abs(sample)
                    mag_prev = abs(prev)
                    total = mag_prev + mag_curr
                    if total > 1e-12:
                        t_frac = mag_prev / total
                    else:
                        t_frac = 0.5
                    zc_pos = (pos - sps) + t_frac * sps
                    expected_next = zc_pos + sps * 0.5
                    phase_err = expected_next - pos
                    while phase_err > sps * 0.5:
                        phase_err -= sps
                    while phase_err < -sps * 0.5:
                        phase_err += sps
                    pos += self._mm_gain * phase_err

                # Complex differential decode: Re{z[n]·conj(z[n-1])}
                # Positive → same phase → bit 0; negative → flip → bit 1
                bit = 0 if dp > 0 else 1
                self._debug_bits += 1
                if bit:
                    self._debug_bit_ones += 1
                else:
                    self._debug_bit_zeros += 1
                self._process_bit(bit)

            self._prev_sample = sample
            self._mm_count = min(self._mm_count + 1, 3)
            pos += sps

        # Keep tail of buffer for continuity across chunks.
        keep = min(len(buf), int(sps) + 4)
        start = len(buf) - keep
        self._sample_buf = buf[start:].copy()
        self._mm_pos = pos - start

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
                self._debug_syncs += 1
                logger.debug("RDS sync on block %d", block_pos)
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
                expected = _OFFSET_Cp

        # Single-bit error correction
        if not valid:
            error_syn = syndrome ^ expected
            if error_syn in _SINGLE_BIT_SYNDROMES:
                bit_pos = _SINGLE_BIT_SYNDROMES[error_syn]
                if bit_pos < 16:
                    data_16 ^= 1 << (15 - bit_pos)
                valid = True
            elif self._block_idx == 2:
                error_syn_cp = syndrome ^ _OFFSET_Cp
                if error_syn_cp in _SINGLE_BIT_SYNDROMES:
                    bit_pos = _SINGLE_BIT_SYNDROMES[error_syn_cp]
                    if bit_pos < 16:
                        data_16 ^= 1 << (15 - bit_pos)
                    valid = True

        if valid:
            self._group_blocks[self._block_idx] = data_16
            self._blocks_collected |= (1 << self._block_idx)
            self._sync_errors = 0
            self._debug_block_ok += 1
        else:
            self._sync_errors += 1
            self._debug_block_fail += 1
            if self._debug_block_fail <= 20:
                logger.debug(
                    "RDS blk fail: idx=%d syn=0x%03X exp=0x%03X xor=0x%03X",
                    self._block_idx, syndrome, expected, syndrome ^ expected,
                )
            if self._sync_errors > 50:
                self._synced = False
                self._blocks_collected = 0
                return

        # Advance to next block
        self._block_idx = (self._block_idx + 1) % 4

        # If we wrapped around (completed block D → block A), try to decode group.
        if self._block_idx == 0:
            collected = self._blocks_collected
            if collected == 0x0F:
                self._decode_group(collected)
                self._debug_groups += 1
            elif (collected & 0x03) == 0x03:
                self._decode_group(collected)
            self._blocks_collected = 0

    def _decode_group(self, collected: int) -> None:
        """Decode an RDS group (full or partial).

        Parameters
        ----------
        collected : int
            Bitmask of which blocks passed CRC (0x0F = all four).
        """
        blk_b = self._group_blocks[1]

        # Block B carries group type and PTY — required for any decode
        if not (collected & 0x02):
            return

        # Group type: bits 12–15 of block B (4 bits) + version bit 11
        group_type = (blk_b >> 12) & 0x0F
        version = (blk_b >> 11) & 0x01  # 0 = A, 1 = B

        # PTY: bits 5–9 of block B — confirmed after seeing same code twice
        pty_code = (blk_b >> 5) & 0x1F
        if 0 < pty_code < len(_PTY_NAMES) and _PTY_NAMES[pty_code]:
            if pty_code == self._pty_candidate:
                self._pty_confirm_count += 1
                if self._pty_confirm_count >= 2:
                    self.program_type = _PTY_NAMES[pty_code]
            else:
                self._pty_candidate = pty_code
                self._pty_confirm_count = 1

        if group_type == 0 and (collected & 0x08):
            # Group 0A/0B: PS name — needs blocks B and D
            self._decode_ps(blk_b, self._group_blocks[3])
        elif group_type == 2 and (collected & 0x0C) == 0x0C:
            # Group 2A: Radio Text — needs blocks B, C, and D
            self._decode_rt(blk_b, self._group_blocks[2],
                            self._group_blocks[3], version)

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
