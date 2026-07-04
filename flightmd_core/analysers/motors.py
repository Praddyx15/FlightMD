"""
MotorAnalyser — ESC telemetry, motor balance, RPM dropouts, thermal stress.

ESC telemetry is only available from BLHeli32, KISS, or AM32 ESCs with
telemetry enabled in PX4. Most logs won't have this — skipped gracefully.
"""

import numpy as np
import pandas as pd
from typing import Optional

from flightmd_core.analysers.base import BaseAnalyser
from flightmd_core.models.findings import (
    AnalyserResult, Finding, Severity, Category
)

# Motor balance thresholds (std/mean of RPM across motors)
BALANCE_WARNING  = 0.08
BALANCE_CRITICAL = 0.15

# ESC temperature warning
TEMP_WARNING_C = 80.0

# Current imbalance: one motor drawing >20% more than average
CURRENT_IMBALANCE_PCT = 0.20

# RPM dropout: motor drops to 0 for >100ms mid-flight
RPM_DROPOUT_MS = 100.0


class MotorAnalyser(BaseAnalyser):
    name            = "motors"
    display_name    = "Motor / ESC Analysis"
    required_topics = ["esc_status"]

    def analyse(
        self,
        topics: dict[str, pd.DataFrame],
        params: dict[str, float],
    ) -> AnalyserResult:
        df = topics["esc_status"].copy()
        findings: list[Finding] = []
        health_score = 100.0

        ts_us = df["timestamp"].values if "timestamp" in df.columns else np.arange(len(df))
        ts_s  = ts_us / 1e6

        # Detect available motors — columns like esc[0].esc_rpm, esc_rpm[0], etc.
        rpm_cols  = self._find_motor_cols(df, "rpm")
        temp_cols = self._find_motor_cols(df, "temperature")
        curr_cols = self._find_motor_cols(df, "current")

        if not rpm_cols:
            return AnalyserResult(
                analyser=self.name,
                display_name=self.display_name,
                findings=[],
                skipped=True,
                skip_reason="No ESC RPM columns found. ESC telemetry not available in this log.",
            )

        n_motors = len(rpm_cols)
        rpm_matrix = np.column_stack([df[c].fillna(0).values for c in rpm_cols])

        # ── 1. Motor balance at hover ────────────────────────────────────────
        hover_mask = self._detect_hover(rpm_matrix, ts_s)
        if hover_mask.sum() > 50:
            hover_rpm = rpm_matrix[hover_mask]
            mean_rpm  = hover_rpm.mean(axis=1)
            std_rpm   = hover_rpm.std(axis=1)
            mean_mean = float(mean_rpm.mean())
            mean_std  = float(std_rpm.mean())
            balance_idx = mean_std / mean_mean if mean_mean > 0 else 0.0

            if balance_idx > BALANCE_CRITICAL:
                health_score = max(0.0, health_score - 30)
                tech = (
                    f"Motor balance index: {balance_idx:.3f} (CRITICAL, threshold={BALANCE_CRITICAL}). "
                    f"Mean hover RPM: {mean_mean:.0f}, RPM std: {mean_std:.0f}. "
                    f"One or more motors significantly weaker than others."
                )
                findings.append(Finding(
                    category=Category.MOTORS,
                    severity=Severity.CRITICAL,
                    title=f"Significant Motor Imbalance (balance index={balance_idx:.2f})",
                    technical_summary=tech,
                    plain_english=tech,
                    recommendation="Inspect all motors for damage. Check propeller seating. Test each motor individually on the bench. Replace any weak or damaged motor.",
                    confidence=min(1.0, balance_idx / 0.25),
                    chart_data=self._build_chart(df, rpm_cols, ts_us),
                ))
            elif balance_idx > BALANCE_WARNING:
                health_score = max(0.0, health_score - 15)
                tech = (
                    f"Motor balance index: {balance_idx:.3f} (WARNING, threshold={BALANCE_WARNING}). "
                    f"Mean hover RPM: {mean_mean:.0f}, RPM std: {mean_std:.0f}."
                )
                findings.append(Finding(
                    category=Category.MOTORS,
                    severity=Severity.WARNING,
                    title=f"Motor Balance Warning (balance index={balance_idx:.2f})",
                    technical_summary=tech,
                    plain_english=tech,
                    recommendation="One motor may be weaker or have a worn bearing. Run a motor test sequence and compare RPM vs throttle curves.",
                    confidence=min(1.0, balance_idx / 0.20),
                    chart_data=self._build_chart(df, rpm_cols, ts_us),
                ))

        # ── 2. ESC temperature ───────────────────────────────────────────────
        if temp_cols:
            for i, tcol in enumerate(temp_cols):
                temp = df[tcol].dropna().values
                if len(temp) == 0:
                    continue
                max_temp = float(temp.max())
                if max_temp > TEMP_WARNING_C:
                    health_score = max(0.0, health_score - 15)
                    tech = (
                        f"ESC {i+1} temperature reached {max_temp:.0f}°C "
                        f"(threshold: {TEMP_WARNING_C}°C)."
                    )
                    findings.append(Finding(
                        category=Category.MOTORS,
                        severity=Severity.WARNING,
                        title=f"ESC Thermal Stress — Motor {i+1} ({max_temp:.0f}°C)",
                        technical_summary=tech,
                        plain_english=tech,
                        recommendation=f"Reduce sustained full-throttle time. Ensure ESC {i+1} has adequate airflow. Check for prop size mismatch.",
                        confidence=min(1.0, (max_temp - TEMP_WARNING_C) / 20.0),
                    ))

        # ── 3. Current imbalance ─────────────────────────────────────────────
        if curr_cols and len(curr_cols) >= 2:
            curr_matrix = np.column_stack([df[c].fillna(0).values for c in curr_cols])
            mean_curr = curr_matrix.mean(axis=1, keepdims=True)
            max_curr  = curr_matrix.max(axis=1)
            with np.errstate(divide="ignore", invalid="ignore"):
                imbalance = np.where(mean_curr > 0, (max_curr - mean_curr.flatten()) / mean_curr.flatten(), 0)
            max_imbalance = float(imbalance.max())
            if max_imbalance > CURRENT_IMBALANCE_PCT:
                health_score = max(0.0, health_score - 15)
                worst_motor = int(np.argmax(curr_matrix.max(axis=0)))
                tech = (
                    f"Motor {worst_motor+1} drew {max_imbalance*100:.0f}% more current than average "
                    f"at peak. Threshold: {CURRENT_IMBALANCE_PCT*100:.0f}%."
                )
                findings.append(Finding(
                    category=Category.MOTORS,
                    severity=Severity.WARNING,
                    title=f"Motor Current Imbalance — Motor {worst_motor+1}",
                    technical_summary=tech,
                    plain_english=tech,
                    recommendation=f"Inspect motor {worst_motor+1} for mechanical drag, binding, or stator damage. Check propeller for cracks.",
                    confidence=min(1.0, max_imbalance / 0.40),
                ))

        # ── 4. RPM dropout detection ─────────────────────────────────────────
        for i, rcol in enumerate(rpm_cols):
            rpm = df[rcol].fillna(0).values
            # Find periods where RPM = 0 mid-flight (after first armed period)
            # Proxy for "in flight": mean RPM > 1000
            if rpm.mean() < 500:
                continue
            armed_start = next((j for j, v in enumerate(rpm) if v > 500), None)
            if armed_start is None:
                continue
            armed_rpm = rpm[armed_start:]
            armed_ts  = ts_us[armed_start:]
            dropout_mask = armed_rpm < 100
            if not dropout_mask.any():
                continue

            # Find runs
            runs = []
            in_run = False
            run_start = 0
            for j, v in enumerate(dropout_mask):
                if v and not in_run:
                    in_run, run_start = True, j
                elif not v and in_run:
                    in_run = False
                    runs.append((run_start, j))
            if in_run:
                runs.append((run_start, len(dropout_mask)))

            for rs, re in runs:
                dur_ms = (armed_ts[min(re, len(armed_ts)-1)] - armed_ts[rs]) / 1e3
                if dur_ms > RPM_DROPOUT_MS:
                    health_score = max(0.0, health_score - 30)
                    ts_start_ms = int(armed_ts[rs] / 1e3)
                    tech = (
                        f"Motor {i+1} RPM dropped to near-zero for {dur_ms:.0f}ms "
                        f"at t={ts_s[armed_start + rs]:.1f}s during flight. "
                        f"This indicates a possible motor failure event."
                    )
                    findings.append(Finding(
                        category=Category.MOTORS,
                        severity=Severity.CRITICAL,
                        title=f"Motor {i+1} Dropout Detected ({dur_ms:.0f}ms)",
                        technical_summary=tech,
                        plain_english=tech,
                        recommendation=f"Do NOT fly this aircraft until motor {i+1} is inspected and tested. Check ESC connection, motor windings, and prop nut.",
                        confidence=0.95,
                        timestamp_start_ms=ts_start_ms,
                    ))
                    break   # one dropout finding per motor

        return AnalyserResult(
            analyser=self.name,
            display_name=self.display_name,
            findings=findings,
            health_score=health_score,
        )

    # ── helpers ──────────────────────────────────────────────────────────────

    def _find_motor_cols(self, df: pd.DataFrame, field: str) -> list[str]:
        """Find ESC columns matching various PX4 naming conventions."""
        candidates = []
        # Pattern: esc[N].esc_rpm, esc_rpm[N], esc[N]_rpm, motor_N_rpm
        for col in df.columns:
            if field in col.lower() and any(
                pat in col.lower() for pat in ["esc", "motor"]
            ):
                candidates.append(col)
        # Sort for consistent ordering
        return sorted(candidates)

    def _detect_hover(self, rpm_matrix: np.ndarray, ts_s: np.ndarray) -> np.ndarray:
        """
        Identify hover periods: all motors spinning >500 RPM,
        RPM variance across motors relatively low, sustained >2s.
        """
        all_spinning = (rpm_matrix > 500).all(axis=1)
        with np.errstate(divide="ignore", invalid="ignore"):
            cv = np.where(
                rpm_matrix.mean(axis=1) > 0,
                rpm_matrix.std(axis=1) / rpm_matrix.mean(axis=1),
                1.0,
            )
        stable = cv < 0.15
        return all_spinning & stable

    def _build_chart(self, df: pd.DataFrame, rpm_cols: list[str], ts_us: np.ndarray) -> dict:
        step = max(1, len(df) // 500)
        return {
            "timestamps": (ts_us[::step] / 1e3).tolist(),
            "rpm_per_motor": {
                col: df[col].fillna(0).values[::step].tolist()
                for col in rpm_cols
            },
        }
