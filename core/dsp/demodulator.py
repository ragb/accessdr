"""
core/dsp/demodulator.py — Stateful demodulators for common radio modes.

Each mode is encapsulated in a Demodulator subclass that:
  - pre-computes all filter coefficients once at construction
  - carries filter state (zi) between calls so there are no transient
    discontinuities at chunk boundaries (the main cause of crackle)

All bandpass / lowpass filters use IIR Butterworth in SOS form
(``scipy.signal.sosfilt``).  Compared to the previous FIR ``lfilter``
approach this is ~10–50× cheaper per sample:

  - 1023-tap FIR pilot BPF  → 4th-order IIR (4 biquads, 20 MACs/sample)
  - 511-tap  FIR L−R BPF    → 4th-order IIR (4 biquads, 20 MACs/sample)
  - 127-tap  FIR lowpass     → 4th-order IIR (2 biquads, 10 MACs/sample)

Public API
----------
    dem = make_demodulator("WFM", baseband_rate=240_000, audio_rate=48_000)
    audio_f32 = dem.process(iq_complex64)  # called repeatedly per chunk
"""

from __future__ import annotations

import logging
import numpy as np
from abc import ABC, abstractmethod
from scipy import signal as sp_signal

from .filters import make_lowpass_iir, make_bandpass_iir, deemphasis_filter

logger = logging.getLogger(__name__)

AUDIO_RATE = 48_000


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------

class Demodulator(ABC):
    """Abstract base — subclasses implement process().

    Subclasses set ``_CHANNEL_BW`` (Hz, one-sided) to enable a
    pre-demodulation lowpass that isolates the desired signal after the
    mixer shifts it to DC.
    """

    _CHANNEL_BW: float = 0  # 0 = no channel filter (subclass overrides)

    def __init__(self, baseband_rate: int, audio_rate: int) -> None:
        self.baseband_rate = baseband_rate
        self.audio_rate = audio_rate
        self._resample_up, self._resample_down = _resample_ratio(baseband_rate, audio_rate)

        # Pre-demodulation channel filter (IIR Butterworth lowpass, SOS)
        bw = self._CHANNEL_BW
        if bw > 0 and bw < baseband_rate / 2:
            self._ch_sos = make_lowpass_iir(bw, baseband_rate, order=5)
            self._ch_zi_i = sp_signal.sosfilt_zi(self._ch_sos) * 0.0
            self._ch_zi_q = sp_signal.sosfilt_zi(self._ch_sos) * 0.0
            self._has_ch_filter = True
        else:
            self._has_ch_filter = False

    def _channel_filter(self, iq: np.ndarray) -> np.ndarray:
        """Apply pre-demodulation channel filter (IIR lowpass on I and Q)."""
        if not self._has_ch_filter:
            return iq
        i_f, self._ch_zi_i = sp_signal.sosfilt(
            self._ch_sos, iq.real, zi=self._ch_zi_i)
        q_f, self._ch_zi_q = sp_signal.sosfilt(
            self._ch_sos, iq.imag, zi=self._ch_zi_q)
        return (i_f + 1j * q_f).astype(np.complex64)

    @abstractmethod
    def process(self, iq: np.ndarray) -> np.ndarray:
        """Demodulate *iq* (complex64) → float32 audio at audio_rate."""

    def _resample(self, audio: np.ndarray) -> np.ndarray:
        """Resample from baseband_rate to audio_rate (polyphase, integer ratio)."""
        if self._resample_up == self._resample_down:
            return audio.astype(np.float32)
        return sp_signal.resample_poly(audio, self._resample_up, self._resample_down).astype(np.float32)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resample_ratio(in_rate: int, out_rate: int):
    from math import gcd
    g = gcd(in_rate, out_rate)
    return out_rate // g, in_rate // g


def _fm_discriminant(iq: np.ndarray) -> np.ndarray:
    """Instantaneous frequency via conjugate-product polar discriminant."""
    product = iq[1:] * np.conj(iq[:-1])
    out = np.empty(len(iq), dtype=np.float64)
    out[0] = 0.0
    out[1:] = np.angle(product)
    return out


# ---------------------------------------------------------------------------
# WFM
# ---------------------------------------------------------------------------

def _detect_deemphasis_tau() -> float:
    """Return the correct de-emphasis time constant for the user's region.

    50 µs — Europe, UK, Australia, most of the world.
    75 µs — Americas, Japan, South Korea.
    """
    import locale
    try:
        loc = locale.getdefaultlocale()[0] or ""
    except Exception:  # noqa: BLE001
        loc = ""
    loc = loc.lower().replace("-", "_")
    # 75 µs regions (prefix match)
    if any(loc.startswith(p) for p in (
        "en_us", "en_ca", "fr_ca", "es_mx", "es_ar", "es_cl", "es_co",
        "es_ve", "es_pe", "es_ec", "pt_br", "ja", "ko",
    )):
        return 75e-6
    return 50e-6


class WFMDemodulator(Demodulator):
    """Wide-band FM demodulator with automatic MPX stereo decoding.

    Stereo decoding is active whenever a 19 kHz pilot tone is detected with
    sufficient SNR above the surrounding noise floor (FFT-based detection).
    When stereo, process() returns a (N, 2) float32 array with left in column 0
    and right in column 1.  When mono, it returns (N,).

    Includes stereo blend: smoothly reduces stereo separation when the pilot
    SNR is marginal, avoiding the ~20 dB noise penalty of full stereo on weak
    signals.

    MPX signal structure (IEC 60268-3 / NRSC-4):
      0–15 kHz   — L+R (mono sum)
      19 kHz     — stereo pilot (always present on stereo stations)
      23–53 kHz  — (L-R) DSB-SC centred at 38 kHz
    """

    _CHANNEL_BW = 100_000  # ±75 kHz deviation + stereo subcarrier + guard
    _MAX_DEVIATION = 75_000.0  # Hz, standard FM broadcast

    _PILOT_SNR_THRESHOLD = 4.0
    _PILOT_ON  = 8
    _PILOT_OFF = 8
    _PILOT_CHECK_INTERVAL = 4  # only run FFT-based detection every Nth chunk

    # Stereo blend: smoothly transition between mono and full stereo based on
    # pilot SNR.  Below _BLEND_SNR_LOW → mono, above _BLEND_SNR_HIGH → stereo.
    _BLEND_SNR_LOW  = 6.0
    _BLEND_SNR_HIGH = 20.0

    def __init__(self, baseband_rate: int, audio_rate: int) -> None:
        super().__init__(baseband_rate, audio_rate)
        rate = baseband_rate

        # FM discriminator normalization: convert rad/sample → ±1.0 at full deviation
        self._disc_gain = float(rate / (2.0 * np.pi * self._MAX_DEVIATION))

        # De-emphasis — auto-detect region (50 µs Europe, 75 µs Americas)
        tau = _detect_deemphasis_tau()
        logger.info("WFM de-emphasis: %.0f µs", tau * 1e6)
        self._deemph_b, self._deemph_a = deemphasis_filter(rate, tau=tau)

        # L+R extraction: IIR lowpass 0–15 kHz
        self._lpr_sos = make_lowpass_iir(15_000, rate, order=4)

        # 19 kHz pilot BPF — IIR bandpass (4th order per edge = 8 poles total)
        self._pilot_sos = make_bandpass_iir(18_000, 20_000, rate, order=4)

        # L-R DSB-SC subcarrier BPF (23–53 kHz)
        self._lmr_sos = make_bandpass_iir(23_000, 53_000, rate, order=4)

        # Post-demodulation LPF: removes 76 kHz image after product detection
        self._lmr_lp_sos = make_lowpass_iir(15_000, rate, order=4)

        # Final audio LPF at 15 kHz (after resampling to audio_rate)
        self._audio_lp_sos = make_lowpass_iir(15_000, audio_rate, order=4)

        # Filter states — zero-initialised, carried between chunks
        self._zi_lpr      = sp_signal.sosfilt_zi(self._lpr_sos)      * 0.0
        self._zi_pilot    = sp_signal.sosfilt_zi(self._pilot_sos)    * 0.0
        self._zi_lmr      = sp_signal.sosfilt_zi(self._lmr_sos)      * 0.0
        self._zi_lmr_lp   = sp_signal.sosfilt_zi(self._lmr_lp_sos)  * 0.0
        self._zi_deemph_l = sp_signal.lfilter_zi(self._deemph_b, self._deemph_a) * 0.0
        self._zi_deemph_r = sp_signal.lfilter_zi(self._deemph_b, self._deemph_a) * 0.0
        self._zi_audio_l  = sp_signal.sosfilt_zi(self._audio_lp_sos) * 0.0
        self._zi_audio_r  = sp_signal.sosfilt_zi(self._audio_lp_sos) * 0.0

        # Hi-blend: adaptive treble cut driven by pilot SNR.
        # Pre-compute a lowpass at 5 kHz — when blended in, removes FM hiss.
        self._hicut_sos = make_lowpass_iir(5_000, audio_rate, order=3)
        self._hicut_zi_l = sp_signal.sosfilt_zi(self._hicut_sos) * 0.0
        self._hicut_zi_r = sp_signal.sosfilt_zi(self._hicut_sos) * 0.0

        self.stereo_detected: bool = False
        self._pilot_count: int = 0
        self._pilot_check_ctr: int = 0
        self._stereo_blend: float = 0.0   # 0 = mono, 1 = full stereo
        self._last_pilot_snr: float = 0.0
        self._hiblend: float = 0.0        # 0 = full BW, 1 = hi-cut active

    def process(self, iq: np.ndarray) -> np.ndarray:
        iq = self._channel_filter(iq)

        # Signal-gated limiter: normalize to unit magnitude when a signal
        # is present.  FM carries info in phase only so limiting removes
        # AM noise (AGC, quantization, multipath).  When no signal is
        # present, skip limiting to avoid amplifying random noise.
        mag = np.abs(iq)
        if float(np.sqrt(np.mean(np.square(mag)))) > 0.03:
            iq = iq / np.maximum(mag, np.float32(1e-10))

        # FM discriminant → normalized MPX baseband (±1.0 at full deviation)
        mpx = _fm_discriminant(iq) * self._disc_gain

        # Extract L+R (mono sum, 0–15 kHz)
        lpr, self._zi_lpr = sp_signal.sosfilt(
            self._lpr_sos, mpx, zi=self._zi_lpr)

        # Extract 19 kHz pilot
        pilot, self._zi_pilot = sp_signal.sosfilt(
            self._pilot_sos, mpx, zi=self._zi_pilot)

        # Stereo detection — throttled to every Nth chunk to save CPU.
        self._pilot_check_ctr += 1
        if self._pilot_check_ctr >= self._PILOT_CHECK_INTERVAL:
            self._pilot_check_ctr = 0
            snr = self._measure_pilot_snr(mpx)
            self._last_pilot_snr = snr
            detected = snr > self._PILOT_SNR_THRESHOLD
            if detected:
                self._pilot_count = min(self._pilot_count + 1, self._PILOT_ON)
                if self._pilot_count >= self._PILOT_ON:
                    self.stereo_detected = True
            else:
                self._pilot_count = max(self._pilot_count - 1, 0)
                if self._pilot_count <= 0:
                    self.stereo_detected = False

            # Update stereo blend from SNR (smooth transition)
            if self.stereo_detected:
                target = np.clip(
                    (snr - self._BLEND_SNR_LOW)
                    / (self._BLEND_SNR_HIGH - self._BLEND_SNR_LOW),
                    0.0, 1.0,
                )
            else:
                target = 0.0
            # Exponential smoothing (~200 ms time constant)
            alpha = 0.15
            self._stereo_blend += alpha * (target - self._stereo_blend)

            # Hi-blend: cut treble when pilot SNR is low (noisy signal).
            # SNR > 30 → full BW, SNR < 10 → hi-cut at 5 kHz.
            hb_target = float(np.clip(1.0 - (snr - 10.0) / 20.0, 0.0, 1.0))
            self._hiblend += alpha * (hb_target - self._hiblend)

        if self.stereo_detected or self._stereo_blend > 0.01:
            return self._process_stereo(mpx, lpr, pilot)
        else:
            return self._process_mono(lpr)

    # ------------------------------------------------------------------

    def _measure_pilot_snr(self, mpx: np.ndarray) -> float:
        """Measure the 19 kHz pilot SNR (ratio, not dB).  Returns 0 on failure."""
        N = len(mpx)
        if N < 256:
            return 0.0
        window = np.hanning(N)
        spectrum = np.abs(np.fft.rfft(mpx * window)) ** 2
        freq_res = self.baseband_rate / N

        pilot_idx = int(round(19_000.0 / freq_res))
        if pilot_idx >= len(spectrum):
            return 0.0

        pilot_power = float(spectrum[pilot_idx])

        lo1 = int(round(15_000.0 / freq_res))
        hi1 = int(round(18_000.0 / freq_res))
        lo2 = int(round(20_000.0 / freq_res))
        hi2 = int(round(25_000.0 / freq_res))
        noise_bins = np.concatenate([spectrum[lo1:hi1], spectrum[lo2:hi2]])
        if len(noise_bins) == 0:
            return 0.0
        noise_floor = float(np.median(noise_bins))
        if noise_floor < 1e-30:
            return 0.0

        return pilot_power / noise_floor

    # ------------------------------------------------------------------

    def _process_stereo(
        self, mpx: np.ndarray, lpr: np.ndarray, pilot: np.ndarray
    ) -> np.ndarray:
        # Generate 38 kHz coherent reference by frequency-doubling the pilot.
        # cos(2x) = 2·cos²(x) − 1  — no FFT-based hilbert() needed.
        pilot_peak = np.max(np.abs(pilot))
        if pilot_peak > 1e-10:
            pilot_norm = pilot / pilot_peak
        else:
            pilot_norm = pilot
        ref = 2.0 * pilot_norm * pilot_norm - 1.0

        # Extract L-R DSB-SC subcarrier (23–53 kHz)
        lmr_band, self._zi_lmr = sp_signal.sosfilt(
            self._lmr_sos, mpx, zi=self._zi_lmr)

        # Product demodulation → baseband L-R + 76 kHz image
        lmr_product = lmr_band * ref * 2.0

        # LPF to remove the 76 kHz image
        lmr, self._zi_lmr_lp = sp_signal.sosfilt(
            self._lmr_lp_sos, lmr_product, zi=self._zi_lmr_lp)

        # Stereo blend: scale L-R by blend factor (0 = mono, 1 = full stereo).
        # Reduces the ~20 dB noise penalty of stereo on weak signals.
        blend = self._stereo_blend
        left  = lpr + blend * lmr
        right = lpr - blend * lmr

        # De-emphasis on each channel independently
        left,  self._zi_deemph_l = sp_signal.lfilter(
            self._deemph_b, self._deemph_a, left,  zi=self._zi_deemph_l)
        right, self._zi_deemph_r = sp_signal.lfilter(
            self._deemph_b, self._deemph_a, right, zi=self._zi_deemph_r)

        left_out  = self._resample(left)
        right_out = self._resample(right)

        # Final audio LPF: remove discriminator noise above 15 kHz
        left_out,  self._zi_audio_l = sp_signal.sosfilt(
            self._audio_lp_sos, left_out, zi=self._zi_audio_l)
        right_out, self._zi_audio_r = sp_signal.sosfilt(
            self._audio_lp_sos, right_out, zi=self._zi_audio_r)

        # Hi-blend: crossfade with hi-cut version to reduce HF noise
        if self._hiblend > 0.01:
            left_hc, self._hicut_zi_l = sp_signal.sosfilt(
                self._hicut_sos, left_out, zi=self._hicut_zi_l)
            right_hc, self._hicut_zi_r = sp_signal.sosfilt(
                self._hicut_sos, right_out, zi=self._hicut_zi_r)
            b = np.float32(self._hiblend)
            left_out  = left_out  * (1.0 - b) + left_hc  * b
            right_out = right_out * (1.0 - b) + right_hc * b

        return np.stack([left_out, right_out], axis=1).astype(np.float32)

    def _process_mono(self, lpr: np.ndarray) -> np.ndarray:
        audio, self._zi_deemph_l = sp_signal.lfilter(
            self._deemph_b, self._deemph_a, lpr, zi=self._zi_deemph_l)
        audio = self._resample(audio)
        audio, self._zi_audio_l = sp_signal.sosfilt(
            self._audio_lp_sos, audio, zi=self._zi_audio_l)

        # Hi-blend: crossfade with hi-cut version to reduce HF noise
        if self._hiblend > 0.01:
            hicut, self._hicut_zi_l = sp_signal.sosfilt(
                self._hicut_sos, audio, zi=self._hicut_zi_l)
            b = np.float32(self._hiblend)
            audio = audio * (1.0 - b) + hicut * b

        return audio.astype(np.float32)


# ---------------------------------------------------------------------------
# NFM
# ---------------------------------------------------------------------------

class NFMDemodulator(Demodulator):
    _CHANNEL_BW = 12_500  # standard 25 kHz NFM channel
    _MAX_DEVIATION = 5_000.0  # ±5 kHz standard NFM (PMR446 uses ±2.5 kHz)

    def __init__(self, baseband_rate: int, audio_rate: int) -> None:
        super().__init__(baseband_rate, audio_rate)
        # Discriminator normalization: convert rad/sample → ±1.0 at full deviation
        self._disc_gain = float(baseband_rate / (2.0 * np.pi * self._MAX_DEVIATION))
        self._lp_sos = make_lowpass_iir(8_000, baseband_rate, order=4)
        self._zi_lp = sp_signal.sosfilt_zi(self._lp_sos) * 0.0

    def process(self, iq: np.ndarray) -> np.ndarray:
        iq = self._channel_filter(iq)
        # Signal-gated limiter: only limit when real signal is present
        mag = np.abs(iq)
        if float(np.sqrt(np.mean(np.square(mag)))) > 0.03:
            iq = iq / np.maximum(mag, np.float32(1e-10))
        disc = _fm_discriminant(iq) * self._disc_gain
        audio, self._zi_lp = sp_signal.sosfilt(
            self._lp_sos, disc, zi=self._zi_lp)
        return self._resample(audio)


# ---------------------------------------------------------------------------
# AM
# ---------------------------------------------------------------------------

class AMDemodulator(Demodulator):
    _CHANNEL_BW = 5_000  # 10 kHz AM channel

    def __init__(self, baseband_rate: int, audio_rate: int) -> None:
        super().__init__(baseband_rate, audio_rate)
        self._lp_sos = make_lowpass_iir(5_000, baseband_rate, order=4)
        self._zi_lp = sp_signal.sosfilt_zi(self._lp_sos) * 0.0
        # DC block (1st-order IIR — trivial cost, keep as b/a)
        self._dc_b = np.array([1.0, -1.0])
        self._dc_a = np.array([1.0, -0.9995])
        self._zi_dc = sp_signal.lfilter_zi(self._dc_b, self._dc_a) * 0.0

    def process(self, iq: np.ndarray) -> np.ndarray:
        iq = self._channel_filter(iq)
        envelope = np.abs(iq).astype(np.float64)
        audio, self._zi_dc = sp_signal.lfilter(
            self._dc_b, self._dc_a, envelope, zi=self._zi_dc)
        audio, self._zi_lp = sp_signal.sosfilt(
            self._lp_sos, audio, zi=self._zi_lp)
        return self._resample(audio)


# ---------------------------------------------------------------------------
# USB / LSB
# ---------------------------------------------------------------------------

class SSBDemodulator(Demodulator):
    _CHANNEL_BW = 3_000  # 3 kHz SSB channel

    def __init__(self, baseband_rate: int, audio_rate: int, upper: bool) -> None:
        super().__init__(baseband_rate, audio_rate)
        self._upper = upper

    def process(self, iq: np.ndarray) -> np.ndarray:
        iq = self._channel_filter(iq)
        i = iq.real.astype(np.float64)
        q_h = sp_signal.hilbert(i).imag
        audio = (i - q_h) if self._upper else (i + q_h)
        return self._resample(audio)


# ---------------------------------------------------------------------------
# CW
# ---------------------------------------------------------------------------

class CWDemodulator(Demodulator):
    _CHANNEL_BW = 1_500  # must pass 600–1000 Hz beat note + margin

    def __init__(self, baseband_rate: int, audio_rate: int) -> None:
        super().__init__(baseband_rate, audio_rate)
        self._bp_sos = make_bandpass_iir(600, 1_000, baseband_rate, order=4)
        self._zi_bp = sp_signal.sosfilt_zi(self._bp_sos) * 0.0
        self._phase = 0.0

    def process(self, iq: np.ndarray) -> np.ndarray:
        iq = self._channel_filter(iq)
        real = iq.real.astype(np.float64)
        filtered, self._zi_bp = sp_signal.sosfilt(
            self._bp_sos, real, zi=self._zi_bp)
        envelope = np.abs(sp_signal.hilbert(filtered))
        t = np.arange(len(envelope)) / self.baseband_rate
        # Stateful phase to avoid discontinuity between chunks
        phase_vec = 2.0 * np.pi * 700.0 * t + self._phase
        self._phase = float(phase_vec[-1]) % (2.0 * np.pi)
        tone = envelope * np.sin(phase_vec)
        return self._resample(tone)


# ---------------------------------------------------------------------------
# DSB
# ---------------------------------------------------------------------------

class DSBDemodulator(Demodulator):
    _CHANNEL_BW = 5_000  # 10 kHz DSB channel

    def __init__(self, baseband_rate: int, audio_rate: int) -> None:
        super().__init__(baseband_rate, audio_rate)
        self._lp_sos = make_lowpass_iir(5_000, baseband_rate, order=4)
        self._zi_lp = sp_signal.sosfilt_zi(self._lp_sos) * 0.0

    def process(self, iq: np.ndarray) -> np.ndarray:
        iq = self._channel_filter(iq)
        audio = iq.real.astype(np.float64)
        audio, self._zi_lp = sp_signal.sosfilt(
            self._lp_sos, audio, zi=self._zi_lp)
        return self._resample(audio)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

_MODE_MAP = {
    "WFM": WFMDemodulator,
    "NFM": NFMDemodulator,
    "AM":  AMDemodulator,
    "USB": lambda br, ar: SSBDemodulator(br, ar, upper=True),
    "LSB": lambda br, ar: SSBDemodulator(br, ar, upper=False),
    "CW":  CWDemodulator,
    "DSB": DSBDemodulator,
}


def make_demodulator(mode: str, baseband_rate: int, audio_rate: int = AUDIO_RATE) -> Demodulator:
    """Return a fresh stateful Demodulator for *mode*."""
    cls = _MODE_MAP.get(mode.upper())
    if cls is None:
        raise ValueError(f"Unknown mode: {mode!r}")
    return cls(baseband_rate, audio_rate)


# ---------------------------------------------------------------------------
# Thin compatibility shim (used by old call sites if any)
# ---------------------------------------------------------------------------

def demodulate(
    iq: np.ndarray,
    mode: str,
    baseband_rate: int,
    audio_rate: int = AUDIO_RATE,
) -> np.ndarray:
    """Stateless convenience wrapper — creates a fresh demodulator each call."""
    dem = make_demodulator(mode, baseband_rate, audio_rate)
    return dem.process(iq)
