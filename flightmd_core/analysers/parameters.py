"""
ParameterAnalyser — PX4 parameter anomaly detection.

Checks logged parameters against PX4 defaults, safe ranges, and known
dangerous combinations. Unlike other analysers, this uses the params dict
directly — not topic DataFrames.
"""

import json
import os

import pandas as pd

from flightmd_core.analysers.base import BaseAnalyser
from flightmd_core.models.findings import (
    AnalyserResult, Finding, Severity, Category
)

# Deprecated parameters (PX4 v1.13 → v1.14 migrations)
DEPRECATED_PARAMS = {
    "MC_ACRO_EXPO",
    "MC_ACRO_EXPO_Y",
    "MC_ACRO_SUPEXPO",
    "MC_ACRO_SUPEXPOY",
    "MPC_VELD_LP",
    "EKF2_MAG_DECL",
    "LND_FLIGHT_T_LO",
    "LND_FLIGHT_T_HI",
}

# Dangerous parameter combinations
DANGEROUS_COMBOS = [
    {
        "params": {"MC_ROLLRATE_P": (">", 0.3), "MC_ROLLRATE_D": ("<", 0.001)},
        "severity": Severity.WARNING,
        "title": "Oscillation Risk: High Rate P + Low Rate D",
        "reason": "MC_ROLLRATE_P > 0.3 with MC_ROLLRATE_D < 0.001 is likely to cause roll oscillation.",
    },
    {
        "params": {"MC_PITCHRATE_P": (">", 0.3), "MC_PITCHRATE_D": ("<", 0.001)},
        "severity": Severity.WARNING,
        "title": "Oscillation Risk: High Pitch P + Low Pitch D",
        "reason": "MC_PITCHRATE_P > 0.3 with MC_PITCHRATE_D < 0.001 is likely to cause pitch oscillation.",
    },
    {
        "params": {"MPC_XY_P": (">", 1.5), "MPC_XY_VEL_P_ACC": ("<", 1.5)},
        "severity": Severity.WARNING,
        "title": "Position Loop Instability Risk",
        "reason": "MPC_XY_P > 1.5 with MPC_XY_VEL_P_ACC < 1.5 may cause position loop oscillation.",
    },
    {
        "params": {"BAT_LOW_THR": ("<", "BAT_CRIT_THR"),},
        "severity": Severity.CRITICAL,
        "title": "Battery Thresholds Inverted",
        "reason": "BAT_LOW_THR must be greater than BAT_CRIT_THR (e.g. low=0.25, critical=0.10).",
    },
    {
        "params": {"COM_RC_LOSS_T": ("<", 0.5)},
        "severity": Severity.WARNING,
        "title": "Very Short RC Loss Timeout",
        "reason": "COM_RC_LOSS_T < 0.5s may trigger unintended failsafe on brief signal glitches.",
    },
]

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")


class ParameterAnalyser(BaseAnalyser):
    name            = "parameters"
    display_name    = "Parameter Analysis"
    required_topics = []    # uses params dict, not topics
    optional_topics = []

    def is_applicable(self, available_topics: set[str]) -> bool:
        # Always applicable — params are always present
        return True

    def analyse(
        self,
        topics: dict[str, pd.DataFrame],
        params: dict[str, float],
    ) -> AnalyserResult:
        findings: list[Finding] = []
        health_score = 100.0

        if not params:
            return AnalyserResult(
                analyser=self.name,
                display_name=self.display_name,
                findings=[],
                skipped=True,
                skip_reason="No parameters found in log.",
            )

        # ── Load reference data ──────────────────────────────────────────────
        safe_ranges = self._load_safe_ranges()

        # ── 1. Deprecated params ─────────────────────────────────────────────
        for p in DEPRECATED_PARAMS:
            if p in params:
                health_score = max(0.0, health_score - 5)
                tech = f"Parameter '{p}' is deprecated in PX4 v1.14 and has no effect."
                findings.append(Finding(
                    category=Category.PARAMETERS,
                    severity=Severity.INFO,
                    title=f"Deprecated Parameter: {p}",
                    technical_summary=tech,
                    plain_english=tech,
                    recommendation=f"Remove '{p}' from your parameter file. It is no longer used by PX4 v1.14.",
                    confidence=1.0,
                ))

        # ── 2. Out-of-safe-range params ──────────────────────────────────────
        for pname, pval in params.items():
            if pname not in safe_ranges:
                continue
            sr = safe_ranges[pname]
            mn = sr.get("min")
            mx = sr.get("max")
            unit = sr.get("unit")

            if mn is not None and pval < mn:
                distance_ratio = (mn - pval) / (mn - (mn * 0.5 + 1e-9))
                sev = Severity.CRITICAL if distance_ratio > 0.5 else Severity.WARNING
                penalty = 30.0 if sev == Severity.CRITICAL else 15.0
                health_score = max(0.0, health_score - penalty)
                tech = (
                    f"{pname} = {pval} is below minimum safe value of {mn}"
                    + (f" {unit}" if unit else "") + "."
                )
                findings.append(Finding(
                    category=Category.PARAMETERS,
                    severity=sev,
                    title=f"Parameter Below Safe Range: {pname}",
                    technical_summary=tech,
                    plain_english=tech,
                    recommendation=f"Set {pname} to at least {mn}{' ' + unit if unit else ''} for safe operation.",
                    confidence=0.9,
                ))

            elif mx is not None and pval > mx:
                distance_ratio = (pval - mx) / (mx * 0.5 + 1e-9)
                sev = Severity.CRITICAL if distance_ratio > 0.5 else Severity.WARNING
                penalty = 30.0 if sev == Severity.CRITICAL else 15.0
                health_score = max(0.0, health_score - penalty)
                tech = (
                    f"{pname} = {pval} exceeds maximum safe value of {mx}"
                    + (f" {unit}" if unit else "") + "."
                )
                findings.append(Finding(
                    category=Category.PARAMETERS,
                    severity=sev,
                    title=f"Parameter Above Safe Range: {pname}",
                    technical_summary=tech,
                    plain_english=tech,
                    recommendation=f"Reduce {pname} to at most {mx}{' ' + unit if unit else ''} for safe operation.",
                    confidence=0.9,
                ))

        # ── 3. Dangerous combinations ────────────────────────────────────────
        for combo in DANGEROUS_COMBOS:
            if self._check_combo(combo["params"], params):
                health_score = max(0.0, health_score - (
                    30.0 if combo["severity"] == Severity.CRITICAL else 15.0
                ))
                param_vals = {
                    p: params.get(p, "N/A")
                    for p in combo["params"].keys()
                    if not isinstance(list(combo["params"].values())[0][1], str)
                }
                tech = (
                    combo["reason"] + " "
                    + " ".join(f"{k}={v}" for k, v in param_vals.items())
                )
                findings.append(Finding(
                    category=Category.PARAMETERS,
                    severity=combo["severity"],
                    title=combo["title"],
                    technical_summary=tech,
                    plain_english=tech,
                    recommendation=combo["reason"],
                    confidence=0.95,
                ))

        return AnalyserResult(
            analyser=self.name,
            display_name=self.display_name,
            findings=findings,
            health_score=health_score,
            key_metrics={
                "param_count": float(len(params)),
                "anomaly_count": float(len(findings)),
            },
        )

    # ── helpers ──────────────────────────────────────────────────────────────

    def _load_defaults(self) -> dict:
        for fname in ["v1_14.json", "v1_13.json"]:
            path = os.path.join(DATA_DIR, "px4_param_defaults", fname)
            if os.path.exists(path):
                with open(path) as f:
                    return json.load(f)
        return {}

    def _load_safe_ranges(self) -> dict:
        path = os.path.join(DATA_DIR, "param_safe_ranges.json")
        if os.path.exists(path):
            with open(path) as f:
                return json.load(f)
        return {}

    def _check_combo(self, conditions: dict, params: dict[str, float]) -> bool:
        """
        Each condition is (operator, value) or (operator, other_param_name).
        Operators: ">", "<", ">=", "<=", "=="
        """
        for pname, (op, rhs) in conditions.items():
            lhs = params.get(pname)
            if lhs is None:
                return False
            # rhs may be a param name (string) for cross-param comparisons
            if isinstance(rhs, str) and rhs in params:
                rhs_val = params[rhs]
            elif isinstance(rhs, str):
                return False
            else:
                rhs_val = rhs

            if op == ">"  and not (lhs >  rhs_val):
                return False
            if op == "<"  and not (lhs <  rhs_val):
                return False
            if op == ">=" and not (lhs >= rhs_val):
                return False
            if op == "<=" and not (lhs <= rhs_val):
                return False
            if op == "==" and not (lhs == rhs_val):
                return False

        return True
