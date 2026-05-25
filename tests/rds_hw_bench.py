"""Hardware RDS test — captures from RTL-SDR and runs RDS decoder.

Replicates the exact WFM demodulator pipeline from the app:
  IQ @ 2.4 MSPS → StatefulDecimator (AA filter + ×10 downsample) → 240 kHz
  → channel filter → limiter → FM discriminant → MPX
  MPX → pilot BPF → RDS decoder

Usage:
    python -m tests.test_rds_hw                     # default 105.7 MHz, 120s
    python -m tests.test_rds_hw --freq 98.3          # specify frequency in MHz
    python -m tests.test_rds_hw --freq 97.4 --time 60  # 60 seconds
"""

import argparse
import ctypes
import sys
import time
import logging
import numpy as np
from scipy import signal as sp_signal

sys.path.insert(0, ".")

from rtlsdr.rtlsdr import RtlSdr
from core.dsp.rds import RDSDecoder
from core.dsp.filters import StatefulDecimator, make_lowpass_iir, make_bandpass_iir

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

# ---------- parameters ----------
SAMPLE_RATE = 2_400_000
DECIM_IQ = 10               # → 240 kHz baseband
BASEBAND_RATE = SAMPLE_RATE // DECIM_IQ  # 240 000
CHUNK_SIZE = 65536           # samples per sync read
MAX_DEVIATION = 75_000.0


def fm_discriminant(iq: np.ndarray) -> np.ndarray:
    """Instantaneous frequency via conjugate-product polar discriminant."""
    product = iq[1:] * np.conj(iq[:-1])
    out = np.empty(len(iq), dtype=np.float64)
    out[0] = 0.0
    out[1:] = np.angle(product)
    return out


def run_test(freq_hz: int, capture_seconds: int, offset_tuning: bool = False) -> None:
    freq_mhz = freq_hz / 1e6

    # --- DSP setup (matches core/dsp/demodulator.py WFM pipeline) ---

    # Anti-aliased decimator: 8th-order Butterworth @ 108 kHz, then ×10 downsample
    decimator = StatefulDecimator(factor=DECIM_IQ, input_rate=SAMPLE_RATE)

    # Channel filter: 5th-order Butterworth lowpass at 100 kHz (I and Q)
    ch_sos = make_lowpass_iir(100_000, BASEBAND_RATE, order=5)
    ch_zi_i = sp_signal.sosfilt_zi(ch_sos) * 0.0
    ch_zi_q = sp_signal.sosfilt_zi(ch_sos) * 0.0

    # FM discriminator gain: rad/sample → ±1.0 at full deviation
    disc_gain = float(BASEBAND_RATE / (2.0 * np.pi * MAX_DEVIATION))

    # Pilot BPF: IIR bandpass 18–20 kHz, order 4
    pilot_sos = make_bandpass_iir(18_000, 20_000, BASEBAND_RATE, order=4)
    zi_pilot = sp_signal.sosfilt_zi(pilot_sos) * 0.0

    # RDS decoder
    rds = RDSDecoder(BASEBAND_RATE)

    def process_chunk(iq_raw: np.ndarray) -> None:
        nonlocal ch_zi_i, ch_zi_q, zi_pilot

        # 1. Anti-aliased decimation (matches StatefulDecimator in pipeline.py)
        iq = decimator.process(iq_raw)

        # 2. Channel filter (I and Q separately)
        i_f, ch_zi_i = sp_signal.sosfilt(ch_sos, iq.real, zi=ch_zi_i)
        q_f, ch_zi_q = sp_signal.sosfilt(ch_sos, iq.imag, zi=ch_zi_q)
        iq = (i_f + 1j * q_f).astype(np.complex64)

        # 3. Limiter: normalize magnitude when signal present
        mag = np.abs(iq)
        if float(np.sqrt(np.mean(np.square(mag)))) > 0.03:
            iq = iq / np.maximum(mag, np.float32(1e-10))

        # 4. FM discriminant → normalized MPX
        mpx = fm_discriminant(iq) * disc_gain

        # 5. Pilot extraction
        pilot, zi_pilot = sp_signal.sosfilt(pilot_sos, mpx, zi=zi_pilot)

        # 6. Feed RDS
        rds.process(mpx, pilot)

    # --- Capture ---
    logger.info("Opening RTL-SDR at %.1f MHz for %d seconds...", freq_mhz, capture_seconds)

    sdr = RtlSdr()
    sdr.sample_rate = SAMPLE_RATE
    sdr.center_freq = freq_hz
    sdr.gain = "auto"

    # Enable bias tee to power external amplifier via SMA connector
    try:
        from rtlsdr.librtlsdr import librtlsdr as _lib
        if not hasattr(_lib.rtlsdr_set_bias_tee, "argtypes"):
            _lib.rtlsdr_set_bias_tee.argtypes = [ctypes.c_void_p, ctypes.c_int]
            _lib.rtlsdr_set_bias_tee.restype = ctypes.c_int
        _lib.rtlsdr_set_bias_tee(sdr.dev_p, 1)
        logger.info("Bias tee ENABLED")
    except Exception as exc:
        logger.warning("Could not enable bias tee: %s", exc)

    # Enable offset tuning to avoid DC spike at center frequency
    if offset_tuning:
        try:
            if not hasattr(_lib.rtlsdr_set_offset_tuning, "argtypes"):
                _lib.rtlsdr_set_offset_tuning.argtypes = [ctypes.c_void_p, ctypes.c_int]
                _lib.rtlsdr_set_offset_tuning.restype = ctypes.c_int
            _lib.rtlsdr_set_offset_tuning(sdr.dev_p, 1)
            logger.info("Offset tuning ENABLED")
        except Exception as exc:
            logger.warning("Could not enable offset tuning: %s", exc)

    chunks = 0
    t0 = time.time()

    try:
        while time.time() - t0 < capture_seconds:
            iq_raw = sdr.read_samples(CHUNK_SIZE)
            process_chunk(iq_raw)
            chunks += 1

            if chunks % 100 == 0:
                elapsed = time.time() - t0
                logger.info(
                    "[%.0fs] chunks=%d  syncs=%d  groups=%d  "
                    "blk_ok=%d  blk_fail=%d  ones=%d  zeros=%d  "
                    "PS=%r  PTY=%r  RT=%r",
                    elapsed, chunks,
                    rds._debug_syncs, rds._debug_groups,
                    rds._debug_block_ok, rds._debug_block_fail,
                    rds._debug_bit_ones, rds._debug_bit_zeros,
                    rds.station_name, rds.program_type, rds.radio_text,
                )
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    finally:
        sdr.close()

    elapsed = time.time() - t0
    logger.info("=" * 60)
    logger.info("RESULTS after %.1f seconds, %d chunks:", elapsed, chunks)
    logger.info("  Frequency:  %.1f MHz", freq_mhz)
    logger.info("  Syncs:      %d", rds._debug_syncs)
    logger.info("  Groups:     %d (full 4-block)", rds._debug_groups)
    logger.info("  Blocks OK:  %d", rds._debug_block_ok)
    logger.info("  Blocks fail:%d", rds._debug_block_fail)
    logger.info("  Bits total: %d", rds._debug_bits)
    logger.info("  Ones/Zeros: %d / %d", rds._debug_bit_ones, rds._debug_bit_zeros)
    total_bits = rds._debug_bit_ones + rds._debug_bit_zeros
    if total_bits > 0:
        logger.info("  Ones ratio: %.1f%%", 100.0 * rds._debug_bit_ones / total_bits)
    total_blocks = rds._debug_block_ok + rds._debug_block_fail
    if total_blocks > 0:
        logger.info("  Block pass: %.1f%%", 100.0 * rds._debug_block_ok / total_blocks)
    logger.info("  Station:    %r", rds.station_name)
    logger.info("  PTY:        %r", rds.program_type)
    logger.info("  Radio Text: %r", rds.radio_text)
    logger.info("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="Hardware RDS decoder test")
    parser.add_argument("--freq", type=float, default=105.7,
                        help="FM frequency in MHz (default: 105.7)")
    parser.add_argument("--time", type=int, default=120,
                        help="Capture duration in seconds (default: 120)")
    parser.add_argument("--offset-tuning", action="store_true",
                        help="Enable RTL-SDR offset tuning (avoids DC spike)")
    args = parser.parse_args()

    freq_hz = int(args.freq * 1_000_000)
    run_test(freq_hz, args.time, offset_tuning=args.offset_tuning)


if __name__ == "__main__":
    main()
