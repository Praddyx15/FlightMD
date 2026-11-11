"""
ParameterAnalyser: parameters outside their allowed or recommended range,
and dangerous combinations, for PX4 and ArduPilot. Works from the params
dict, not from topics.

Two ranges per parameter:
  firmware-allowed  min/max from the autopilot's own metadata, in
                    data/param_tables/ (scripts/gen_param_tables.py), the
                    table closest to the log's firmware version
  recommended       data/param_safe_ranges.json, hand-picked and only where
                    it's tighter than the firmware's (each entry says why)

The firmware default is the suggested value when it sits inside both;
ArduPilot's metadata has no defaults, so there it's the nearest bound.

There's no "deprecated parameter" check: a log carries exactly the
parameters its firmware knows, so a name in a log is never stale.

Autopilots store params as float32, so 0.05 arrives as 0.05000000074505806.
Values are rounded back to their float32 decimal form before comparing or
showing them; otherwise every gain that sits exactly on a bound reads as
"above range".
"""

import json
import math
import numbers
import os
import re
from functools import lru_cache
from typing import Optional

import numpy as np

from flightmd_core.analysers.base import BaseAnalyser
from flightmd_core.analysers.vehicle import vehicle_from_params
from flightmd_core.models.findings import (
    AnalyserResult, Finding, ParamRecommendation, Severity, Category
)

# each condition is (param, op, number or other param); "fix" is
# (param, direction) for the change sheet, suggested value = firmware default
DANGEROUS_COMBOS = [
    {
        "autopilot": "px4",
        "kind": "params.rate_p_high_d_low",
        "when": [("MC_ROLLRATE_P", ">", 0.3), ("MC_ROLLRATE_D", "<", 0.001)],
        "severity": Severity.WARNING,
        "title": "Oscillation Risk: High Rate P + Low Rate D",
        "reason": "MC_ROLLRATE_P > 0.3 with MC_ROLLRATE_D < 0.001 is likely to cause roll oscillation.",
        "fix": ("MC_ROLLRATE_D", "increase"),
    },
    {
        "autopilot": "px4",
        "kind": "params.rate_p_high_d_low",
        "when": [("MC_PITCHRATE_P", ">", 0.3), ("MC_PITCHRATE_D", "<", 0.001)],
        "severity": Severity.WARNING,
        "title": "Oscillation Risk: High Pitch P + Low Pitch D",
        "reason": "MC_PITCHRATE_P > 0.3 with MC_PITCHRATE_D < 0.001 is likely to cause pitch oscillation.",
        "fix": ("MC_PITCHRATE_D", "increase"),
    },
    {
        "autopilot": "px4",
        "kind": "params.pos_loop_risk",
        "when": [("MPC_XY_P", ">", 1.5), ("MPC_XY_VEL_P_ACC", "<", 1.5)],
        "severity": Severity.WARNING,
        "title": "Position Loop Instability Risk",
        "reason": "MPC_XY_P > 1.5 with MPC_XY_VEL_P_ACC < 1.5 may cause position loop oscillation.",
        "fix": ("MPC_XY_P", "decrease"),
    },
    {
        "autopilot": "px4",
        "kind": "params.bat_thr_inverted",
        "when": [("BAT_LOW_THR", "<", "BAT_CRIT_THR")],
        "severity": Severity.CRITICAL,
        "title": "Battery Thresholds Inverted",
        "reason": "BAT_LOW_THR must be greater than BAT_CRIT_THR (e.g. low=0.15, critical=0.07).",
        "fix": ("BAT_LOW_THR", "increase"),
    },
    {
        "autopilot": "px4",
        "kind": "params.rc_loss_short",
        "when": [("COM_RC_LOSS_T", "<", 0.5)],
        "severity": Severity.WARNING,
        "title": "Very Short RC Loss Timeout",
        "reason": "COM_RC_LOSS_T < 0.5s may trigger unintended failsafe on brief signal glitches.",
        "fix": ("COM_RC_LOSS_T", "increase"),
    },
    # 0 switches each ArduPilot battery failsafe off, so only compare set ones
    {
        "autopilot": "ardupilot",
        "kind": "params.bat_thr_inverted",
        "when": [("BATT_LOW_VOLT", ">", 0), ("BATT_CRT_VOLT", ">", 0), ("BATT_LOW_VOLT", "<=", "BATT_CRT_VOLT")],
        "severity": Severity.CRITICAL,
        "title": "Battery Voltage Failsafes Inverted",
        "reason": "BATT_LOW_VOLT must be higher than BATT_CRT_VOLT, or the critical failsafe fires first.",
        "fix": None,
    },
    {
        "autopilot": "ardupilot",
        "kind": "params.bat_thr_inverted",
        "when": [("BATT_LOW_MAH", ">", 0), ("BATT_CRT_MAH", ">", 0), ("BATT_LOW_MAH", "<=", "BATT_CRT_MAH")],
        "severity": Severity.CRITICAL,
        "title": "Battery Capacity Failsafes Inverted",
        "reason": "BATT_LOW_MAH must be higher than BATT_CRT_MAH (both are remaining capacity).",
        "fix": None,
    },
    {
        "autopilot": "ardupilot",
        "kind": "params.arming_checks_off",
        "when": [("ARMING_CHECK", "==", 0)],
        "severity": Severity.WARNING,
        "title": "Pre-Arm Checks Disabled",
        "reason": "ARMING_CHECK = 0 turns off every pre-arm safety check.",
        "fix": None,
    },
]

# multicopter-only params; meaningless on a plane or rover
_MC_PREFIXES = ("MC_", "MPC_")

# units the text reads better without
_QUIET_UNITS = {"norm", "%/100"}

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
TABLE_DIR = os.path.join(DATA_DIR, "param_tables")

_VERSION = re.compile(r"(\d+)\.(\d+)")
_AP_VEHICLE = {"multirotor": "copter", "fixed_wing": "plane", "vtol": "plane", "rover": "rover"}


def f32(v: float) -> float:
    """The decimal the autopilot actually stores: float32, shortest repr.
    Whole numbers are left alone: INT32 params past 2^24 (coordinates, IP
    addresses) would get rounded."""
    if float(v).is_integer():
        return float(v)
    return float(str(np.float32(v)))


@lru_cache(maxsize=1)
def load_safe_ranges() -> dict:
    """{"px4": {name: {min, max, unit, why}}, "ardupilot": {...}}"""
    with open(os.path.join(DATA_DIR, "param_safe_ranges.json"), encoding="utf-8") as f:
        data = json.load(f)
    return {k: v for k, v in data.items() if not k.startswith("_")}


@lru_cache(maxsize=1)
def load_tables() -> list[dict]:
    tables = []
    for name in sorted(os.listdir(TABLE_DIR)):
        if not name.endswith(".json"):
            continue
        with open(os.path.join(TABLE_DIR, name), encoding="utf-8") as f:
            t = json.load(f)
        t["series"] = tuple(int(x) for x in t["version"].split(".")[:2])
        tables.append(t)
    return tables


def firmware_series(metadata, autopilot: str) -> Optional[tuple[int, int]]:
    if metadata is None:
        return None
    fields = ["px4_version", "firmware_version"] if autopilot == "px4" else ["firmware_version"]
    for field in fields:
        m = _VERSION.search(getattr(metadata, field, None) or "")
        if m and int(m.group(1)) > 0:
            return int(m.group(1)), int(m.group(2))
    return None


def ap_vehicle(metadata, frame: str) -> Optional[str]:
    vt = (getattr(metadata, "vehicle_type", None) or "").lower()
    if vt in ("copter", "plane", "rover"):
        return vt
    return _AP_VEHICLE.get(frame)


def pick_table(autopilot: str, vehicle: Optional[str], series) -> tuple[dict, str]:
    """(params table, which one in words). The table nearest the firmware
    version; with no version, every table of that autopilot merged with the
    widest ranges, so a value valid in any release isn't flagged."""
    # print([t["version"] for t in load_tables()])
    cands = [t for t in load_tables() if t["autopilot"] == autopilot
             and (autopilot != "ardupilot" or vehicle is None or t["vehicle"] == vehicle)]
    if not cands:
        return {}, ""
    name = "PX4" if autopilot == "px4" else f"Ardu{(vehicle or 'Pilot').capitalize()}"
    # ArduPilot without a known vehicle merges too: Copter and Plane ranges differ
    if series is not None and (autopilot == "px4" or vehicle is not None):
        best = min(cands, key=lambda t: (abs(t["series"][0] - series[0]) * 100
                                         + abs(t["series"][1] - series[1]), -t["series"][1]))
        return best["params"], f"{name} {'.'.join(map(str, best['series']))} metadata"

    merged: dict[str, dict] = {}
    for t in sorted(cands, key=lambda t: t["series"]):
        for p, e in t["params"].items():
            m = merged.setdefault(p, {})
            m.update({k: v for k, v in e.items() if k not in ("min", "max")})
            if "min" in e:
                m["min"] = min(m.get("min", e["min"]), e["min"])
            if "max" in e:
                m["max"] = max(m.get("max", e["max"]), e["max"])
    return merged, f"{name} metadata, widest range across releases"


class ParameterAnalyser(BaseAnalyser):
    name            = "parameters"
    display_name    = "Parameter Analysis"
    required_topics = []
    weight          = 5.0

    def is_applicable(self, available_topics: set[str]) -> bool:
        return True     # works off params, which every format has

    def analyse(self, topics, params):
        if not params:
            return self._skip("No parameters found in log.")

        vehicle = vehicle_from_params(params)
        # a trimmed set with no tell-tale names; every check is by exact
        # name, so PX4's tables only ever match PX4 parameters anyway
        autopilot = "px4" if vehicle.autopilot == "unknown" else vehicle.autopilot

        values = {k: f32(float(v)) for k, v in params.items()
                  if isinstance(v, numbers.Real) and math.isfinite(v)}
        skip_mc = autopilot == "px4" and vehicle.frame in ("fixed_wing", "rover")
        series = firmware_series(self.metadata, autopilot)
        table, source = pick_table(autopilot, ap_vehicle(self.metadata, vehicle.frame), series)
        safe = load_safe_ranges().get(autopilot, {})

        findings: list[Finding] = []
        health_score = 100.0

        for pname, pval in values.items():
            if skip_mc and pname.startswith(_MC_PREFIXES):
                continue
            fw = table.get(pname, {})
            if fw.get("read_only"):
                continue
            f = self._range_check(pname, pval, fw, safe.get(pname, {}), source)
            if f is not None:
                health_score -= 30.0 if f.severity == Severity.CRITICAL else 15.0
                findings.append(f)

        for combo in DANGEROUS_COMBOS:
            if combo["autopilot"] != autopilot:
                continue
            if skip_mc and any(p.startswith(_MC_PREFIXES) for p, _, _ in combo["when"]):
                continue
            if not self._check_combo(combo["when"], values):
                continue
            health_score -= 30.0 if combo["severity"] == Severity.CRITICAL else 15.0
            involved = []
            for p, _, rhs in combo["when"]:
                involved.append(p)
                if isinstance(rhs, str):
                    involved.append(rhs)
            involved = list(dict.fromkeys(involved))
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
                params=involved,
                param_changes=self._combo_fix(combo, values, table),
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

    def _range_check(self, pname, pval, fw, rec, source):
        fw_min, fw_max = fw.get("min"), fw.get("max")
        rec_min, rec_max = rec.get("min"), rec.get("max")
        unit = fw.get("unit") or rec.get("unit")

        # the firmware's limit is the harder fact, so it's reported first
        if fw_min is not None and pval < fw_min:
            bound, word, kind = fw_min, "below", "firmware"
        elif fw_max is not None and pval > fw_max:
            bound, word, kind = fw_max, "above", "firmware"
        elif rec_min is not None and pval < rec_min:
            bound, word, kind = rec_min, "below", "recommended"
        elif rec_max is not None and pval > rec_max:
            bound, word, kind = rec_max, "above", "recommended"
        else:
            return None

        lo = max((b for b in (fw_min, rec_min) if b is not None), default=None)
        hi = min((b for b in (fw_max, rec_max) if b is not None), default=None)
        u = f" {unit}" if unit and unit not in _QUIET_UNITS else ""

        # how far outside, relative to the width of the usable range
        if lo is not None and hi is not None and hi > lo:
            scale = hi - lo
        else:
            scale = max(abs(bound), 1.0)
        far = abs(pval - bound) / scale > 0.5
        negative_gain = pval < 0 <= (lo if lo is not None else 0)
        sev = Severity.CRITICAL if far or negative_gain else Severity.WARNING

        # firmware default if it's inside the usable range, else the nearest edge
        suggested = fw.get("default")
        if suggested is None or (lo is not None and suggested < lo) or (hi is not None and suggested > hi):
            suggested = lo if word == "below" else hi
        suggested = f32(suggested)

        limit = "minimum" if word == "below" else "maximum"
        what = f"the firmware's allowed {limit}" if kind == "firmware" else f"the recommended {limit}"
        span = f"{lo:g} to {hi:g}{u}" if lo is not None and hi is not None else f"{limit} {bound:g}{u}"
        tech = f"{pname} = {pval:g} is {word} {what} of {bound:g}{u}"
        if source and kind == "firmware":
            tech += f" ({source})"
        tech += "."
        if kind == "recommended" and rec.get("why"):
            tech += f" {rec['why']}"
        reboot = " Takes effect after a reboot." if fw.get("reboot_required") else ""
        return Finding(
            category=Category.PARAMETERS,
            severity=sev,
            kind="params.below_range" if word == "below" else "params.above_range",
            title=f"Parameter {word.capitalize()} Safe Range: {pname}",
            technical_summary=tech,
            plain_english=tech,
            recommendation=f"Set {pname} to {suggested:g}{u} (usable range {span}).{reboot}",
            confidence=0.9 if kind == "firmware" else 0.8,
            param_changes=[ParamRecommendation(
                param_name=pname,
                current_value=pval,
                suggested_value=suggested,
                unit=unit,
                change_direction="increase" if word == "below" else "decrease",
                reason=f"{pname} is {word} {what} of {bound:g}{u}.",
            )],
        )

    def _combo_fix(self, combo, values, table) -> list[ParamRecommendation]:
        if not combo["fix"]:
            return []
        pname, direction = combo["fix"]
        cur = values.get(pname)
        target = table.get(pname, {}).get("default")
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

    def _check_combo(self, conditions, params: dict[str, float]) -> bool:
        """Each condition is (param, op, number) or (param, op, other_param)."""
        for pname, op, rhs in conditions:
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
