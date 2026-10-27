"""
PowerAnalyser: the flight controller's own supply while armed.

  system_power  PX4: voltage5v_v, usb_connected, periph_5v_oc, hipower_5v_oc
                ArduPilot POWR / MAVLink POWER_STATUS: voltage5v_v (Vcc),
                servo_rail_v, power_flags (MAV_POWER_STATUS bits)

Board voltage outside 4.3-5.8 V is what ArduPilot's own arming check
refuses; a dip under load is the classic brown-out warning sign. Weight 0:
the findings show up, the score doesn't move, since most logs don't carry
this topic and its absence says nothing about the flight.
"""

import numpy as np

from flightmd_core.analysers.base import BaseAnalyser
from flightmd_core.analysers.helpers import confidence, downsample, find_runs, when
from flightmd_core.analysers.phases import flight_phases
from flightmd_core.models.findings import AnalyserResult, Category, Finding, Severity

VCC_MIN = 4.3
VCC_MAX = 5.8

# MAV_POWER_STATUS
USB_CONNECTED = 4
PERIPH_OVERCURRENT = 8
PERIPH_HIPOWER_OVERCURRENT = 16


class PowerAnalyser(BaseAnalyser):
    name            = "power"
    display_name    = "Board Power"
    weight          = 0.0
    required_topics = ["system_power"]
    required_columns = {"system_power": ["timestamp"]}

    def analyse(self, topics, params):
        df = topics["system_power"].dropna(subset=["timestamp"]).sort_values("timestamp")
        phases = flight_phases(topics)
        d = df[phases.mask(df["timestamp"].to_numpy(float), "armed")]
        if len(d) < 2:
            return self._skip(f"No board power samples {phases.describe('armed')}.")

        ts = d["timestamp"].to_numpy(float)
        flags = d["power_flags"].fillna(0).astype(np.int64).to_numpy() if "power_flags" in d.columns else None
        usb = np.zeros(len(d), dtype=bool)
        if "usb_connected" in d.columns:
            usb |= d["usb_connected"].fillna(0).to_numpy(float) > 0
        if flags is not None:
            usb |= (flags & USB_CONNECTED) != 0

        findings: list[Finding] = []
        health_score = 100.0
        key_metrics: dict[str, float] = {}

        if "voltage5v_v" in d.columns:
            v = d["voltage5v_v"].to_numpy(float)
            # USB-powered bench time reads low and means nothing
            ok = np.isfinite(v) & (v > 0) & ~usb
            if ok.sum() >= 2:
                lo, hi = float(np.min(v[ok])), float(np.max(v[ok]))
                key_metrics.update(min_vcc_v=round(lo, 3), vcc_range_v=round(hi - lo, 3))
                bad = ok & ((v < VCC_MIN) | (v > VCC_MAX))
                if bad.any():
                    runs = find_runs(bad)
                    low = lo < VCC_MIN
                    health_score -= 30
                    tech = (
                        f"Flight controller supply {'fell to' if low else 'rose to'} "
                        f"{lo if low else hi:.2f} V while armed (allowed {VCC_MIN}-{VCC_MAX} V); "
                        f"{int(bad.sum())} samples in {len(runs)} episode(s). Range {lo:.2f}-{hi:.2f} V."
                    )
                    t_ms, vs = downsample(ts, v)
                    findings.append(Finding(
                        category=Category.SYSTEM,
                        severity=Severity.CRITICAL,
                        kind="power.vcc_out_of_range",
                        title=f"Board Voltage {'Low' if low else 'High'} ({lo if low else hi:.2f} V)",
                        technical_summary=tech,
                        plain_english=tech,
                        recommendation=(
                            "Check the power module and its cable, and move servos, LEDs and other loads "
                            "off the flight controller's supply; a brown-out reboots the autopilot in the air."
                        ),
                        confidence=confidence((VCC_MIN - lo) / 0.3 if low else (hi - VCC_MAX) / 0.3),
                        chart_data={"timestamps": t_ms, "vcc": vs, "min": VCC_MIN, "max": VCC_MAX},
                        **when(ts[runs[0][0]], ts[min(runs[-1][1], len(ts) - 1)]),
                    ))

        # todo: servo_rail_v dips too, once there's a documented threshold for it
        oc = np.zeros(len(d), dtype=bool)
        oc_cols = [c for c in ("periph_5v_oc", "hipower_5v_oc") if c in d.columns]
        for c in oc_cols:
            oc |= d[c].fillna(0).to_numpy(float) > 0
        if flags is not None:
            oc |= (flags & (PERIPH_OVERCURRENT | PERIPH_HIPOWER_OVERCURRENT)) != 0
        if oc.any():
            runs = find_runs(oc)
            health_score -= 15
            tech = (
                f"Peripheral supply over-current flagged in {int(oc.sum())} armed samples "
                f"({len(runs)} episode(s))."
            )
            findings.append(Finding(
                category=Category.SYSTEM,
                severity=Severity.WARNING,
                kind="power.overcurrent",
                title="Peripheral Supply Over-Current",
                technical_summary=tech,
                plain_english=tech,
                recommendation="Something on the flight controller's peripheral ports draws too much current: check telemetry radios, GPS, cameras and LEDs, and power heavy loads separately.",
                confidence=confidence(len(runs) / 3.0),
                **when(ts[runs[0][0]], ts[min(runs[-1][1], len(ts) - 1)]),
            ))

        if not key_metrics and not oc_cols and flags is None:
            return self._skip("system_power has no voltage or fault fields.")
        return AnalyserResult(
            analyser=self.name,
            display_name=self.display_name,
            findings=findings,
            health_score=max(0.0, health_score),
            key_metrics=key_metrics,
        )
