"""
BatteryAnalyser: voltage sag (from internal resistance), C-rate, capacity
fade and temperature.

Sag is not "full-pack voltage minus end-of-flight voltage": that is just the
discharge curve. In short windows (IR_WINDOW_S) where the current moves a
lot, we fit V = a + b·t − R·I; the open-circuit voltage barely changes in
that time, so R is the pack's internal resistance. Sag per cell is then
R × (peak current − resting current) / cells.
"""

import numpy as np
import pandas as pd

from flightmd_core.analysers.base import BaseAnalyser
from flightmd_core.analysers.helpers import confidence, downsample, find_col, when
from flightmd_core.models.findings import (
    AnalyserResult, Finding, Severity, Category
)

SAG_WARNING_PER_CELL  = 0.50   # V at peak load
SAG_CRITICAL_PER_CELL = 1.00

IR_WINDOW_S = 10.0
IR_MIN_SAMPLES = 10
IR_MIN_STEP_A = 2.0            # and at least 20% of the flight's current range

TEMP_WARNING_C = 60.0          # LiPo/Li-ion upper limit; 45 fires on any hot day

CRATE_WARNING = 30.0           # sustained, against rated capacity

CAPACITY_FADE_FACTOR = 1.15
MIN_USED_FRACTION = 0.3        # below this the estimate is mostly noise
CIRCULAR_TOLERANCE = 0.03

LIPO_FULL_V = 4.2


class BatteryAnalyser(BaseAnalyser):
    name            = "battery"
    display_name    = "Battery Analysis"
    required_topics = ["battery_status"]
    weight          = 15.0

    def analyse(self, topics, params):
        raw = topics["battery_status"]
        v_col = find_col(raw, ["voltage_v", "voltage_filtered_v", "voltage"])
        i_col = find_col(raw, ["current_a", "current_filtered_a", "current"])
        if v_col is None or i_col is None or "timestamp" not in raw.columns:
            return self._skip("battery_status missing voltage, current or timestamp columns.")

        # V, I and t must come from the same rows
        df = raw.dropna(subset=["timestamp", v_col, i_col]).sort_values("timestamp").reset_index(drop=True)
        df = df[df[v_col] > 0].reset_index(drop=True)
        if len(df) < 10:
            return self._skip("Fewer than 10 battery samples with both voltage and current.")

        ts = df["timestamp"].to_numpy(float)
        ts_s = ts / 1e6
        voltage = df[v_col].to_numpy(float)
        current = df[i_col].to_numpy(float)

        n_cells, cells_from = self._cells(df, params, voltage)
        capacity_mah = self._capacity(df, params)
        remaining = self._remaining(df)
        consumed_mah = self._integrate(current, ts_s)

        findings: list[Finding] = []
        health_score = 100.0
        key_metrics: dict[str, float] = {"consumed_mah": round(consumed_mah, 1)}

        r_pack, sag = self._sag(voltage, current, ts_s, n_cells)
        if r_pack is not None:
            key_metrics["sag_per_cell_v"] = round(sag, 4)
            key_metrics["internal_resistance_mohm_per_cell"] = round(r_pack / n_cells * 1000, 2)
            f, p = self._sag_finding(sag, r_pack, n_cells, cells_from, current, ts)
            findings += f
            health_score -= p

        if capacity_mah:
            f, p, c_rate = self._c_rate(current, ts, capacity_mah)
            key_metrics["peak_c_rate"] = round(c_rate, 2)
            findings += f
            health_score -= p

        if remaining is not None and capacity_mah:
            f, p = self._capacity_fade(current, ts_s, remaining, capacity_mah)
            findings += f
            health_score -= p

        temp_col = find_col(df, ["temperature", "temperature_filtered"])
        if temp_col:
            f, p = self._temperature(df[temp_col].to_numpy(float), ts)
            findings += f
            health_score -= p

        rem_pct = remaining * 100 if remaining is not None else np.full(len(ts), np.nan)
        ts_ms, v_ds, i_ds, r_ds = downsample(ts, voltage, current, rem_pct)
        chart_data = {
            "timestamps": ts_ms,
            "voltage": v_ds,
            "current": i_ds,
            "remaining_pct": r_ds,
            "n_cells": n_cells,
        }
        for f in findings:
            if f.chart_data is None:
                f.chart_data = chart_data

        return AnalyserResult(
            analyser=self.name,
            display_name=self.display_name,
            findings=findings,
            health_score=max(0.0, health_score),
            key_metrics=key_metrics,
        )

    def _cells(self, df, params, voltage) -> tuple[int, str]:
        # todo: battery_status_1 / BAT2_N_CELLS once a second pack is analysed
        if "cell_count" in df.columns:
            c = df["cell_count"].dropna()
            if len(c) and c.max() > 0:
                return int(c.max()), "log"
        for p in ("BAT1_N_CELLS", "BAT_N_CELLS"):
            if params.get(p, 0) > 0:
                return int(params[p]), p
        # guess from the fullest voltage seen; wrong for Li-ion or HV packs
        return max(1, round(float(voltage.max()) / LIPO_FULL_V)), "estimated"

    def _capacity(self, df, params):
        """Rated capacity in mAh, or None. PX4 -1 / 0 mean "not set"."""
        if "capacity" in df.columns:
            c = df["capacity"].dropna()
            if len(c) and c.max() > 100:
                return float(c.max())
        for p in ("BAT1_CAPACITY", "BAT_CAPACITY", "BATT_CAPACITY"):
            if params.get(p, 0) > 100:
                return float(params[p])
        return None

    def _remaining(self, df):
        col = find_col(df, ["remaining", "remaining_capacity"])
        if col is None:
            return None
        r = df[col].to_numpy(float, copy=True)
        r[r < 0] = np.nan                    # -1 = unknown on MAVLink
        if np.nanmax(r, initial=0) > 1.5:     # percent, not fraction
            r = r / 100.0
        return r if np.isfinite(r).any() else None

    def _integrate(self, current, ts_s) -> float:
        """mAh drawn, trapezoidal."""
        if len(current) < 2:
            return 0.0
        return float(np.sum((current[:-1] + current[1:]) / 2 * np.diff(ts_s))) / 3.6

    def _sag(self, voltage, current, ts_s, n_cells):
        """Pack internal resistance (Ω) from windowed fits, and the sag per
        cell it implies at this flight's peak load. (None, None) when no
        window had enough current change to measure it."""
        spread = np.percentile(current, 95) - np.percentile(current, 5)
        min_step = max(IR_MIN_STEP_A, 0.2 * spread)
        estimates = []
        for start in np.arange(ts_s[0], ts_s[-1], IR_WINDOW_S):
            m = (ts_s >= start) & (ts_s < start + IR_WINDOW_S)
            if m.sum() < IR_MIN_SAMPLES:
                continue
            i = current[m]
            if i.max() - i.min() < min_step:
                continue
            a = np.column_stack([np.ones(len(i)), ts_s[m] - start, -i])
            coef, *_ = np.linalg.lstsq(a, voltage[m], rcond=None)
            estimates.append(coef[2])
        if not estimates:
            return None, None

        r = max(0.0, float(np.median(estimates)))
        resting = pd.Series(current).rolling(IR_MIN_SAMPLES, min_periods=1).median().min()
        peak = np.percentile(current, 99)
        return r, r * max(0.0, peak - resting) / n_cells

    def _sag_finding(self, sag, r_pack, n_cells, cells_from, current, ts):
        if sag > SAG_CRITICAL_PER_CELL:
            sev, penalty, thr = Severity.CRITICAL, 30.0, SAG_CRITICAL_PER_CELL
        elif sag > SAG_WARNING_PER_CELL:
            sev, penalty, thr = Severity.WARNING, 15.0, SAG_WARNING_PER_CELL
        else:
            return [], 0.0
        cells = f"{n_cells}S" + (" (estimated from voltage)" if cells_from == "estimated" else "")
        peak_at = int(np.argmax(current))
        tech = (
            f"Internal resistance {r_pack * 1000:.0f} mΩ for the pack ({r_pack / n_cells * 1000:.1f} mΩ/cell, "
            f"{cells}), measured from voltage response to current steps. At the peak load of "
            f"{np.percentile(current, 99):.1f} A that is {sag:.2f} V/cell of sag "
            f"(threshold {thr} V/cell). Normal discharge over the flight is not counted."
        )
        rec = (
            "This pack's internal resistance is high. Cycle-test it with an IR-capable charger and "
            "retire it if the reading confirms; check connectors and wiring for a bad joint first."
            if sev == Severity.CRITICAL else
            "Measure the pack's internal resistance on a charger and compare with its earlier "
            "readings; check connectors, and consider a higher-rated pack for this load."
        )
        return [Finding(
            category=Category.BATTERY,
            severity=sev,
            kind="battery.sag",
            title=f"High Voltage Sag ({sag:.2f}V/cell)",
            technical_summary=tech,
            plain_english=tech,
            recommendation=rec,
            confidence=confidence(sag / thr - 1, quality=0.8 if cells_from == "estimated" else 1.0),
            **when(ts[peak_at]),
        )], penalty

    def _c_rate(self, current, ts, capacity_mah):
        # 1 s median so a single current spike isn't "the C-rate"
        n = max(1, int(round(1e6 / max(np.median(np.diff(ts)), 1.0))))
        sustained = pd.Series(current).rolling(n, min_periods=1).median().to_numpy()
        j = int(np.argmax(sustained))
        c_rate = float(sustained[j]) / (capacity_mah / 1000.0)
        if c_rate <= CRATE_WARNING:
            return [], 0.0, c_rate
        tech = (
            f"Sustained peak current {sustained[j]:.1f} A on a {capacity_mah:.0f} mAh pack = "
            f"{c_rate:.1f}C (threshold {CRATE_WARNING:.0f}C)."
        )
        return [Finding(
            category=Category.BATTERY,
            severity=Severity.WARNING,
            kind="battery.c_rate",
            title=f"High C-Rate Stress ({c_rate:.0f}C)",
            technical_summary=tech,
            plain_english=tech,
            recommendation="Check the pack's continuous C rating covers this load; otherwise use a higher-capacity or higher-rated pack, or reduce weight.",
            confidence=confidence(c_rate / CRATE_WARNING - 1),
            **when(ts[j]),
        )], 10.0, c_rate

    def _capacity_fade(self, current, ts_s, remaining, capacity_mah):
        ok = np.isfinite(remaining)
        if ok.sum() < 10:
            return [], 0.0
        drawn = np.concatenate(([0.0], np.cumsum((current[:-1] + current[1:]) / 2 * np.diff(ts_s)) / 3.6))

        # when "remaining" is itself 1 - drawn/capacity (PX4 with capacity
        # set, every ArduPilot log) comparing the two proves nothing
        model = 1.0 - drawn / capacity_mah
        if np.nanmax(np.abs(remaining[ok] - model[ok])) < CIRCULAR_TOLERANCE:
            return [], 0.0

        first, last = np.flatnonzero(ok)[[0, -1]]
        used = float(remaining[first] - remaining[last])
        if used < MIN_USED_FRACTION:
            return [], 0.0
        estimated = (drawn[last] - drawn[first]) / used
        if estimated * CAPACITY_FADE_FACTOR >= capacity_mah:
            return [], 0.0

        fade = (capacity_mah - estimated) / capacity_mah * 100
        tech = (
            f"{drawn[last] - drawn[first]:.0f} mAh drawn while state of charge fell by {used * 100:.0f}%, "
            f"which implies ~{estimated:.0f} mAh total against a rated {capacity_mah:.0f} mAh "
            f"({fade:.0f}% short)."
        )
        return [Finding(
            category=Category.BATTERY,
            severity=Severity.WARNING,
            kind="battery.capacity_fade",
            title=f"Battery Capacity Fade (~{fade:.0f}% below rated)",
            technical_summary=tech,
            plain_english=tech,
            recommendation="Cycle-test the battery with a cell analyser. If capacity is <80% of rated, retire the pack.",
            confidence=confidence(fade / 30.0, quality=min(1.0, used / 0.6)),
        )], 15.0

    def _temperature(self, temp, ts):
        if not np.isfinite(temp).any():
            return [], 0.0
        peak = float(np.nanmax(temp))
        if peak <= TEMP_WARNING_C:
            return [], 0.0
        hot = np.flatnonzero(temp > TEMP_WARNING_C)
        tech = (
            f"Battery temperature reached {peak:.1f}°C (threshold {TEMP_WARNING_C:.0f}°C); "
            f"mean {float(np.nanmean(temp)):.1f}°C."
        )
        return [Finding(
            category=Category.BATTERY,
            severity=Severity.WARNING,
            kind="battery.thermal",
            title=f"Battery Thermal Stress ({peak:.0f}°C)",
            technical_summary=tech,
            plain_english=tech,
            recommendation="Allow battery to cool before next flight. Check for adequate airflow around battery. Reduce aggressive manoeuvres.",
            confidence=confidence((peak - TEMP_WARNING_C) / 20.0),
            **when(ts[hot[0]], ts[hot[-1]]),
        )], 15.0
