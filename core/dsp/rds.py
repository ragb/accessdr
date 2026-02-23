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

Demodulation approach:
  Real-only coherent product demodulation with differential decode.
  The 57 kHz carrier is derived from the 19 kHz stereo pilot via the
  triple-frequency identity cos(3θ) = 4cos³(θ) − 3cos(θ).  After
  mixing and lowpass filtering, differential BPSK decode (XOR of
  consecutive bit signs) recovers data regardless of carrier phase.
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

        # PTY confirmation: only report after seeing the same code twice
        # (reduces false positives from noise-matching CRC by chance)
        self._pty_candidate: int = -1
        self._pty_confirm_count: int = 0

        # --- DSP filters ---
        # FIR bandpass 55.5–58.5 kHz to isolate RDS subcarrier.
        # 501-tap Kaiser (beta=8) gives ~97 dB rejection at 53 kHz (L-R edge)
        # vs only ~10 dB for the previous 4th-order IIR Butterworth at 54–60 kHz.
        # This sharp cutoff is critical: the L-R stereo subcarrier (23–53 kHz)
        # has spectral tails from audio content above 15 kHz that leak into the
        # RDS band and overwhelm the weak RDS signal without adequate rejection.
        _BPF_TAPS = 501
        self._rds_bpf = sp_signal.firwin(
            _BPF_TAPS, [55_500, 58_500], pass_zero=False,
            fs=baseband_rate, window=("kaiser", 8),
        )
        self._rds_bpf_zi = sp_signal.lfilter_zi(self._rds_bpf, [1.0]) * 0.0

        # Pilot delay buffer: the FIR BPF introduces (N-1)/2 samples of group
        # delay.  We must delay the pilot by the same amount so the derived
        # 57 kHz carrier stays phase-aligned with the filtered RDS signal.
        # Without this compensation, the product demodulator output is
        # attenuated by cos(phase_offset), losing ~4 dB of SNR margin.
        self._pilot_delay = (_BPF_TAPS - 1) // 2
        self._pilot_buf = np.zeros(self._pilot_delay)

        # Lowpass for RDS demodulated baseband.  The RDS bit rate is 1187.5 bps
        # so the theoretical minimum bandwidth is ~600 Hz.  A 1.2 kHz cutoff
        # provides adequate margin while rejecting ~3 dB more noise than a
        # wider filter, which helps on marginal signals.
        from .filters import make_lowpass_iir
        self._rds_lpf = make_lowpass_iir(1_200, baseband_rate, order=4)
        self._rds_lpf_zi = sp_signal.sosfilt_zi(self._rds_lpf) * 0.0

        # Decimation: reduce sample rate to ~12 kHz for cheap per-sample processing.
        # At 240 kHz baseband, decimate by 20 → 12 kHz → ~10 samples per bit.
        _RDS_INTERNAL_RATE = 11875  # 10× the bit rate
        self._decim_factor = max(1, baseband_rate // _RDS_INTERNAL_RATE)
        self._internal_rate = baseband_rate / self._decim_factor

        # --- Bit clock recovery (Gardner TED) ---
        self._bits_per_sample = 1187.5 / self._internal_rate
        self._clock_phase: float = 0.0
        self._clock_freq_offset: float = 0.0  # integral term for PLL
        self._last_decision: float = 0.0  # previous bit decision value
        self._mid_sample: float = 0.0  # mid-bit sample for Gardner TED
        self._bit_accumulator: float = 0.0  # running sum within bit period
        self._bit_acc_count: int = 0  # samples accumulated

        # --- Differential decode state ---
        self._last_bit_sign: int = 0  # sign of previous bit sample (0 or 1)

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
        self._rds_bpf_zi = sp_signal.lfilter_zi(self._rds_bpf, [1.0]) * 0.0
        self._pilot_buf = np.zeros(self._pilot_delay)
        self._rds_lpf_zi = sp_signal.sosfilt_zi(self._rds_lpf) * 0.0
        self._clock_phase = 0.0
        self._clock_freq_offset = 0.0
        self._last_decision = 0.0
        self._mid_sample = 0.0
        self._bit_accumulator = 0.0
        self._bit_acc_count = 0
        self._last_bit_sign = 0

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

        # 1. Bandpass filter MPX to isolate RDS subcarrier (FIR, 501 taps)
        rds_band, self._rds_bpf_zi = sp_signal.lfilter(
            self._rds_bpf, [1.0], mpx, zi=self._rds_bpf_zi,
        )

        # 2. Delay pilot to compensate FIR group delay, then derive carrier
        self._pilot_buf = np.concatenate([self._pilot_buf, pilot])
        if len(self._pilot_buf) < self._pilot_delay + len(mpx):
            self._debug_chunks += 1
            return  # still filling delay buffer at startup
        delayed_pilot = self._pilot_buf[:len(mpx)]
        self._pilot_buf = self._pilot_buf[len(mpx):]

        pilot_peak = np.max(np.abs(delayed_pilot))
        if pilot_peak < 1e-8:
            return  # no pilot → no stereo → probably no RDS
        pilot_norm = delayed_pilot / pilot_peak
        # cos(3θ) = 4cos³(θ) − 3cos(θ) — derives 57 kHz from 19 kHz pilot
        carrier = 4.0 * pilot_norm ** 3 - 3.0 * pilot_norm

        # 3. Coherent product demodulation — real-valued, no quadrature needed.
        # Differential BPSK decode (XOR of consecutive bit signs) cancels
        # any constant carrier phase offset from the pilot BPF group delay.
        demod = rds_band * carrier * 2.0

        # 4. Lowpass at 1.2 kHz (RDS data bandwidth)
        demod_mf, self._rds_lpf_zi = sp_signal.sosfilt(
            self._rds_lpf, demod, zi=self._rds_lpf_zi,
        )

        # 5. Decimate to ~12 kHz to keep the per-sample Python loop cheap
        if self._decim_factor > 1:
            demod_mf = demod_mf[::self._decim_factor]

        # 6. Clock recovery and differential BPSK bit extraction
        self._extract_bits(demod_mf)

        # Debug: log RDS activity every ~5 seconds (~185 chunks at 37/s)
        self._debug_chunks += 1
        if self._debug_chunks % 185 == 0:
            rms = float(np.sqrt(np.mean(np.square(demod_mf))))
            rds_snr = self._measure_rds_snr(mpx)

            # Sign-change rate: clean BPSK ~5%, noise ~50%
            signs = np.sign(demod_mf)
            sign_changes = np.count_nonzero(np.diff(signs))
            sign_change_pct = 100.0 * sign_changes / max(len(signs) - 1, 1)

            # Bimodality: ratio of |samples| > 0.5×rms (BPSK >80%, noise ~39%)
            if rms > 1e-10:
                above_half = np.count_nonzero(np.abs(demod_mf) > 0.5 * rms)
                bimodal_pct = 100.0 * above_half / max(len(demod_mf), 1)
            else:
                bimodal_pct = 0.0

            logger.info(
                "RDS debug: chunks=%d bits=%d synced=%s syncs=%d groups=%d "
                "blk_ok=%d blk_fail=%d rms=%.5f pilot=%.5f "
                "ones=%d zeros=%d rds_snr=%.1fdB "
                "sign_chg=%.1f%% bimodal=%.1f%%",
                self._debug_chunks, self._debug_bits, self._synced,
                self._debug_syncs, self._debug_groups,
                self._debug_block_ok, self._debug_block_fail,
                rms, pilot_peak,
                self._debug_bit_ones, self._debug_bit_zeros,
                rds_snr, sign_change_pct, bimodal_pct,
            )

    def _measure_rds_snr(self, mpx: np.ndarray) -> float:
        """Measure RDS subcarrier SNR using peak-bin detection.

        Uses a Hann-windowed FFT to measure:
        - Pilot: peak bin in 18.5-19.5 kHz
        - RDS carrier: peak bin in 55-59 kHz
        - Noise floor: median of bins in 70-76 kHz
        Peak detection is essential because both pilot and RDS carrier are
        narrow-band signals (tones) that would be diluted by band-average.
        """
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
        """Recover clock and extract bits via differential BPSK.

        Uses Gardner-style timing error detection: the error signal is
        computed from the mid-bit sample and the two adjacent decision
        samples, which is self-normalizing and robust to noise.

        Real-valued demodulation: the carrier phase offset (from pilot
        BPF group delay) produces a constant sign flip that cancels in
        the differential XOR.
        """
        for sample in demod:
            self._clock_phase += self._bits_per_sample

            # Accumulate sample into the bit integrator for mid-bit estimation
            self._bit_accumulator += sample
            self._bit_acc_count += 1

            if self._clock_phase >= 1.0:
                self._clock_phase -= 1.0

                # Use the accumulated average as the decision value
                # (partial integrate-and-dump within Python loop)
                if self._bit_acc_count > 0:
                    decision_value = self._bit_accumulator / self._bit_acc_count
                else:
                    decision_value = sample

                # Gardner timing error detector:
                # e[n] = (y[n] - y[n-1]) × y_mid
                # where y[n] is the current decision, y[n-1] is the previous,
                # and y_mid is the mid-bit sample (accumulated between decisions).
                # This is self-normalizing and data-directed.
                if self._last_decision != 0.0:
                    timing_error = (decision_value - self._last_decision) * self._mid_sample
                    # Loop filter: proportional + integral for stable tracking
                    self._clock_phase -= timing_error * 0.01  # proportional
                    self._clock_freq_offset += timing_error * 0.0001  # integral
                    self._clock_phase -= self._clock_freq_offset

                # Clamp the frequency offset to prevent runaway
                self._clock_freq_offset = max(-0.1, min(0.1, self._clock_freq_offset))

                # Differential BPSK: XOR of consecutive bit signs.
                current_sign = 1 if decision_value >= 0 else 0
                decoded = current_sign ^ self._last_bit_sign
                self._last_bit_sign = current_sign
                self._last_decision = decision_value
                self._debug_bits += 1
                if decoded:
                    self._debug_bit_ones += 1
                else:
                    self._debug_bit_zeros += 1

                self._process_bit(decoded)

                # Reset accumulator; save the mid-point sample as zero
                self._mid_sample = 0.0
                self._bit_accumulator = 0.0
                self._bit_acc_count = 0

            elif self._clock_phase >= 0.5 and self._mid_sample == 0.0:
                # Capture mid-bit sample for Gardner TED
                self._mid_sample = sample

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

        # Single-bit error correction: if the syndrome doesn't match,
        # check whether XOR with the expected offset yields a known
        # single-bit error pattern.  If so, correct the bit and accept.
        if not valid:
            error_syn = syndrome ^ expected
            if error_syn in _SINGLE_BIT_SYNDROMES:
                bit_pos = _SINGLE_BIT_SYNDROMES[error_syn]
                if bit_pos < 16:
                    data_16 ^= 1 << (15 - bit_pos)
                # (check bits don't affect decoded data, no need to fix)
                valid = True
            # Also try C' for block C
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
                # Lost sync — go back to searching.  Threshold raised from 10
                # to 50 to survive marginal signals: at 3% block pass rate the
                # average gap between valid blocks is ~33, so a threshold of 10
                # would lose sync before seeing even one good block.
                self._synced = False
                self._blocks_collected = 0
                return

        # Advance to next block
        self._block_idx = (self._block_idx + 1) % 4

        # If we wrapped around (completed block D → block A), try to decode group.
        # Full decode requires all 4 blocks (0x0F).  Partial decode attempts
        # extraction with whatever blocks passed — this dramatically improves
        # decode success rate on marginal signals where individual block BER
        # is high but the data repeats across many groups.
        if self._block_idx == 0:
            collected = self._blocks_collected
            if collected == 0x0F:
                self._decode_group(collected)
                self._debug_groups += 1
            elif (collected & 0x03) == 0x03:
                # Blocks A+B both valid — partial decode.  Requiring A
                # reduces false positives: random noise matching BOTH A's
                # and B's CRC is p ≈ (5/1024)² ≈ 0.002% vs 0.5% for B alone.
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
