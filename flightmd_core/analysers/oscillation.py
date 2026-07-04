"""
OscillationAnalyser — FFT-based roll/pitch/yaw oscillation detector.

Uses scipy.fft to detect sustained oscillations in angular velocity data.
A dominant peak in 1–30 Hz range with high normalised amplitude indicates
PID tuning issues (usually D term too low or P too high).
"""

import numpy as np
from scipy import fft, signal
import pandas as pd
from typing import Optional

from flightmd_core.analysers.base import BaseAnalyser
from flightmd_core.models.findings import (
    AnalyserResult, Finding, Severity, Category, ParamRecommendation
)


# Penalty applied to module health score per finding severity
PENALTIES = {
    "SEVERE":    30,
    "MODERATE":  15,
    "MILD":       5,
}

# Oscillation thresholds (prominence ratio)
THRESH_SEVERE   = 35.0
THRESH_MODERATE = 18.0
THRESH_MILD     = 10.0

# Frequency range of interest (Hz)
FREQ_LOW  = 1.0
FREQ_HIGH = 30.0

# Severe finding requires peak in this band
SEVERE_BAND_LOW  = 2.0
SEVERE_BAND_HIGH = 10.0

# Default P-gain param names per axis (used when params dict has no match)
AXIS_PARAMS = {
    "roll":  "MC_ROLLRATE_P",
    "pitch": "MC_PITCHRATE_P",
    "yaw":   "MC_YAWRATE_P",
}
DEFAULT_RATE_P = 0.15  # fallback when param not in log


class OscillationAnalyser(BaseAnalyser):
    name          = "oscillation"
    display_name  = "Oscillation Analysis"
    required_topics = ["vehicle_angular_velocity"]

    def analyse(
        self,
        topics: dict[str, pd.DataFrame],
        params: dict[str, float],
    ) -> AnalyserResult:
        df = topics["vehicle_angular_velocity"].copy()

        # PX4 column names vary by version — normalise
        col_map = {
            "rollspeed":  self._find_col(df, ["rollspeed", "xyz[0]", "x"]),
            "pitchspeed": self._find_col(df, ["pitchspeed", "xyz[1]", "y"]),
            "yawspeed":   self._find_col(df, ["yawspeed", "xyz[2]", "z"]),
        }

        # Estimate sample rate from timestamps
        if "timestamp" in df.columns:
            dt_us = df["timestamp"].diff().median()
            sample_rate = 1e6 / dt_us if dt_us > 0 else 250.0
        else:
            sample_rate = 250.0  # typical PX4 angular velocity rate

        axes = {
            "roll":  col_map["rollspeed"],
            "pitch": col_map["pitchspeed"],
            "yaw":   col_map["yawspeed"],
        }

        findings: list[Finding] = []
        health_score = 100.0
        all_chart_data: dict[str, dict] = {}

        for axis_name, col_name in axes.items():
            if col_name is None:
                continue

            signal_data = df[col_name].dropna().values
            if len(signal_data) < 64:
                continue

            level, dominant_hz, norm_amp, freqs, amps = self._analyse_axis(
                signal_data, sample_rate
            )

            # Store chart data regardless of finding
            all_chart_data[axis_name] = {
                "frequencies": freqs[:512].tolist(),     # limit payload
                "amplitudes":  amps[:512].tolist(),
                "peak_hz":     dominant_hz,
                "norm_amp":    norm_amp,
            }

            if level == "NONE":
                continue

            severity = {
                "SEVERE":   Severity.CRITICAL,
                "MODERATE": Severity.WARNING,
                "MILD":     Severity.INFO,
            }[level]

            # Penalty
            health_score = max(0.0, health_score - PENALTIES[level])

            # Param recommendation
            param_name = AXIS_PARAMS[axis_name]
            current_p  = params.get(param_name, DEFAULT_RATE_P)
            suggested_p = round(current_p * 0.87, 4)

            param_changes = [
                ParamRecommendation(
                    param_name=param_name,
                    current_value=round(current_p, 4),
                    suggested_value=suggested_p,
                    unit=None,
                    change_direction="decrease",
                    reason=f"Reduce {axis_name}-rate P by ~13% to dampen {dominant_hz:.1f} Hz oscillation",
                )
            ]

            technical_summary = (
                f"{axis_name.capitalize()} axis: dominant oscillation at {dominant_hz:.1f} Hz, "
                f"normalised amplitude {norm_amp:.2f} ({level.lower()}). "
                f"Sample rate {sample_rate:.0f} Hz. "
                f"Current {param_name}={current_p}, suggested={suggested_p}."
            )

            findings.append(Finding(
                category=Category.OSCILLATION,
                severity=severity,
                title=f"{axis_name.capitalize()}-Axis Oscillation at {dominant_hz:.1f} Hz",
                technical_summary=technical_summary,
                plain_english=technical_summary,   # overwritten by Claude
                recommendation=f"Reduce {param_name} from {current_p} to {suggested_p}.",
                confidence=float(np.clip(norm_amp, 0.0, 1.0)),
                chart_data={
                    "axis": axis_name,
                    **all_chart_data[axis_name],
                },
                param_changes=param_changes,
            ))

        return AnalyserResult(
            analyser=self.name,
            display_name=self.display_name,
            findings=findings,
            health_score=health_score,
        )

    # ── helpers ─────────────────────────────────────────────────────────────

    def _find_col(self, df: pd.DataFrame, candidates: list[str]) -> Optional[str]:
        for c in candidates:
            if c in df.columns:
                return c
        return None

    def _analyse_axis(
        self,
        data: np.ndarray,
        sample_rate: float,
    ) -> tuple[str, float, float, np.ndarray, np.ndarray]:
        """
        Returns (level, dominant_hz, norm_amplitude, freq_bins, amplitudes)
        level ∈ {"NONE", "MILD", "MODERATE", "SEVERE"}
        """
        # Detrend + window
        detrended = data - np.mean(data)
        window    = np.hanning(len(detrended))
        windowed  = detrended * window

        # FFT — keep positive frequencies only
        spectrum = np.abs(fft.fft(windowed))
        freqs    = fft.fftfreq(len(windowed), d=1.0 / sample_rate)
        pos_mask = freqs > 0
        freqs    = freqs[pos_mask]
        spectrum = spectrum[pos_mask]

        if len(spectrum) == 0:
            return "NONE", 0.0, 0.0, np.array([]), np.array([])

        # Interest band mask
        band_mask = (freqs >= FREQ_LOW) & (freqs <= FREQ_HIGH)
        if not band_mask.any():
            return "NONE", 0.0, 0.0, freqs, spectrum

        band_freqs   = freqs[band_mask]
        band_spectrum = spectrum[band_mask]

        # Find peaks
        min_height = band_spectrum.max() * 0.15
        peaks, _   = signal.find_peaks(band_spectrum, height=min_height, distance=3)

        if len(peaks) == 0:
            return "NONE", 0.0, 0.0, freqs, spectrum

        # Dominant peak
        dominant_idx = peaks[np.argmax(band_spectrum[peaks])]
        dominant_hz  = float(band_freqs[dominant_idx])
        peak_amp     = float(band_spectrum[dominant_idx])
        median_val   = np.median(band_spectrum)
        norm_amp     = peak_amp / median_val if median_val > 0 else 0.0

        # Classify
        if norm_amp > THRESH_SEVERE and SEVERE_BAND_LOW <= dominant_hz <= SEVERE_BAND_HIGH:
            level = "SEVERE"
        elif norm_amp > THRESH_MODERATE:
            level = "MODERATE"
        elif norm_amp > THRESH_MILD:
            level = "MILD"
        else:
            level = "NONE"

        return level, dominant_hz, norm_amp, freqs, spectrum
