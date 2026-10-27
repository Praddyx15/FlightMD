"""
VibrationAnalyser: accelerometer vibration level, clipping, and agreement
between IMUs, in flight only.

The level is computed like ArduPilot's VIBE: take out everything below ~5 Hz
(gravity, manoeuvres) and RMS what's left, so the 30 / 60 m/s² thresholds
mean the same thing they mean in Mission Planner. Raw RMS included gravity,
so a hover alone read ~9.8.

Clipping is the sensor hitting its range limit (±8 g / ±16 g ...), not
"over 3 g". We use the autopilot's own clip counters when the log has them,
otherwise samples sitting on a flat plateau at the axis maximum.
"""

import re

import numpy as np
import pandas as pd

from flightmd_core.analysers.base import BaseAnalyser
from flightmd_core.analysers.helpers import confidence, downsample, find_col, sample_rate_hz, when
from flightmd_core.analysers.phases import flight_phases
from flightmd_core.models.findings import (
    AnalyserResult, Finding, Severity, Category
)

RMS_CRITICAL = 60.0     # m/s², high-passed
RMS_WARNING  = 30.0

HPF_CUTOFF_S = 0.2      # rolling-mean length ≈ 5 Hz high-pass
RMS_WINDOW_S = 1.0      # windowed RMS, for when it happened

# plateau fallback: only plausible as range clipping above ~7.5 g
CLIP_MIN_RANGE = 75.0
CLIP_PLATEAU = 0.99
CLIP_MIN_FRACTION = 0.001   # of in-flight samples
CLIP_MIN_COUNT = 10

IMU_CONSISTENCY_THRESH = 15.0   # m/s² RMS difference

_INSTANCE = re.compile(r"^sensor_accel(?:_(\d+))?$")


class VibrationAnalyser(BaseAnalyser):
    name          = "vibration"
    display_name  = "Vibration Analysis"
    required_topics = ["sensor_accel"]

    def analyse(self, topics, params):
        imus = self._instances(topics)
        if not imus:
            return self._skip("No sensor_accel topics found in log.")
        phases = flight_phases(topics)

        findings: list[Finding] = []
        health_score = 100.0
        rms_by_imu: dict[str, float] = {}
        clips_total = 0
        chart_data = {"instances": {}}

        for name, label, df in imus:
            x_col = find_col(df, ["x", "xyz[0]"])
            y_col = find_col(df, ["y", "xyz[1]"])
            z_col = find_col(df, ["z", "xyz[2]"])
            if not (x_col and y_col and z_col) or "timestamp" not in df.columns:
                continue
            d = df.dropna(subset=["timestamp", x_col, y_col, z_col]).sort_values("timestamp")
            d = d[phases.mask(d["timestamp"].to_numpy(float), "in_air")]
            if len(d) < 50:
                continue

            ts = d["timestamp"].to_numpy(float)
            fs = sample_rate_hz(ts, 250.0)
            raw = d[[x_col, y_col, z_col]].to_numpy(float)
            n_hp = max(3, int(round(HPF_CUTOFF_S * fs)))
            hp = raw - pd.DataFrame(raw).rolling(n_hp, center=True, min_periods=1).mean().to_numpy()

            rms_axes = np.sqrt(np.mean(hp ** 2, axis=0))
            rms = float(np.sqrt(np.mean(np.sum(hp ** 2, axis=1))))
            n_win = max(1, int(round(RMS_WINDOW_S * fs)))
            win_rms = np.sqrt(pd.Series(np.sum(hp ** 2, axis=1)).rolling(n_win, center=True, min_periods=1).mean().to_numpy())

            clips, clip_source = self._clips(d, raw)
            clips_total += clips
            rms_by_imu[label] = rms

            ts_ms, xs, ys, zs, vs = downsample(ts, raw[:, 0], raw[:, 1], raw[:, 2], win_rms)
            inst = {
                "timestamps": ts_ms, "x": xs, "y": ys, "z": zs, "vibe": vs,
                "rms_x": float(rms_axes[0]), "rms_y": float(rms_axes[1]), "rms_z": float(rms_axes[2]),
                "combined_rms": rms, "clip_count": clips,
            }
            chart_data["instances"][name] = inst

            if rms > RMS_WARNING:
                critical = rms > RMS_CRITICAL
                thr = RMS_CRITICAL if critical else RMS_WARNING
                health_score -= 30 if critical else 15
                over = np.flatnonzero(win_rms > RMS_WARNING)
                tech = (
                    f"{label}: vibration {rms:.1f} m/s² RMS in flight above 5 Hz "
                    f"({'CRITICAL' if critical else 'WARNING'}, threshold {thr:.0f}). "
                    f"Per axis X={rms_axes[0]:.1f}, Y={rms_axes[1]:.1f}, Z={rms_axes[2]:.1f}; "
                    f"worst 1 s window {np.nanmax(win_rms):.1f}."
                )
                findings.append(Finding(
                    category=Category.VIBRATION,
                    severity=Severity.CRITICAL if critical else Severity.WARNING,
                    kind="vibration.critical" if critical else "vibration.elevated",
                    title=f"{'Critical' if critical else 'Elevated'} Vibration — {label}",
                    technical_summary=tech,
                    plain_english=tech,
                    recommendation=(
                        "Immediately inspect propellers for balance/damage. Check all motor bell screws and frame arm bolts."
                        if critical else
                        "Balance propellers using a prop balancer. Inspect motor mounts for looseness."
                    ),
                    confidence=confidence(rms / thr - 1, len(over) / fs),
                    chart_data={"instance": name, **inst},
                    **(when(ts[over[0]], ts[over[-1]]) if len(over) else {}),
                ))

            if clips >= CLIP_MIN_COUNT and clips >= CLIP_MIN_FRACTION * len(d):
                health_score -= 15
                minutes = (ts[-1] - ts[0]) / 60e6
                tech = (
                    f"{label}: {clips} clipping events in {minutes:.1f} min of flight "
                    f"({clip_source}). The accelerometer hit its range limit, which corrupts "
                    f"the attitude and height estimate."
                )
                findings.append(Finding(
                    category=Category.VIBRATION,
                    severity=Severity.WARNING,
                    kind="vibration.clipping",
                    title=f"Hard IMU Clipping Detected — {label}",
                    technical_summary=tech,
                    plain_english=tech,
                    recommendation="Look for a loose prop, a damaged motor bell or a hard impact. Check all prop nuts are tight and that the flight controller sits on its damping mount.",
                    confidence=confidence(clips / (CLIP_MIN_FRACTION * len(d)) - 1),
                    chart_data={"instance": name, **inst},
                ))

        if not rms_by_imu:
            return self._skip(f"Not enough accelerometer data {phases.describe()}.")

        if len(rms_by_imu) >= 2:
            spread = max(rms_by_imu.values()) - min(rms_by_imu.values())
            if spread > IMU_CONSISTENCY_THRESH:
                health_score -= 15
                per = ", ".join(f"{k} {v:.1f}" for k, v in rms_by_imu.items())
                tech = (
                    f"IMU instances disagree by {spread:.1f} m/s² RMS "
                    f"(threshold {IMU_CONSISTENCY_THRESH:.0f}). Per IMU: {per}."
                )
                findings.append(Finding(
                    category=Category.VIBRATION,
                    severity=Severity.WARNING,
                    kind="vibration.imu_mismatch",
                    title="IMU Instance Inconsistency",
                    technical_summary=tech,
                    plain_english=tech,
                    recommendation="Check flight controller mounting. One IMU may be poorly isolated from vibration path.",
                    confidence=confidence(spread / IMU_CONSISTENCY_THRESH - 1),
                    chart_data=chart_data,
                ))

        return AnalyserResult(
            analyser=self.name,
            display_name=self.display_name,
            findings=findings,
            health_score=max(0.0, health_score),
            key_metrics={
                "max_imu_rms": round(max(rms_by_imu.values()), 3),
                "total_clip_count": float(clips_total),
            },
        )

    def _instances(self, topics):
        """[(topic, label, df)]: the bare name is IMU 0, _1/_2 the others.
        An old-style sensor_accel_0 next to the bare name is the same data."""
        found = {}
        for key, df in topics.items():
            m = _INSTANCE.match(key)
            if not m:
                continue
            idx = int(m.group(1) or 0)
            if idx in found and m.group(1) is not None:
                continue
            found[idx] = (key, f"IMU {idx}", df)
        return [found[i] for i in sorted(found)]

    def _clips(self, d, raw) -> tuple[int, str]:
        counters = [c for c in d.columns if c.startswith("clip_counter")]
        if counters:
            # PX4 sensor_accel.clip_counter[3]: clips per axis in that sample
            return int(np.nansum(d[counters].to_numpy(float))), "autopilot clip counter"
        cumulative = [c for c in d.columns if re.fullmatch(r"[Cc]lip\d?", c)]
        if cumulative:
            # ArduPilot VIBE.Clip0..2 are running totals
            v = d[cumulative].to_numpy(float)
            return int(np.nansum(np.nanmax(v, axis=0) - np.nanmin(v, axis=0))), "autopilot clip counter"

        total = 0
        for k in range(3):
            a = np.abs(raw[:, k])
            top = float(np.nanmax(a))
            if top < CLIP_MIN_RANGE:
                continue
            n = int(np.sum(a >= CLIP_PLATEAU * top))
            if n >= 3:      # one sample at the max is just the max
                total += n
        return total, "samples flat at the sensor's range limit"
