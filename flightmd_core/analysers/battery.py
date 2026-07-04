"""
BatteryAnalyser — voltage sag, internal resistance, capacity fade, thermal stress.

Battery health directly affects flight safety. High internal resistance causes
voltage sag under load, reducing effective capacity and potentially triggering
low-voltage failsafes mid-flight.
"""

import numpy as np
import pandas as pd
from typing import Optional

from flightmd_core.analysers.base import BaseAnalyser
from flightmd_core.models.findings import (
    AnalyserResult, Finding, Severity, Category, ParamRecommendation
)

# Sag thresholds (volts per cell, typical LiPo cell = 4.2V full)
SAG_WARNING_PER_CELL  = 0.50   # V
SAG_CRITICAL_PER_CELL = 1.00   # V

# Current thresholds for idle vs loaded classification
IDLE_CURRENT_THRESH   = 5.0    # A — below this = idle
LOADED_CURRENT_THRESH = 15.0   # A — above this = loaded

# Temperature warning threshold
TEMP_WARNING_C = 45.0

# C-rate concern (non-racing)
CRATE_WARNING = 30.0

# Capacity over-draw factor
CAPACITY_FADE_FACTOR = 1.15


class BatteryAnalyser(BaseAnalyser):
    name            = "battery"
    display_name    = "Battery Analysis"
    required_topics = ["battery_status"]

    def analyse(
        self,
        topics: dict[str, pd.DataFrame],
        params: dict[str, float],
    ) -> AnalyserResult:
        df = topics["battery_status"].copy()
        findings: list[Finding] = []
        health_score = 100.0

        # ── Column resolution (PX4 names vary by version) ───────────────────
        v_col    = self._find_col(df, ["voltage_v", "voltage_filtered_v", "voltage"])
        i_col    = self._find_col(df, ["current_a", "current_filtered_a", "current"])
        rem_col  = self._find_col(df, ["remaining", "remaining_capacity"])
        temp_col = self._find_col(df, ["temperature", "temperature_filtered"])
        cap_col  = self._find_col(df, ["capacity", "full_charge_capacity_wh"])

        if v_col is None or i_col is None:
            return AnalyserResult(
                analyser=self.name,
                display_name=self.display_name,
                findings=[],
                skipped=True,
                skip_reason="battery_status missing voltage or current columns.",
            )

        voltage  = df[v_col].dropna().values
        current  = df[i_col].dropna().values
        min_len  = min(len(voltage), len(current))
        voltage  = voltage[:min_len]
        current  = current[:min_len]
        ts_raw   = df["timestamp"].values[:min_len] if "timestamp" in df.columns else np.arange(min_len)
        ts_s     = ts_raw / 1e6   # µs → seconds

        remaining = df[rem_col].dropna().values[:min_len] if rem_col else np.ones(min_len)

        # Detect number of cells from peak voltage (assume 4.2V/cell at full)
        peak_v = float(voltage.max())
        n_cells = max(1, round(peak_v / 4.2))

        # ── 1. Voltage sag analysis ─────────────────────────────────────────
        sag_findings, sag_penalty = self._analyse_sag(
            voltage, current, remaining, n_cells, ts_s
        )
        findings.extend(sag_findings)
        health_score = max(0.0, health_score - sag_penalty)

        # ── 2. Capacity fade ────────────────────────────────────────────────
        if len(ts_s) > 10 and rem_col:
            cap_findings, cap_penalty = self._analyse_capacity(
                current, ts_s, remaining, cap_col, df
            )
            findings.extend(cap_findings)
            health_score = max(0.0, health_score - cap_penalty)

        # ── 3. Temperature ──────────────────────────────────────────────────
        if temp_col:
            temp = df[temp_col].dropna().values
            if len(temp) > 0:
                max_temp = float(temp.max())
                if max_temp > TEMP_WARNING_C:
                    health_score = max(0.0, health_score - 15)
                    tech = (
                        f"Battery temperature reached {max_temp:.1f}°C "
                        f"(threshold: {TEMP_WARNING_C}°C). "
                        f"Mean temperature: {float(temp.mean()):.1f}°C."
                    )
                    findings.append(Finding(
                        category=Category.BATTERY,
                        severity=Severity.WARNING,
                        title=f"Battery Thermal Stress ({max_temp:.0f}°C)",
                        technical_summary=tech,
                        plain_english=tech,
                        recommendation="Allow battery to cool before next flight. Check for adequate airflow around battery. Reduce aggressive manoeuvres.",
                        confidence=min(1.0, (max_temp - TEMP_WARNING_C) / 20.0),
                    ))

        # ── 4. C-rate ───────────────────────────────────────────────────────
        if len(current) > 10:
            peak_current = float(current.max())
            consumed_mah = self._integrate_current(current, ts_s)
            if consumed_mah > 50:   # sanity check — need a real flight
                c_rate = peak_current / (consumed_mah / 1000.0)
                if c_rate > CRATE_WARNING:
                    health_score = max(0.0, health_score - 10)
                    tech = (
                        f"Peak C-rate: {c_rate:.1f}C (peak current {peak_current:.1f}A, "
                        f"capacity drawn {consumed_mah:.0f}mAh). "
                        f"High C-rates accelerate cell degradation."
                    )
                    findings.append(Finding(
                        category=Category.BATTERY,
                        severity=Severity.WARNING,
                        title=f"High C-Rate Stress ({c_rate:.0f}C)",
                        technical_summary=tech,
                        plain_english=tech,
                        recommendation="Use higher-capacity battery or reduce payload. Ensure battery is rated for this C-rate.",
                        confidence=min(1.0, c_rate / 50.0),
                    ))

        # Build chart data
        step = max(1, min_len // 500)
        chart_data = {
            "timestamps": (ts_raw[::step] / 1e3).tolist(),
            "voltage": voltage[::step].tolist(),
            "current": current[::step].tolist(),
            "remaining_pct": (remaining[::step] * 100).tolist(),
            "n_cells": n_cells,
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

    def _analyse_sag(
        self,
        voltage: np.ndarray,
        current: np.ndarray,
        remaining: np.ndarray,
        n_cells: int,
        ts_s: np.ndarray,
    ) -> tuple[list[Finding], float]:
        findings: list[Finding] = []
        penalty = 0.0

        idle_mask   = current < IDLE_CURRENT_THRESH
        loaded_mask = current > LOADED_CURRENT_THRESH

        if not idle_mask.any() or not loaded_mask.any():
            return findings, penalty

        idle_v   = float(np.percentile(voltage[idle_mask], 50))
        loaded_v = float(np.percentile(voltage[loaded_mask], 10))   # worst 10%
        total_sag = idle_v - loaded_v
        sag_per_cell = total_sag / n_cells

        if sag_per_cell > SAG_CRITICAL_PER_CELL:
            sev     = Severity.CRITICAL
            penalty = 30.0
            label   = "CRITICAL — battery near end of life"
        elif sag_per_cell > SAG_WARNING_PER_CELL:
            sev     = Severity.WARNING
            penalty = 15.0
            label   = "WARNING — high internal resistance"
        else:
            return findings, penalty

        tech = (
            f"Voltage sag under load: idle voltage {idle_v:.2f}V, "
            f"loaded voltage {loaded_v:.2f}V, sag {total_sag:.2f}V total "
            f"({sag_per_cell:.2f}V/cell for {n_cells}S pack). {label}."
        )
        findings.append(Finding(
            category=Category.BATTERY,
            severity=sev,
            title=f"High Voltage Sag ({sag_per_cell:.2f}V/cell)",
            technical_summary=tech,
            plain_english=tech,
            recommendation=(
                "Battery internal resistance is elevated. "
                "Retire or cycle-test this pack. "
                "Consider replacing if sag exceeds 1V/cell."
            ) if sev == Severity.CRITICAL else (
                "Monitor battery health closely. "
                "Check pack age and cycle count. "
                "Storage-charge between flights if not flying regularly."
            ),
            confidence=min(1.0, sag_per_cell / SAG_CRITICAL_PER_CELL),
        ))
        return findings, penalty

    def _analyse_capacity(
        self,
        current: np.ndarray,
        ts_s: np.ndarray,
        remaining: np.ndarray,
        cap_col: Optional[str],
        df: pd.DataFrame,
    ) -> tuple[list[Finding], float]:
        findings: list[Finding] = []
        penalty = 0.0

        consumed_mah = self._integrate_current(current, ts_s)

        # Try to get rated capacity from the log
        rated_mah: Optional[float] = None
        if cap_col and cap_col in df.columns:
            cap_val = df[cap_col].dropna()
            if len(cap_val) > 0:
                v = float(cap_val.iloc[0])
                # PX4 stores capacity in mAh
                if v > 100:
                    rated_mah = v

        # Calculate estimated actual capacity based on remaining state of charge
        estimated_mah = None
        if remaining.min() > 0.0:
            used_fraction = 1.0 - float(remaining.min())
            if used_fraction > 0.05:
                estimated_mah = consumed_mah / used_fraction

        # Fallback: if rated capacity is not available, we can't detect fade
        if rated_mah is None:
            return findings, penalty

        if estimated_mah and estimated_mah * CAPACITY_FADE_FACTOR < rated_mah:
            penalty = 15.0
            fade_pct = (rated_mah - estimated_mah) / rated_mah * 100
            tech = (
                f"Estimated capacity is {estimated_mah:.0f}mAh but rated capacity is ~{rated_mah:.0f}mAh. "
                f"Apparent capacity deficit: {fade_pct:.0f}%. "
                f"This suggests capacity fade due to aging or cell damage."
            )
            findings.append(Finding(
                category=Category.BATTERY,
                severity=Severity.WARNING,
                title=f"Battery Capacity Fade (~{fade_pct:.0f}% below rated)",
                technical_summary=tech,
                plain_english=tech,
                recommendation="Cycle-test the battery with a cell analyser. If capacity is <80% of rated, retire the pack.",
                confidence=min(1.0, fade_pct / 30.0),
            ))

        return findings, penalty

    def _integrate_current(self, current: np.ndarray, ts_s: np.ndarray) -> float:
        """Trapezoidal integration → mAh consumed."""
        if len(current) < 2 or len(ts_s) < 2:
            return 0.0
        dt = np.diff(ts_s)
        avg_i = (current[:-1] + current[1:]) / 2.0
        coulombs = float(np.sum(avg_i * dt))
        return coulombs / 3.6   # A·s → mAh
