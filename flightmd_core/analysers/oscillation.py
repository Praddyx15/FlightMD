"""
OscillationAnalyser: sustained roll/pitch/yaw rate oscillations.

Each in-flight stretch of angular-rate data is resampled onto a uniform grid
(gaps over GAP_FACTOR x the normal interval split it) and cut into ~4 s
Hann windows with 50% overlap (a spectrogram). Per window we take the
biggest narrow peak in the band and estimate its amplitude in deg/s from
the power around the peak. Fixed-length windows make the numbers independent
of log length, and looking per window means a 20 s burst in a 20 min flight
still shows up. Windows are 4 s so a 1 Hz attitude-loop wobble still gets
four cycles per window.

Severity comes from the oscillation amplitude (deg/s), gated on the peak
standing well clear of the noise floor (prominence). What to change depends
on where the peak sits:
  < MID_BAND_HZ        rate P too high      -> reduce P
  MID..HIGH_BAND_HZ    D term / D filtering -> reduce D, lower D cutoff
  > HIGH_BAND_HZ       mechanical / noise   -> no gain change, check frame
"""

import numpy as np
import pandas as pd
from scipy import signal

from flightmd_core.analysers.base import BaseAnalyser
from flightmd_core.analysers.helpers import confidence, find_col, sample_rate_hz, to_list, when
from flightmd_core.analysers.phases import flight_phases
from flightmd_core.analysers.vehicle import rate_gain_names, vehicle_from_params
from flightmd_core.models.findings import (
    AnalyserResult, Finding, Severity, Category, ParamRecommendation
)

PENALTIES = {"SEVERE": 30, "MODERATE": 15, "MILD": 5}

# oscillation amplitude, deg/s
AMP_SEVERE   = 40.0
AMP_MODERATE = 15.0
AMP_MILD     = 5.0

# peak power / median band power in one window; white noise alone stays
# under ~20, and a peak also has to hold for three windows in a row
MIN_PROMINENCE = 25.0

FREQ_LOW = 1.0          # Hz; slower than this is piloting, not a control loop
FREQ_HIGH_CAP = 100.0
MID_BAND_HZ = 12.0
HIGH_BAND_HZ = 35.0

SEGMENT_S = 4.0
GAP_FACTOR = 5.0
MIN_RATE_HZ = 10.0      # tlog ATTITUDE at 2-4 Hz can't see a control-loop oscillation
CHART_FREQ_MIN = 0.5
CHART_MAX_BINS = 512


class OscillationAnalyser(BaseAnalyser):
    name          = "oscillation"
    display_name  = "Oscillation Analysis"
    required_topics = ["vehicle_angular_velocity"]

    def analyse(self, topics, params):
        df = topics["vehicle_angular_velocity"]
        if "timestamp" not in df.columns:
            return self._skip("Angular velocity topic has no timestamps.")

        axes = {
            "roll":  find_col(df, ["rollspeed", "xyz[0]", "x"]),
            "pitch": find_col(df, ["pitchspeed", "xyz[1]", "y"]),
            "yaw":   find_col(df, ["yawspeed", "xyz[2]", "z"]),
        }
        phases = flight_phases(topics)
        vehicle = vehicle_from_params(params)

        findings: list[Finding] = []
        health_score = 100.0
        key_metrics: dict[str, float] = {}
        assessed_any = False
        slow_rate = None

        for axis, col in axes.items():
            if col is None:
                continue
            d = df[["timestamp", col]].dropna().sort_values("timestamp")
            d = d[phases.mask(d["timestamp"].to_numpy(float), "in_air")]
            ts = d["timestamp"].to_numpy(float)
            x = d[col].to_numpy(float)
            fs = sample_rate_hz(ts, 0.0)
            if fs < MIN_RATE_HZ:
                slow_rate = fs
                continue

            spec = self._spectrogram(ts, x, fs)
            if spec is None:
                continue
            assessed_any = True
            res = self._worst(spec)
            # print(axis, res["peak_hz"], res["amp_dps"], res["prominence"])

            key_metrics[f"{axis}_peak_hz"] = round(res["peak_hz"], 3)
            key_metrics[f"{axis}_norm_amp"] = round(res["prominence"], 3)
            key_metrics[f"{axis}_osc_amp_dps"] = round(res["amp_dps"], 2)

            chart = {"axis": axis, **self._chart(spec), "peak_hz": res["peak_hz"],
                     "norm_amp": res["prominence"], "amp_dps": res["amp_dps"]}

            level = self._level(res)
            if level == "NONE":
                continue
            health_score = max(0.0, health_score - PENALTIES[level])
            findings.append(self._finding(axis, level, res, fs, chart, params, vehicle, phases))

        if not assessed_any:
            if slow_rate is not None:
                return self._skip(
                    f"Angular rate is logged at {slow_rate:.1f} Hz; oscillation analysis needs "
                    f"at least {MIN_RATE_HZ:.0f} Hz."
                )
            return self._skip(
                f"Not enough angular-rate data ({phases.describe()}) for a {SEGMENT_S:.0f} s analysis window."
            )

        return AnalyserResult(
            analyser=self.name,
            display_name=self.display_name,
            findings=findings,
            health_score=health_score,
            key_metrics=key_metrics,
        )

    def _spectrogram(self, ts, x, fs):
        """Per-window PSDs over every gap-free stretch. Returns the band
        frequencies, PSD columns, window centre times (µs) and the full
        frequency axis + mean PSD for the chart; None if no stretch is long
        enough for one window."""
        nper = int(2 ** round(np.log2(SEGMENT_S * fs)))
        dt_us = 1e6 / fs
        breaks = np.flatnonzero(np.diff(ts) > GAP_FACTOR * dt_us) + 1
        cols, times = [], []
        freqs = None
        for seg in np.split(np.arange(len(ts)), breaks):
            if len(seg) < nper:
                continue
            t_seg = ts[seg]
            grid = np.arange(t_seg[0], t_seg[-1], dt_us)
            if len(grid) < nper:
                continue
            y = np.interp(grid, t_seg, x[seg])
            f, tt, S = signal.spectrogram(
                y, fs=fs, window="hann", nperseg=nper, noverlap=nper // 2,
                detrend="constant", scaling="density", mode="psd",
            )
            freqs = f
            cols.append(S)
            times.append(grid[0] + tt * 1e6)
        if not cols:
            return None

        S = np.concatenate(cols, axis=1)
        hi = min(FREQ_HIGH_CAP, 0.8 * fs / 2)
        band = (freqs >= FREQ_LOW) & (freqs <= hi)
        return {
            "freqs": freqs, "band": band, "S": S,
            "times": np.concatenate(times), "df": float(freqs[1] - freqs[0]),
            "fs": fs, "seg_us": nper * dt_us,
        }

    def _worst(self, spec):
        fb = spec["freqs"][spec["band"]]
        Sb = spec["S"][spec["band"]]
        cols = np.arange(Sb.shape[1])
        pk = Sb.argmax(axis=0)
        floor = np.median(Sb, axis=0)
        prom = Sb[pk, cols] / np.maximum(floor, 1e-30)

        # sinusoid power = PSD above the floor over the Hann main lobe
        amp = np.empty(len(cols))
        for j, k in enumerate(pk):
            lo, hi = max(0, k - 2), min(len(fb), k + 3)
            p = np.clip(Sb[lo:hi, j] - floor[j], 0, None).sum() * spec["df"]
            amp[j] = np.degrees(np.sqrt(2 * p))
        amp[prom < MIN_PROMINENCE] = 0.0

        # sustained = median of three neighbouring windows (~8 s), so one
        # window with a bump doesn't count
        amp_s = pd.Series(amp).rolling(3, min_periods=1, center=True).median().to_numpy()
        prom_s = pd.Series(prom).rolling(3, min_periods=1, center=True).median().to_numpy()
        j = int(np.argmax(amp_s))
        if amp_s[j] > 0:
            peak_hz = float(fb[pk[j]])
        else:
            # nothing stands out; report where the average spectrum peaks so
            # the trend metric still means something
            peak_hz = float(fb[np.argmax(Sb.mean(axis=1))])

        # windows that carry the same oscillation, for the time span
        same = (amp >= AMP_MILD) & (np.abs(fb[pk] - peak_hz) <= 2.0)
        half = spec["seg_us"] / 2
        t0 = float(spec["times"][same].min() - half) if same.any() else None
        t1 = float(spec["times"][same].max() + half) if same.any() else None
        hop_s = spec["seg_us"] / 2e6
        return {
            "peak_hz": peak_hz,
            "amp_dps": float(amp_s[j]),
            "prominence": float(prom_s[j]),
            "t0": t0, "t1": t1,
            "duration_s": float(same.sum() * hop_s),
            "fs": spec["fs"],
        }

    def _level(self, res) -> str:
        if res["prominence"] < MIN_PROMINENCE:
            return "NONE"
        a = res["amp_dps"]
        if a >= AMP_SEVERE:
            return "SEVERE"
        if a >= AMP_MODERATE:
            return "MODERATE"
        if a >= AMP_MILD:
            return "MILD"
        return "NONE"

    def _chart(self, spec) -> dict:
        f = spec["freqs"]
        psd = spec["S"].mean(axis=1)
        keep = f >= CHART_FREQ_MIN
        f, psd = f[keep], psd[keep]
        step = max(1, int(np.ceil(len(f) / CHART_MAX_BINS)))
        return {
            "frequencies": to_list(f[::step]),
            "amplitudes": to_list(np.sqrt(psd[::step])),   # rad/s/√Hz
        }

    def _finding(self, axis, level, res, fs, chart, params, vehicle, phases) -> Finding:
        hz = res["peak_hz"]
        amp = res["amp_dps"]
        severity = {"SEVERE": Severity.CRITICAL, "MODERATE": Severity.WARNING, "MILD": Severity.INFO}[level]
        threshold = {"SEVERE": AMP_SEVERE, "MODERATE": AMP_MODERATE, "MILD": AMP_MILD}[level]
        p_name, d_name = rate_gain_names(vehicle, axis)

        changes: list[ParamRecommendation] = []
        if hz < MID_BAND_HZ:
            kind = "oscillation.rate_p"
            rec = f"Lower the {axis} rate P gain by about 13%."
            cur = params.get(p_name) if p_name else None
            if cur is not None and cur > 0:
                new = round(cur * 0.87, 4)
                changes.append(ParamRecommendation(
                    param_name=p_name, current_value=round(cur, 6), suggested_value=new,
                    change_direction="decrease",
                    reason=f"Reduce {axis}-rate P by ~13% to damp the {hz:.1f} Hz oscillation",
                ))
                rec = f"Reduce {p_name} from {cur:g} to {new:g} (about 13%), then re-test."
        elif hz < HIGH_BAND_HZ:
            kind = "oscillation.rate_d"
            rec = f"Lower the {axis} rate D gain by about 15%, or lower the D-term filter cutoff."
            cur = params.get(d_name) if d_name else None
            if cur is not None and cur > 0:
                new = round(cur * 0.85, 5)
                changes.append(ParamRecommendation(
                    param_name=d_name, current_value=round(cur, 6), suggested_value=new,
                    change_direction="decrease",
                    reason=f"{hz:.0f} Hz is D-term territory; reduce {axis}-rate D by ~15%",
                ))
                rec = (f"Reduce {d_name} from {cur:g} to {new:g} (about 15%), or lower the "
                       f"D-term filter cutoff. Don't raise D for this one.")
        else:
            kind = "oscillation.mechanical"
            rec = ("Check props, motor mounts and flight-controller mounting before touching gains; "
                   "if it persists, set up a notch filter at this frequency.")

        if not changes and kind != "oscillation.mechanical" and p_name is None:
            rec += f" (No {axis} gain is suggested for this vehicle type: {vehicle.frame}, {vehicle.autopilot}.)"

        tech = (
            f"{axis.capitalize()} rate oscillation at {hz:.1f} Hz, amplitude {amp:.1f} deg/s "
            f"({level.lower()}, threshold {threshold:.0f} deg/s), peak {res['prominence']:.0f}x "
            f"the noise floor, present for ~{res['duration_s']:.0f} s {phases.describe()}. "
            f"Rate data at {fs:.0f} Hz."
        )
        quality = min(1.0, (fs / 2) / (2 * hz)) if hz > 0 else 1.0
        return Finding(
            category=Category.OSCILLATION,
            severity=severity,
            kind=kind,
            title=f"{axis.capitalize()}-Axis Oscillation at {hz:.1f} Hz",
            technical_summary=tech,
            plain_english=tech,
            recommendation=rec,
            confidence=confidence(amp / threshold - 1, res["duration_s"], quality),
            chart_data=chart,
            param_changes=changes,
            **when(res["t0"], res["t1"]),
        )
