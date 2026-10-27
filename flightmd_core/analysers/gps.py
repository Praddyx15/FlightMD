"""
GPSAnalyser: fix quality, satellite count, HDOP, jamming, spoofing.

Everything is judged in flight only (see phases.py). Without arming data
the leading no-fix stretch is dropped instead, so acquisition on the pad
isn't reported as a fix lost in flight.

PX4 sensor_gps enums (msg/SensorGps.msg, v1.14+):
  jamming_state  0 unknown, 1 ok, 2 warning, 3 critical
  spoofing_state 0 unknown, 1 none, 2 indicated, 3 multiple indications
"""

import numpy as np
import pandas as pd

from flightmd_core.analysers.base import BaseAnalyser
from flightmd_core.analysers.helpers import (
    confidence, downsample, find_col, find_runs, run_seconds, sample_rate_hz, when,
)
from flightmd_core.analysers.phases import flight_phases
from flightmd_core.models.findings import (
    AnalyserResult, Finding, Severity, Category
)

FIX_LABELS = {
    0: "No Fix",
    1: "No Fix",
    2: "2D Fix",
    3: "3D Fix",
    4: "DGPS",
    5: "RTK Float",
    6: "RTK Fixed",
}

FIX_LOSS_MIN_S = 1.0        # shorter dips below 3D are "degradation"

HDOP_WARNING  = 2.0
HDOP_CRITICAL = 4.0
HDOP_UNKNOWN  = 50.0        # 99.99 / 655.35 are "no estimate" sentinels

SAT_DROP_THRESH = 4         # satellites lost within the window
SAT_DROP_WINDOW_S = 5.0
SAT_MAX_VALID = 60          # 255 = unknown on MAVLink

JAMMING_WARNING  = 100      # jamming_indicator, 0-255
JAMMING_CRITICAL = 180
SUSTAIN_S = 2.0             # jamming / HDOP must hold this long, not spike once

JAM_STATE_WARNING = 2
JAM_STATE_CRITICAL = 3
SPOOF_INDICATED = 2
SPOOF_MULTIPLE = 3


class GPSAnalyser(BaseAnalyser):
    name            = "gps"
    display_name    = "GPS Analysis"
    required_topics = ["vehicle_gps_position"]
    weight          = 15.0
    optional_topics = ["vehicle_status", "vehicle_land_detected"]

    def analyse(self, topics, params):
        df = topics["vehicle_gps_position"]
        if "timestamp" not in df.columns:
            return self._skip("GPS topic has no timestamps.")
        df = df.sort_values("timestamp").reset_index(drop=True)
        ts_all = df["timestamp"].to_numpy(float)

        phases = flight_phases(topics)
        fix_col = find_col(df, ["fix_type"])
        keep = phases.mask(ts_all, "in_air")
        if not phases.known and fix_col:
            fixed = np.flatnonzero(df[fix_col].to_numpy(float) >= 3)
            if len(fixed):
                keep[: fixed[0]] = False

        w = df[keep].reset_index(drop=True)
        if len(w) < 5:
            return self._skip(f"Fewer than 5 GPS samples {phases.describe()}.")

        ts = w["timestamp"].to_numpy(float)
        rate = sample_rate_hz(ts, 5.0)
        sustain_n = max(1, int(round(SUSTAIN_S * rate)))
        has_fix = (w[fix_col].to_numpy(float) >= 3) if fix_col else np.ones(len(w), bool)
        where = phases.describe()

        findings: list[Finding] = []
        penalty = 0.0

        if fix_col:
            f, p = self._fix(w[fix_col].to_numpy(float), ts, where)
            findings += f
            penalty += p

        sats = None
        if "satellites_used" in w.columns:
            sats = w["satellites_used"].to_numpy(float, copy=True)
            sats[(sats < 0) | (sats > SAT_MAX_VALID)] = np.nan
            f, p = self._satellites(sats, has_fix, ts, rate)
            findings += f
            penalty += p

        hdop_col = find_col(w, ["hdop", "eph"])
        hdop_sustained = None
        if hdop_col:
            hdop = w[hdop_col].to_numpy(float, copy=True)
            hdop[(hdop <= 0) | (hdop >= HDOP_UNKNOWN) | ~has_fix] = np.nan
            hdop_sustained = _rolling(hdop, sustain_n, "median")
            f, p = self._hdop(hdop, hdop_sustained, hdop_col, ts)
            findings += f
            penalty += p

        f, p = self._jamming(w, ts, sustain_n)
        findings += f
        penalty += p

        if "spoofing_state" in w.columns:
            f, p = self._spoofing(w["spoofing_state"].to_numpy(float), ts)
            findings += f
            penalty += p

        cols = {"satellites": "satellites_used", "hdop": hdop_col, "fix_type": fix_col,
                "jamming": "jamming_indicator"}
        present = {k: c for k, c in cols.items() if c and c in df.columns}
        ts_ms, *vals = downsample(ts_all, *(df[c].to_numpy(float) for c in present.values()))
        chart_data = {"timestamps": ts_ms, **{k: [] for k in cols}, **dict(zip(present, vals))}
        for f in findings:
            if f.chart_data is None:
                f.chart_data = chart_data

        key_metrics = {}
        if sats is not None and np.isfinite(sats[has_fix]).any():
            key_metrics["min_satellites"] = float(np.nanmin(sats[has_fix]))
        if hdop_sustained is not None and np.isfinite(hdop_sustained).any():
            key_metrics["max_hdop"] = round(float(np.nanmax(hdop_sustained)), 3)

        return AnalyserResult(
            analyser=self.name,
            display_name=self.display_name,
            findings=findings,
            health_score=max(0.0, 100.0 - penalty),
            key_metrics=key_metrics,
        )

    def _fix(self, fix, ts, where):
        bad = fix < 3
        if not bad.any():
            return [], 0.0
        worst = int(np.nanmin(fix[bad]))
        worst_label = FIX_LABELS.get(worst, str(worst))

        if bad.all():
            tech = (
                f"No 3D GPS fix at any point {where} ({len(fix)} samples, best fix type "
                f"{FIX_LABELS.get(int(np.nanmax(fix)), '?')})."
            )
            return [Finding(
                category=Category.GPS,
                severity=Severity.CRITICAL,
                kind="gps.no_fix",
                title="No 3D GPS Fix During Flight",
                technical_summary=tech,
                plain_english=tech,
                recommendation="Wait for a 3D fix before arming, and check the GPS antenna, cable and mounting.",
                confidence=0.9,
                **when(ts[0], ts[-1]),
            )], 30.0

        runs = find_runs(bad)
        durations = [run_seconds(ts, a, b) for a, b in runs]
        i = int(np.argmax(durations))
        a, b = runs[i]
        longest = durations[i]
        end_us = ts[b] if b < len(ts) else ts[-1]

        if longest >= FIX_LOSS_MIN_S:
            tech = (
                f"GPS fix dropped below 3D {len(runs)} time(s) {where}; longest outage "
                f"{longest:.1f}s starting t={ts[a] / 1e6:.1f}s. Worst fix type: {worst_label}."
            )
            return [Finding(
                category=Category.GPS,
                severity=Severity.CRITICAL,
                kind="gps.fix_lost",
                title=f"GPS Fix Lost During Flight ({worst_label})",
                technical_summary=tech,
                plain_english=tech,
                recommendation="Check GPS antenna orientation and cable routing. Avoid flying near buildings or metal structures. Ensure GPS is mounted away from interference sources.",
                confidence=confidence(longest / FIX_LOSS_MIN_S - 1, longest),
                **when(ts[a], end_us),
            )], 30.0

        tech = (
            f"GPS fix briefly dropped below 3D {len(runs)} time(s) {where} "
            f"(longest {longest:.1f}s). Fix types seen: {sorted(set(int(v) for v in fix if np.isfinite(v)))}."
        )
        return [Finding(
            category=Category.GPS,
            severity=Severity.WARNING,
            kind="gps.fix_degraded",
            title="GPS Fix Degradation",
            technical_summary=tech,
            plain_english=tech,
            recommendation="Inspect the GPS cable for an intermittent connection and move the GPS mast higher, clear of obstructions.",
            confidence=confidence(len(runs) / 5.0, longest),
            **when(ts[a], end_us),
        )], 15.0

    def _satellites(self, sats, has_fix, ts, rate):
        s = np.where(has_fix, sats, np.nan)
        n = max(2, int(round(SAT_DROP_WINDOW_S * rate)))
        # minimum over the next n samples
        ahead_min = pd.Series(s[::-1]).rolling(n, min_periods=1).min().to_numpy()[::-1]
        drop = s - ahead_min
        hits = np.flatnonzero(drop >= SAT_DROP_THRESH)
        if not len(hits):
            return [], 0.0
        i = int(hits[0])
        d = int(drop[i])
        j = i + int(np.nanargmin(s[i:i + n]))
        tech = (
            f"Satellite count dropped by {d} (from {int(s[i])} to {int(s[j])}) "
            f"within {SAT_DROP_WINDOW_S:.0f}s starting at t={ts[i] / 1e6:.1f}s."
        )
        return [Finding(
            category=Category.GPS,
            severity=Severity.WARNING,
            kind="gps.sat_drop",
            title=f"GPS Satellite Count Drop ({d} sats in {SAT_DROP_WINDOW_S:.0f}s)",
            technical_summary=tech,
            plain_english=tech,
            recommendation="Possible signal blockage from airframe banking or obstacle. Review flight path for obstructions. Ensure GPS has clear sky view.",
            confidence=confidence(d / SAT_DROP_THRESH - 1),
            **when(ts[i], ts[j]),
        )], 15.0

    def _hdop(self, hdop, sustained, col, ts):
        if not np.isfinite(sustained).any():
            return [], 0.0
        j = int(np.nanargmax(sustained))
        worst = float(sustained[j])
        if worst > HDOP_CRITICAL:
            sev, penalty, label, thr = Severity.CRITICAL, 30.0, "CRITICAL", HDOP_CRITICAL
        elif worst > HDOP_WARNING:
            sev, penalty, label, thr = Severity.WARNING, 15.0, "WARNING", HDOP_WARNING
        else:
            return [], 0.0
        over = sustained > HDOP_WARNING
        runs = [r for r in find_runs(over) if r[0] <= j < r[1]]
        a, b = runs[0] if runs else (j, j + 1)
        tech = (
            f"{col.upper()} held at {worst:.2f} for at least {SUSTAIN_S:.0f}s in flight "
            f"(mean {float(np.nanmean(hdop)):.2f}). Threshold: WARNING>{HDOP_WARNING}, "
            f"CRITICAL>{HDOP_CRITICAL}. High HDOP means poor satellite geometry and reduced "
            f"position accuracy."
        )
        return [Finding(
            category=Category.GPS,
            severity=sev,
            kind="gps.hdop",
            title=f"GPS Position Uncertainty ({label}, HDOP={worst:.1f})",
            technical_summary=tech,
            plain_english=tech,
            recommendation="Fly in areas with better sky visibility. Wait for more satellites before arming (aim for HDOP < 1.5).",
            confidence=confidence(worst / thr - 1, run_seconds(ts, a, b)),
            **when(ts[a], ts[min(b, len(ts) - 1)]),
        )], penalty

    def _jamming(self, w, ts, sustain_n):
        level = 0          # 0 none, 1 warning, 2 critical
        parts = []
        span = None

        if "jamming_indicator" in w.columns:
            ind = w["jamming_indicator"].to_numpy(float)
            sus = _rolling(ind, sustain_n, "median")
            if np.isfinite(sus).any():
                peak = float(np.nanmax(sus))
                if peak > JAMMING_CRITICAL:
                    level = 2
                elif peak > JAMMING_WARNING:
                    level = 1
                if peak > JAMMING_WARNING:
                    parts.append(f"jamming indicator held at {peak:.0f}/255 for {SUSTAIN_S:.0f}s "
                                 f"(WARNING>{JAMMING_WARNING}, CRITICAL>{JAMMING_CRITICAL})")
                    span = _span(sus > JAMMING_WARNING, ts)

        # the reciever's own verdict, worth as much as the raw indicator
        if "jamming_state" in w.columns:
            st = w["jamming_state"].to_numpy(float)
            sus = _rolling(st, sustain_n, "min")   # state must hold, not blip
            worst = int(np.nanmax(sus)) if np.isfinite(sus).any() else 0
            if worst >= JAM_STATE_WARNING:
                level = max(level, 2 if worst >= JAM_STATE_CRITICAL else 1)
                parts.append(f"receiver jamming state {'critical' if worst >= JAM_STATE_CRITICAL else 'warning'} "
                             f"for {SUSTAIN_S:.0f}s or more")
                span = span or _span(sus >= JAM_STATE_WARNING, ts)

        if level == 0:
            return [], 0.0
        sev = Severity.CRITICAL if level == 2 else Severity.WARNING
        tech = "GPS RF interference in flight: " + "; ".join(parts) + "."
        rec = (
            "Treat GPS as unreliable here: don't fly GPS-dependent missions at this site, and "
            "look for interference sources near the take-off point."
            if level == 2 else
            "Look for onboard RF sources near the GPS (video TX, companion computer, USB 3 "
            "cables) and move or shield them."
        )
        return [Finding(
            category=Category.GPS,
            severity=sev,
            kind="gps.jamming",
            title="GPS RF Interference Detected",
            technical_summary=tech,
            plain_english=tech,
            recommendation=rec,
            confidence=0.85 if level == 2 else 0.6,
            **when(*(span or (None, None))),
        )], 30.0 if level == 2 else 15.0

    def _spoofing(self, spoof, ts):
        worst = int(np.nanmax(spoof)) if np.isfinite(spoof).any() else 0
        if worst >= SPOOF_MULTIPLE:
            sev, penalty, label = Severity.CRITICAL, 30.0, "Multiple Indications"
        elif worst >= SPOOF_INDICATED:
            sev, penalty, label = Severity.WARNING, 15.0, "Indicated"
        else:
            return [], 0.0
        flagged = spoof >= SPOOF_INDICATED
        span = _span(flagged, ts)
        tech = (
            f"Receiver spoofing state reached {worst} ({label.lower()}) in flight, "
            f"{int(flagged.sum())} samples flagged."
        )
        return [Finding(
            category=Category.GPS,
            severity=sev,
            kind="gps.spoofing",
            title=f"GPS Spoofing {label}",
            technical_summary=tech,
            plain_english=tech,
            recommendation="Don't trust GPS-based navigation in this area; fly in a non-GPS mode and land if it recurs. Report repeated spoofing to the relevant aviation authority.",
            confidence=0.9 if worst >= SPOOF_MULTIPLE else 0.6,
            **when(*span),
        )], penalty


def _rolling(x, n, how):
    r = pd.Series(x).rolling(n, min_periods=n)
    return (r.median() if how == "median" else r.min()).to_numpy()


def _span(mask, ts):
    idx = np.flatnonzero(mask)
    if not len(idx):
        return None, None
    return ts[idx[0]], ts[idx[-1]]
