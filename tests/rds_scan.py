"""Quick FM band scan — measure pilot and RDS SNR at each station.

Scans 87.5–108 MHz in 200 kHz steps, captures ~0.4 seconds at each frequency,
and reports pilot and RDS subcarrier strength relative to noise floor.

Uses the same anti-aliased decimation as the app (StatefulDecimator).

Usage:
    python -m tests.test_rds_scan                   # full band scan
    python -m tests.test_rds_scan --lo 95 --hi 100  # scan 95–100 MHz only
"""

import argparse
import sys
import time
import logging
import numpy as np

sys.path.insert(0, ".")

from rtlsdr.rtlsdr import RtlSdr
from core.dsp.filters import StatefulDecimator

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger(__name__)

SAMPLE_RATE = 2_400_000
DECIM = 10
BASEBAND_RATE = SAMPLE_RATE // DECIM
CHUNK_SIZE = 65536
CAPTURE_CHUNKS = 15  # ~0.4 seconds per frequency
MAX_DEVIATION = 75_000.0


def fm_discriminant(iq):
    product = iq[1:] * np.conj(iq[:-1])
    out = np.empty(len(iq), dtype=np.float64)
    out[0] = 0.0
    out[1:] = np.angle(product)
    return out


def measure_snr(mpx, rate):
    """Measure pilot and RDS SNR from MPX spectrum."""
    N = len(mpx)
    if N < 2048:
        return 0, 0, 0
    window = np.hanning(N)
    spectrum = np.abs(np.fft.rfft(mpx * window)) ** 2
    freq_res = rate / N

    def _bin(hz):
        return min(len(spectrum) - 1, max(0, int(round(hz / freq_res))))

    def _peak(lo, hi):
        a, b = _bin(lo), _bin(hi)
        return float(np.max(spectrum[a:b])) if b > a else 1e-30

    def _median(lo, hi):
        a, b = _bin(lo), _bin(hi)
        return float(np.median(spectrum[a:b])) if b > a else 1e-30

    pilot = _peak(18_500, 19_500)
    rds = _peak(55_000, 59_000)
    noise = _median(70_000, 76_000)
    rms = float(np.sqrt(np.mean(np.square(mpx))))

    if noise > 1e-30:
        return 10 * np.log10(pilot / noise), 10 * np.log10(rds / noise), rms
    return 0, 0, rms


def main():
    parser = argparse.ArgumentParser(description="FM band scan for RDS signal strength")
    parser.add_argument("--lo", type=float, default=87.5,
                        help="Start frequency in MHz (default: 87.5)")
    parser.add_argument("--hi", type=float, default=108.0,
                        help="End frequency in MHz (default: 108.0)")
    parser.add_argument("--step", type=float, default=0.2,
                        help="Step size in MHz (default: 0.2)")
    parser.add_argument("--threshold", type=float, default=15.0,
                        help="Minimum pilot SNR in dB to report (default: 15)")
    args = parser.parse_args()

    sdr = RtlSdr()
    sdr.sample_rate = SAMPLE_RATE
    sdr.gain = "auto"

    disc_gain = float(BASEBAND_RATE / (2.0 * np.pi * MAX_DEVIATION))

    results = []
    lo_hz = int(args.lo * 1_000_000)
    hi_hz = int(args.hi * 1_000_000)
    step_hz = int(args.step * 1_000_000)
    freqs = range(lo_hz, hi_hz + step_hz, step_hz)
    logger.info("Scanning %d frequencies (%.1f–%.1f MHz)...", len(freqs), args.lo, args.hi)

    for freq in freqs:
        sdr.center_freq = int(freq)
        time.sleep(0.05)  # settling

        # Fresh decimator per frequency to avoid filter transients
        decimator = StatefulDecimator(factor=DECIM, input_rate=SAMPLE_RATE)

        mpx_all = []
        for _ in range(CAPTURE_CHUNKS):
            iq_raw = sdr.read_samples(CHUNK_SIZE)
            iq = decimator.process(iq_raw)
            # Limiter
            mag = np.abs(iq)
            rms_iq = float(np.sqrt(np.mean(np.square(mag))))
            if rms_iq > 0.03:
                iq = iq / np.maximum(mag, np.float32(1e-10))
            mpx = fm_discriminant(iq) * disc_gain
            mpx_all.append(mpx)

        mpx_cat = np.concatenate(mpx_all)
        pilot_snr, rds_snr, rms = measure_snr(mpx_cat, BASEBAND_RATE)

        if pilot_snr > args.threshold:
            mhz = freq / 1e6
            results.append((mhz, pilot_snr, rds_snr, rms))
            logger.info(
                "%.1f MHz: Pilot %.1fdB  RDS %.1fdB  RMS %.3f",
                mhz, pilot_snr, rds_snr, rms,
            )

    sdr.close()

    # Summary sorted by RDS SNR
    logger.info("\n" + "=" * 60)
    logger.info("TOP STATIONS (sorted by RDS SNR):")
    for mhz, pilot, rds, rms in sorted(results, key=lambda x: -x[2]):
        logger.info(
            "  %6.1f MHz: Pilot %5.1fdB  RDS %5.1fdB  RMS %.3f",
            mhz, pilot, rds, rms,
        )
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
