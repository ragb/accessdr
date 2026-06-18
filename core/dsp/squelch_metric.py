"""core/dsp/squelch_metric.py — Hardware-style squelch metrics.

Three strategies:

* **FMNoiseMetric** (carrier squelch) — for WFM/NFM.  Measures noise energy
  *above* the audio band in the FM discriminator output.  When a valid FM
  signal is present the discriminator is quiet above the audio passband;
  when only noise is received the discriminator is wideband white noise.
  Lower ``noise_db`` ⇒ stronger signal.

* **AMCarrierMetric** (carrier-to-noise ratio) — for AM/DSB.  Measures the
  ratio of carrier level to noise on the channel-filtered IQ envelope.
  Hardware airband receivers detect the AM carrier presence this way
  rather than using broadband RSSI.  Higher ``cnr_db`` ⇒ stronger signal.

* **AdaptiveNoiseFloor** — for SSB/CW (no carrier to detect).  Tracks the
  RSSI noise floor with a slow IIR follower and returns an automatic
  squelch threshold (noise floor + configurable headroom).
"""

from __future__ import annotations

import numpy as np
from scipy import signal as sp_signal

from .filters import make_bandpass_iir


# ---------------------------------------------------------------------------
# Sensitivity → margin mapping
# ---------------------------------------------------------------------------

def sensitivity_to_margins(sensitivity: int) -> dict[str, float]:
    """Map a sensitivity level (0–10) to per-strategy margin/headroom values.

    0 = most sensitive (weakest signals open squelch).
    10 = tightest (only strong signals).
    """
    s = max(0, min(10, sensitivity))
    return {
        "fm_margin": 2.0 + s * 1.5,      # 2–17 dB
        "am_margin": 1.0 + s * 0.8,      # 1–9 dB
        "rssi_headroom": 4.0 + s * 2.0,  # 4–24 dB
    }


# ---------------------------------------------------------------------------
# FM carrier squelch
# ---------------------------------------------------------------------------

# Default noise-measurement bands (Hz) per mode — chosen to sit above the
# audio passband but below interfering subcarriers.
_NOISE_BANDS: dict[str, tuple[float, float]] = {
    "NFM": (4_000.0, 6_000.0),   # above 3 kHz voice, below 8 kHz LPF
    "WFM": (16_000.0, 18_500.0), # above 15 kHz audio, below 19 kHz pilot
}


class FMNoiseMetric:
    """Stateful above-audio noise power meter for FM carrier squelch."""

    def __init__(self, baseband_rate: int, mode: str,
                 noise_band: tuple[float, float] | None = None) -> None:
        lo, hi = noise_band if noise_band is not None else _NOISE_BANDS[mode]
        self._sos = make_bandpass_iir(lo, hi, baseband_rate, order=3)
        self._zi = sp_signal.sosfilt_zi(self._sos) * 0.0
        # IIR-smoothed noise power (dB).  Start high so squelch is closed
        # until the first few chunks settle the estimate.
        self._smooth_db: float = 20.0
        # Smoothing alpha — ~70 ms time constant at ~37 chunks/s
        self._alpha: float = 0.15

    def process(self, discriminator: np.ndarray) -> float:
        """Feed discriminator output, return smoothed noise power in dB.

        Lower values ⇒ stronger FM signal (less above-audio noise).
        """
        filtered, self._zi = sp_signal.sosfilt(
            self._sos, discriminator, zi=self._zi,
        )
        rms_power = float(np.mean(np.square(filtered)))
        noise_db = 10.0 * np.log10(max(rms_power, 1e-20))
        self._smooth_db += self._alpha * (noise_db - self._smooth_db)
        return self._smooth_db

    def reset(self) -> None:
        self._zi = sp_signal.sosfilt_zi(self._sos) * 0.0
        # Reset to a high value (noise-like) so the squelch starts closed
        # and must detect a real signal to open.
        self._smooth_db = 20.0


# ---------------------------------------------------------------------------
# AM carrier-to-noise squelch
# ---------------------------------------------------------------------------

class AMCarrierMetric:
    """Carrier-to-noise ratio meter for AM squelch.

    Operates on the channel-filtered IQ envelope (already computed by the
    AM demodulator).  When an AM carrier is present the envelope has a
    large mean (the carrier) with variance from modulation + noise.
    When no carrier is present the envelope is rectified noise with a
    small, noisy mean.

    The metric is ``cnr_db = 10·log10(mean² / var)``.  A strong
    unmodulated carrier gives CNR ≫ 20 dB; noise-only gives CNR ≈ 1–5 dB.
    Modulated voice typically gives 8–15 dB depending on modulation depth.

    Higher cnr_db ⇒ stronger signal (same polarity as RSSI, unlike FM
    noise metric which is inverted).
    """

    def __init__(self) -> None:
        self._smooth_db: float = 0.0
        self._alpha: float = 0.15  # ~70 ms time constant at ~37 chunks/s

    def process(self, envelope: np.ndarray) -> float:
        """Feed the IQ envelope (|IQ|), return smoothed CNR in dB."""
        mean_sq = float(np.mean(envelope)) ** 2
        var = float(np.var(envelope))
        # CNR = carrier power / noise+modulation power
        cnr = mean_sq / max(var, 1e-20)
        cnr_db = 10.0 * np.log10(max(cnr, 1e-10))
        self._smooth_db += self._alpha * (cnr_db - self._smooth_db)
        return self._smooth_db

    def reset(self) -> None:
        self._smooth_db = 0.0


# ---------------------------------------------------------------------------
# Adaptive thresholds
# ---------------------------------------------------------------------------

class FMAutoThreshold:
    """Adaptive threshold for FM carrier squelch.

    Tracks the *noise ceiling* — the noise_db level when no signal is
    present — and sets the squelch threshold below it by ``margin_db``.
    Squelch opens when noise_db drops below the threshold (signal present
    pushes noise down).

    The ceiling eagerly chases *upward* (toward noise-only levels) and
    drifts downward very slowly, so it adapts to environmental changes
    without chasing signals.
    """

    def __init__(self, margin_db: float = 9.5) -> None:
        self._margin = margin_db
        self._ceiling: float | None = None
        self._alpha_up: float = 0.08     # chase upward quickly (noise appeared)
        self._alpha_down: float = 0.0005 # drift downward very slowly

    def set_margin(self, margin_db: float) -> None:
        self._margin = margin_db

    def update(self, noise_db: float) -> float:
        """Feed noise_db, return the auto squelch threshold.

        The threshold sits *below* the noise ceiling.  noise_db < threshold
        means a signal is present (noise dropped).
        """
        if self._ceiling is None:
            self._ceiling = noise_db
        elif noise_db > self._ceiling:
            # Noise level rose — track up quickly
            self._ceiling += self._alpha_up * (noise_db - self._ceiling)
        else:
            # Signal present or environment quieter — drift down slowly
            self._ceiling += self._alpha_down * (noise_db - self._ceiling)
        return self._ceiling - self._margin

    def reset(self) -> None:
        self._ceiling = None


class AMAutoThreshold:
    """Adaptive threshold for AM carrier squelch.

    Tracks the *high* end of the CNR metric (noise-only ceiling) and
    sets the threshold a margin above it.  When no signal is present,
    CNR is low (~1–5 dB); when a signal is present, CNR is high.
    """

    def __init__(self, margin_db: float = 5.0) -> None:
        self._margin = margin_db
        self._ceiling: float | None = None
        self._alpha_fast: float = 0.05
        self._alpha_slow: float = 0.002

    def set_margin(self, margin_db: float) -> None:
        self._margin = margin_db

    def update(self, cnr_db: float) -> float:
        """Feed CNR, return the auto squelch threshold."""
        if self._ceiling is None:
            self._ceiling = cnr_db
        elif cnr_db < self._ceiling + self._margin:
            # Near or below ceiling (noise only) — track quickly
            self._ceiling += self._alpha_fast * (cnr_db - self._ceiling)
        else:
            # Signal present — let ceiling drift up very slowly
            self._ceiling += self._alpha_slow * (cnr_db - self._ceiling)
        return self._ceiling + self._margin

    def reset(self) -> None:
        self._ceiling = None


class AdaptiveNoiseFloor:
    """Tracks the RSSI noise floor and returns an automatic squelch threshold.

    The floor estimate converges quickly when the channel is quiet and
    drifts slowly downward when a signal is present, so the threshold
    adapts to changing environmental conditions without manual adjustment.
    """

    def __init__(self, headroom_db: float = 14.0, guard_db: float = 6.0) -> None:
        self._headroom = headroom_db
        self._guard = guard_db
        self._floor: float | None = None
        # Fast alpha — used when measured RSSI is near the current floor
        self._alpha_fast: float = 0.05
        # Slow alpha — lets the floor drift down when signal is present
        self._alpha_slow: float = 0.001

    def set_headroom(self, headroom_db: float) -> None:
        self._headroom = headroom_db

    def update(self, rssi_db: float) -> float:
        """Feed an RSSI reading, return the auto squelch threshold (dB)."""
        if self._floor is None:
            self._floor = rssi_db
        elif rssi_db < self._floor + self._guard:
            # Near or below current floor — track quickly
            self._floor += self._alpha_fast * (rssi_db - self._floor)
        else:
            # Signal present — let the floor drift down very slowly
            self._floor += self._alpha_slow * (rssi_db - self._floor)
        return self._floor + self._headroom

    def reset(self) -> None:
        self._floor = None
