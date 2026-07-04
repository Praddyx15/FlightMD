"""
GPSAnalyser — GPS fix quality, satellite count, HDOP, jamming, spoofing.

GPS is mission-critical for multirotor operations. Loss of GPS mid-flight
typically triggers position hold failure or return-to-home activation.
Jamming and spoofing are increasingly common near urban and military areas.
"""

import numpy as np
import pandas as pd
from typing import Optional

from flightmd_core.analysers.base import BaseAnalyser
from flightmd_core.models.findings import (
    AnalyserResult, Finding, Severity, Category
)

# Fix type meanings
FIX_LABELS = {
    0: "No Fix",
    1: "No Fix",
    2: "2D Fix",
    3: "3D Fix",
    4: "DGPS",
    5: "RTK Float",
    6: "RTK Fixed",
}

# Thresholds
HDOP_WARNING  = 2.0
HDOP_CRITICAL = 4.0

SAT_DROP_THRESH = 4     # satellites lost in < 5s
SAT_DROP_WINDOW_S = 5.0

JAMMING_WARNING  = 100
JAMMING_CRITICAL = 180

SPOOFING_INDETERMINATE = 3
SPOOFING_DETECTED      = 4


class GPSAnalyser(BaseAnalyser):
    name            = "gps"
    display_name    = "GPS Analysis"
    required_topics = ["vehicle_gps_position"]
    optional_topics = ["sensor_gnss_relative"]

    def analyse(
        self,
        topics: dict[str, pd.DataFrame],
        params: dict[str, float],
    ) -> AnalyserResult:
        df = topics["vehicle_gps_position"].copy()
        findings: list[Finding] = []
        health_score = 100.0

        ts = df["timestamp"].values if "timestamp" in df.columns else np.arange(len(df))
        ts_s = ts / 1e6   # µs → s

        # ── 1. Fix type analysis ─────────────────────────────────────────────
        fix_col = self._find_col(df, ["fix_type", "fix_type_s"])
        if fix_col:
            fix_findings, fix_penalty = self._analyse_fix_type(
                df[fix_col].values, ts, ts_s
            )
            findings.extend(fix_findings)
            health_score = max(0.0, health_score - fix_penalty)

        # ── 2. Satellite count drops ─────────────────────────────────────────
        sat_col = self._find_col(df, ["satellites_used", "s_variance_m_s"])
        if sat_col and "satellites_used" in df.columns:
            sat_findings, sat_penalty = self._analyse_satellites(
                df["satellites_used"].values, ts_s, ts
            )
            findings.extend(sat_findings)
            health_score = max(0.0, health_score - sat_penalty)

        # ── 3. HDOP ──────────────────────────────────────────────────────────
        hdop_col = self._find_col(df, ["hdop", "eph"])
        if hdop_col:
            hdop_findings, hdop_penalty = self._analyse_hdop(
                df[hdop_col].values, ts, ts_s
            )
            findings.extend(hdop_findings)
            health_score = max(0.0, health_score - hdop_penalty)

        # ── 4. Jamming indicator ─────────────────────────────────────────────
        jam_col = self._find_col(df, ["jamming_indicator", "jamming_state"])
        if jam_col and "jamming_indicator" in df.columns:
            jam_findings, jam_penalty = self._analyse_jamming(
                df["jamming_indicator"].values, ts, ts_s
            )
            findings.extend(jam_findings)
            health_score = max(0.0, health_score - jam_penalty)

        # ── 5. Spoofing state ────────────────────────────────────────────────
        spoof_col = self._find_col(df, ["spoofing_state"])
        if spoof_col:
            spoof_findings, spoof_penalty = self._analyse_spoofing(
                df[spoof_col].values, ts, ts_s
            )
            findings.extend(spoof_findings)
            health_score = max(0.0, health_score - spoof_penalty)

        # Build chart data
        step = max(1, len(df) // 500)
        chart_data = {
            "timestamps": (ts[::step] / 1e3).tolist(),
            "satellites": df["satellites_used"].values[::step].tolist()
                if "satellites_used" in df.columns else [],
            "hdop": df[hdop_col].values[::step].tolist()
                if hdop_col and hdop_col in df.columns else [],
            "fix_type": df[fix_col].values[::step].tolist()
                if fix_col else [],
            "jamming": df["jamming_indicator"].values[::step].tolist()
                if "jamming_indicator" in df.columns else [],
        }

        for f in findings:
            if f.chart_data is None:
                f.chart_data = chart_data

        return AnalyserResult(
            analyser=self.name,
            display_name=self.display_name,
            findings=findings,
            health_score=health_score,
        )

    # ── private helpers ──────────────────────────────────────────────────────

    def _find_col(self, df: pd.DataFrame, candidates: list[str]) -> Optional[str]:
        for c in candidates:
            if c in df.columns:
                return c
        return None

    def _analyse_fix_type(
        self,
        fix: np.ndarray,
        ts_us: np.ndarray,
        ts_s: np.ndarray,
    ) -> tuple[list[Finding], float]:
        findings = []
        penalty = 0.0

        # Any fix < 3 (not 3D) during any period
        bad_fix_mask = fix < 3
        if bad_fix_mask.any():
            bad_count = int(bad_fix_mask.sum())
            max_bad_s = self._max_run_duration(bad_fix_mask, ts_s)
            worst_fix = int(fix[bad_fix_mask].min())
            penalty = 30.0
            tech = (
                f"GPS fix dropped below 3D fix for {bad_count} samples "
                f"(longest run: {max_bad_s:.1f}s). "
                f"Minimum fix type observed: {FIX_LABELS.get(worst_fix, str(worst_fix))}."
            )
            findings.append(Finding(
                category=Category.GPS,
                severity=Severity.CRITICAL,
                title=f"GPS Fix Lost During Flight ({FIX_LABELS.get(worst_fix, 'Unknown')})",
                technical_summary=tech,
                plain_english=tech,
                recommendation="Check GPS antenna orientation and cable routing. Avoid flying near buildings or metal structures. Ensure GPS is mounted away from interference sources.",
                confidence=min(1.0, max_bad_s / 10.0),
            ))
            return findings, penalty

        # Degradation: drop from 3D+ to exactly 2D
        degraded = (fix[:-1] >= 3) & (fix[1:] < 3)
        if degraded.any():
            deg_count = int(degraded.sum())
            penalty = max(penalty, 15.0)
            tech = (
                f"GPS fix degraded from 3D+ to <3D on {deg_count} occasions. "
                f"Fix types seen: {sorted(set(fix.tolist()))}."
            )
            findings.append(Finding(
                category=Category.GPS,
                severity=Severity.WARNING,
                title="GPS Fix Degradation",
                technical_summary=tech,
                plain_english=tech,
                recommendation="Inspect GPS cable for intermittent connection. Move GPS mast to higher, unobstructed position.",
                confidence=min(1.0, deg_count / 5.0),
            ))

        return findings, penalty

    def _analyse_satellites(
        self,
        sats: np.ndarray,
        ts_s: np.ndarray,
        ts_us: np.ndarray,
    ) -> tuple[list[Finding], float]:
        findings = []
        penalty = 0.0

        # Window-based drop detection
        window_samples = max(1, int(SAT_DROP_WINDOW_S * len(ts_s) / (ts_s[-1] - ts_s[0] + 1e-9)))
        for i in range(len(sats) - window_samples):
            chunk = sats[i:i + window_samples]
            drop = int(chunk[0]) - int(chunk.min())
            if drop >= SAT_DROP_THRESH:
                penalty = 15.0
                ts_start_ms = int(ts_us[i] / 1e3)
                tech = (
                    f"Satellite count dropped by {drop} (from {int(chunk[0])} to {int(chunk.min())}) "
                    f"within {SAT_DROP_WINDOW_S}s starting at t={ts_s[i]:.1f}s."
                )
                findings.append(Finding(
                    category=Category.GPS,
                    severity=Severity.WARNING,
                    title=f"GPS Satellite Count Drop ({drop} sats in {SAT_DROP_WINDOW_S}s)",
                    technical_summary=tech,
                    plain_english=tech,
                    recommendation="Possible signal blockage from airframe banking or obstacle. Review flight path for obstructions. Ensure GPS has clear sky view.",
                    confidence=min(1.0, drop / 8.0),
                    timestamp_start_ms=ts_start_ms,
                ))
                break   # one finding for this type is sufficient

        return findings, penalty

    def _analyse_hdop(
        self,
        hdop: np.ndarray,
        ts_us: np.ndarray,
        ts_s: np.ndarray,
    ) -> tuple[list[Finding], float]:
        findings = []
        penalty = 0.0

        hdop_clean = hdop[hdop > 0]   # filter zero/invalid
        if len(hdop_clean) == 0:
            return findings, penalty

        max_hdop = float(hdop_clean.max())
        mean_hdop = float(hdop_clean.mean())

        if max_hdop > HDOP_CRITICAL:
            penalty = 30.0
            sev = Severity.CRITICAL
            label = "CRITICAL"
        elif max_hdop > HDOP_WARNING:
            penalty = 15.0
            sev = Severity.WARNING
            label = "WARNING"
        else:
            return findings, penalty

        tech = (
            f"HDOP reached {max_hdop:.2f} (mean: {mean_hdop:.2f}). "
            f"Threshold: WARNING>{HDOP_WARNING}, CRITICAL>{HDOP_CRITICAL}. "
            f"High HDOP indicates poor satellite geometry and reduced position accuracy."
        )
        findings.append(Finding(
            category=Category.GPS,
            severity=sev,
            title=f"GPS Position Uncertainty ({label}, HDOP={max_hdop:.1f})",
            technical_summary=tech,
            plain_english=tech,
            recommendation="Fly in areas with better sky visibility. Wait for more satellites before arming (aim for HDOP < 1.5).",
            confidence=min(1.0, max_hdop / 5.0),
        ))
        return findings, penalty

    def _analyse_jamming(
        self,
        jamming: np.ndarray,
        ts_us: np.ndarray,
        ts_s: np.ndarray,
    ) -> tuple[list[Finding], float]:
        findings = []
        penalty = 0.0

        max_jam = int(jamming.max())
        mean_jam = float(jamming.mean())

        if max_jam > JAMMING_CRITICAL:
            penalty = 30.0
            sev = Severity.CRITICAL
            label = "CRITICAL — likely GPS jamming"
        elif max_jam > JAMMING_WARNING:
            penalty = 15.0
            sev = Severity.WARNING
            label = "WARNING — elevated RF interference"
        else:
            return findings, penalty

        tech = (
            f"Jamming indicator: max={max_jam}/255, mean={mean_jam:.0f}/255. "
            f"{label}. Threshold: WARNING>{JAMMING_WARNING}, CRITICAL>{JAMMING_CRITICAL}."
        )
        findings.append(Finding(
            category=Category.GPS,
            severity=sev,
            title=f"GPS RF Interference Detected (indicator={max_jam})",
            technical_summary=tech,
            plain_english=tech,
            recommendation="Do not fly in this area. Report to local aviation authority if jamming is suspected. Check for local RF interference sources near takeoff point.",
            confidence=min(1.0, max_jam / 255.0),
        ))
        return findings, penalty

    def _analyse_spoofing(
        self,
        spoof: np.ndarray,
        ts_us: np.ndarray,
        ts_s: np.ndarray,
    ) -> tuple[list[Finding], float]:
        findings = []
        penalty = 0.0

        max_spoof = int(spoof.max())

        if max_spoof >= SPOOFING_DETECTED:
            penalty = 30.0
            sev = Severity.CRITICAL
            label = "CRITICAL — GPS spoofing detected"
        elif max_spoof >= SPOOFING_INDETERMINATE:
            penalty = 15.0
            sev = Severity.WARNING
            label = "WARNING — GPS spoofing indeterminate"
        else:
            return findings, penalty

        spoof_label_map = {3: "Indeterminate", 4: "Spoofing Confirmed"}
        tech = (
            f"Spoofing state reached {spoof_label_map.get(max_spoof, str(max_spoof))} "
            f"({max_spoof}). {label}."
        )
        findings.append(Finding(
            category=Category.GPS,
            severity=sev,
            title=f"GPS Spoofing {spoof_label_map.get(max_spoof, 'Alert')}",
            technical_summary=tech,
            plain_english=tech,
            recommendation="Land immediately if spoofing is detected. Do not trust GPS-based navigation. Report incident to drone operator community and aviation authority.",
            confidence=1.0 if max_spoof >= SPOOFING_DETECTED else 0.5,
        ))
        return findings, penalty

    def _max_run_duration(self, mask: np.ndarray, ts_s: np.ndarray) -> float:
        max_dur = 0.0
        in_run = False
        start_s = 0.0
        for i, v in enumerate(mask):
            if v and not in_run:
                in_run = True
                start_s = ts_s[i]
            elif not v and in_run:
                in_run = False
                max_dur = max(max_dur, ts_s[i] - start_s)
        if in_run:
            max_dur = max(max_dur, ts_s[-1] - start_s)
        return max_dur
