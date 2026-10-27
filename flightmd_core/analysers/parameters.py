"""
ParameterAnalyser: PX4 parameters outside safe ranges, dangerous
combinations, and parameters that no longer exist. Works from the params
dict, not from topics.

Autopilots store params as float32, so 0.05 arrives as 0.05000000074505806.
Values are rounded back to their float32 decimal form before comparing or
showing them; otherwise every gain that sits exactly on a bound reads as
"above range".
"""

import json
import math
import numbers
import os
from functools import lru_cache

import numpy as np

from flightmd_core.analysers.base import BaseAnalyser
from flightmd_core.analysers.vehicle import vehicle_from_params
from flightmd_core.models.findings import (
    AnalyserResult, Finding, ParamRecommendation, Severity, Category
)

# Removed from PX4 and ignored if still set. MC_ACRO_EXPO*, EKF2_MAG_DECL
# and LND_FLIGHT_T_* are all live in v1.14 (LND_FLIGHT_T_* is the flight
# time counter), so they don't belong here.
DEPRECATED_PARAMS = {"MPC_VELD_LP"}

# cross-param rhs is a param name; "fix" is (param, direction) for the
# change sheet, with the suggested value taken from the PX4 defaults
DANGEROUS_COMBOS = [
    {
        "kind": "params.rate_p_high_d_low",
        "params": {"MC_ROLLRATE_P": (">", 0.3), "MC_ROLLRATE_D": ("<", 0.001)},
        "severity": Severity.WARNING,
        "title": "Oscillation Risk: High Rate P + Low Rate D",
        "reason": "MC_ROLLRATE_P > 0.3 with MC_ROLLRATE_D < 0.001 is likely to cause roll oscillation.",
        "fix": ("MC_ROLLRATE_D", "increase"),
    },
    {
        "kind": "params.rate_p_high_d_low",
        "params": {"MC_PITCHRATE_P": (">", 0.3), "MC_PITCHRATE_D": ("<", 0.001)},
        "severity": Severity.WARNING,
        "title": "Oscillation Risk: High Pitch P + Low Pitch D",
        "reason": "MC_PITCHRATE_P > 0.3 with MC_PITCHRATE_D < 0.001 is likely to cause pitch oscillation.",
        "fix": ("MC_PITCHRATE_D", "increase"),
    },
    {
        "kind": "params.pos_loop_risk",
        "params": {"MPC_XY_P": (">", 1.5), "MPC_XY_VEL_P_ACC": ("<", 1.5)},
        "severity": Severity.WARNING,
        "title": "Position Loop Instability Risk",
        "reason": "MPC_XY_P > 1.5 with MPC_XY_VEL_P_ACC < 1.5 may cause position loop oscillation.",
        "fix": ("MPC_XY_P", "decrease"),
    },
    {
        "kind": "params.bat_thr_inverted",
        "params": {"BAT_LOW_THR": ("<", "BAT_CRIT_THR")},
        "severity": Severity.CRITICAL,
        "title": "Battery Thresholds Inverted",
        "reason": "BAT_LOW_THR must be greater than BAT_CRIT_THR (e.g. low=0.15, critical=0.07).",
        "fix": ("BAT_LOW_THR", "increase"),
    },
    {
        "kind": "params.rc_loss_short",
        "params": {"COM_RC_LOSS_T": ("<", 0.5)},
        "severity": Severity.WARNING,
        "title": "Very Short RC Loss Timeout",
        "reason": "COM_RC_LOSS_T < 0.5s may trigger unintended failsafe on brief signal glitches.",
        "fix": ("COM_RC_LOSS_T", "increase"),
    },
]

# multicopter-only params; meaningless on a plane or rover
_MC_PREFIXES = ("MC_", "MPC_")

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")


def f32(v: float) -> float:
    """The decimal the autopilot actually stores: float32, shortest repr."""
    return float(str(np.float32(v)))


@lru_cache(maxsize=1)
def load_safe_ranges() -> dict:
    with open(os.path.join(DATA_DIR, "param_safe_ranges.json"), encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def load_defaults() -> dict:
    for name in ("v1_14.json", "v1_13.json"):
        path = os.path.join(DATA_DIR, "px4_param_defaults", name)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                return json.load(f)
    return {}


class ParameterAnalyser(BaseAnalyser):
    name            = "parameters"
    display_name    = "Parameter Analysis"
    required_topics = []

    def is_applicable(self, available_topics: set[str]) -> bool:
        return True     # works off params, which every format has

    def analyse(self, topics, params):
        if not params:
            return self._skip("No parameters found in log.")

        vehicle = vehicle_from_params(params)
        if vehicle.autopilot == "ardupilot":
            # the range table and combos are PX4 names; nothing to check yet
            return self._skip("Parameter checks currently cover PX4 only.")

        values = {k: f32(v) for k, v in params.items()
                  if isinstance(v, numbers.Real) and math.isfinite(v)}
        skip_mc = vehicle.frame in ("fixed_wing", "rover")
        safe_ranges = load_safe_ranges()
        defaults = load_defaults()

        findings: list[Finding] = []
        health_score = 100.0

        for p in sorted(DEPRECATED_PARAMS & values.keys()):
            health_score -= 5
            tech = f"Parameter '{p}' no longer exists in current PX4 releases and has no effect."
            findings.append(Finding(
                category=Category.PARAMETERS,
                severity=Severity.INFO,
                kind="params.deprecated",
                title=f"Deprecated Parameter: {p}",
                technical_summary=tech,
                plain_english=tech,
                recommendation=f"Remove '{p}' from your saved parameter file; the firmware ignores it.",
                confidence=1.0,
            ))

        for pname, pval in values.items():
            sr = safe_ranges.get(pname)
            if sr is None or (skip_mc and pname.startswith(_MC_PREFIXES)):
                continue
            f = self._range_check(pname, pval, sr, defaults)
            if f is not None:
                health_score -= 30.0 if f.severity == Severity.CRITICAL else 15.0
                findings.append(f)

        for combo in DANGEROUS_COMBOS:
            if skip_mc and any(p.startswith(_MC_PREFIXES) for p in combo["params"]):
                continue
            if not self._check_combo(combo["params"], values):
                continue
            health_score -= 30.0 if combo["severity"] == Severity.CRITICAL else 15.0
            involved = []
            for p, (_, rhs) in combo["params"].items():
                involved.append(p)
                if isinstance(rhs, str):
                    involved.append(rhs)
            tech = combo["reason"] + " " + " ".join(f"{p}={values[p]:g}" for p in involved)
            findings.append(Finding(
                category=Category.PARAMETERS,
                severity=combo["severity"],
                kind=combo["kind"],
                title=combo["title"],
                technical_summary=tech,
                plain_english=tech,
                recommendation=combo["reason"],
                confidence=0.95,
                param_changes=self._combo_fix(combo, values, defaults),
            ))

        return AnalyserResult(
            analyser=self.name,
            display_name=self.display_name,
            findings=findings,
            health_score=max(0.0, health_score),
            key_metrics={
                "param_count": float(len(params)),
                "anomaly_count": float(len(findings)),
            },
        )

    def _range_check(self, pname, pval, sr, defaults):
        mn, mx, unit = sr.get("min"), sr.get("max"), sr.get("unit")
        u = f" {unit}" if unit else ""
        if mn is not None and pval < mn:
            bound, direction, word = mn, "increase", "below"
        elif mx is not None and pval > mx:
            bound, direction, word = mx, "decrease", "above"
        else:
            return None

        # how far outside, relative to the width of the safe range
        if mn is not None and mx is not None and mx > mn:
            scale = mx - mn
        else:
            scale = max(abs(bound), 1.0)
        far = abs(pval - bound) / scale > 0.5
        negative_gain = pval < 0 <= (mn if mn is not None else 0)
        sev = Severity.CRITICAL if far or negative_gain else Severity.WARNING

        # firmware default if it's inside the range, else the edge
        suggested = defaults.get(pname)
        if suggested is None or (mn is not None and suggested < mn) or (mx is not None and suggested > mx):
            suggested = bound
        suggested = f32(suggested)

        limit = "minimum" if word == "below" else "maximum"
        span = f"{mn:g} to {mx:g}{u}" if mn is not None and mx is not None else f"{limit} {bound:g}{u}"
        tech = f"{pname} = {pval:g} is {word} the {limit} safe value of {bound:g}{u}."
        return Finding(
            category=Category.PARAMETERS,
            severity=sev,
            kind="params.below_range" if word == "below" else "params.above_range",
            title=f"Parameter {word.capitalize()} Safe Range: {pname}",
            technical_summary=tech,
            plain_english=tech,
            recommendation=f"Set {pname} to {suggested:g}{u} (safe range {span}).",
            confidence=0.9,
            param_changes=[ParamRecommendation(
                param_name=pname,
                current_value=pval,
                suggested_value=suggested,
                unit=unit,
                change_direction=direction,
                reason=f"{pname} is {word} the {limit} safe value of {bound:g}{u}.",
            )],
        )

    def _combo_fix(self, combo, values, defaults) -> list[ParamRecommendation]:
        pname, direction = combo["fix"]
        cur = values.get(pname)
        target = defaults.get(pname)
        if cur is None or target is None:
            return []
        if pname == "BAT_LOW_THR":
            target = max(target, values.get("BAT_CRIT_THR", 0) + 0.05)
        target = f32(target)
        if (direction == "increase" and target <= cur) or (direction == "decrease" and target >= cur):
            return []
        return [ParamRecommendation(
            param_name=pname,
            current_value=cur,
            suggested_value=target,
            change_direction=direction,
            reason=combo["title"],
        )]

    def _check_combo(self, conditions: dict, params: dict[str, float]) -> bool:
        """Each condition is (op, number) or (op, other_param_name)."""
        for pname, (op, rhs) in conditions.items():
            lhs = params.get(pname)
            if lhs is None:
                return False
            if isinstance(rhs, str):
                if rhs not in params:
                    return False
                rhs = params[rhs]
            ok = {
                ">": lhs > rhs, "<": lhs < rhs, ">=": lhs >= rhs,
                "<=": lhs <= rhs, "==": lhs == rhs,
            }[op]
            if not ok:
                return False
        return True
