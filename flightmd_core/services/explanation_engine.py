"""
Deterministic plain-English text for findings, and the executive summary.

Templates are keyed by Finding.kind, which the analyser sets; titles are
display text and are never parsed. The analyser's own recommendation
carries the real numbers (which parameter, from what to what), so it is
kept; a template recommendation only fills in when the analyser left it
empty.
"""

from typing import Optional

from flightmd_core.models.findings import AnalyserResult, Finding, Category, Severity
from flightmd_core.models.metadata import FlightMetadata
from flightmd_core.services.score_calculator import NOT_ASSESSED_LABEL

# kind -> (plain English, fallback recommendation)
TEMPLATES: dict[str, tuple[str, str]] = {
    "oscillation.rate_p": (
        "The aircraft kept wobbling at a steady low frequency on this axis. That pattern usually "
        "means the rate controller's P gain is too high for this airframe, so it overcorrects "
        "back and forth.",
        "Lower the rate P gain for this axis by 10-15% and re-test.",
    ),
    "oscillation.rate_d": (
        "There is a sustained oscillation in the 12-35 Hz range on this axis. That band is usually "
        "the D term amplifying motor and frame noise, so raising D would make it worse.",
        "Lower the rate D gain for this axis by about 15%, or lower the D-term filter cutoff.",
    ),
    "oscillation.mechanical": (
        "There is a high-frequency oscillation on this axis, above where the rate controller "
        "normally oscillates. That is typically mechanical: props, motors or a resonant frame part.",
        "Check props, motor mounts and the flight controller mounting before changing gains.",
    ),
    "vibration.critical": (
        "Vibration levels on the flight controller are extremely high, exceeding critical safety limits. "
        "Severe vibration can saturate internal sensors and cause EKF estimation failures or flyaways.",
        "Do not fly. Inspect propellers for balance or damage. Check all motor bell screws and ensure "
        "the frame arms and flight controller mounts are tight.",
    ),
    "vibration.elevated": (
        "Vibration levels are higher than normal. Elevated vibration adds noise to the attitude "
        "estimate and can degrade position hold.",
        "Balance propellers using a prop balancer. Inspect motor mounts and check whether the flight "
        "controller's damping mount is worn.",
    ),
    "vibration.clipping": (
        "The accelerometer saturated: it hit the end of its measuring range, so the autopilot lost "
        "real acceleration data for those moments.",
        "Check for a loose propeller, bent motor shaft, or motor bell. Ensure the flight controller "
        "is securely mounted on vibration-damping foam.",
    ),
    "vibration.imu_mismatch": (
        "The redundant IMUs measured clearly different vibration levels, which points at mounting, "
        "isolation, or a problem inside one sensor.",
        "Inspect the flight controller mounting. Verify that one side is not touching the frame "
        "directly or pinched by wires, bypassing the damping.",
    ),
    "vibration.imu_errors": (
        "The IMU driver reported read errors during the flight. A few are harmless; a steady stream "
        "means the sensor or its connection is unreliable.",
        "Watch whether the count grows from flight to flight; check the flight controller's connectors "
        "and replace the board if it keeps rising.",
    ),
    "motors.rpm_imbalance": (
        "At hover, one motor had to spin noticeably faster or slower than the others to keep the "
        "aircraft level. That points at that motor, its prop, its arm, or an off-centre load.",
        "Inspect the motor furthest from the average: prop, bearings, arm alignment; then check the "
        "centre of gravity.",
    ),
    "motors.current_imbalance": (
        "At hover, one motor drew clearly more current than the others. Extra drag in that motor "
        "or a damaged prop makes it work harder for the same thrust.",
        "Inspect that motor for mechanical drag, binding, or stator damage, and its propeller for cracks.",
    ),
    "motors.esc_thermal": (
        "The electronic speed controller (ESC) temperature exceeded safe operating limits, "
        "risking thermal shutdown or permanent hardware failure.",
        "Check motor loading, reduce payload weight, or improve airflow/cooling around the ESCs.",
    ),
    "motors.dropout": (
        "One motor stopped (or nearly stopped) in flight while the others kept spinning. That can "
        "cause a sudden loss of control.",
        "Check ESC signal wiring, power connectors, and the logs for desync events or propeller slips.",
    ),
    "gps.no_fix": (
        "The GPS never reached a 3D fix during the flight, so every GPS-assisted mode was unavailable.",
        "Wait for a 3D fix before arming, and check the antenna, cable and sky view.",
    ),
    "gps.fix_lost": (
        "The GPS receiver completely lost its 3D position fix during flight, forcing the autopilot "
        "to fall back to non-GPS modes or a failsafe.",
        "Ensure clear sky view. Check GPS antenna connection and inspect for RF interference from "
        "onboard electronics (cameras, transmitters).",
    ),
    "gps.fix_degraded": (
        "The GPS fix degraded briefly during flight, which can cause position drift or toilet-bowling.",
        "Check for GPS antenna shading or local RF interference sources such as cameras or "
        "telemetry transmitters.",
    ),
    "gps.sat_drop": (
        "The number of tracked GPS satellites dropped rapidly, indicating antenna obstruction "
        "or RF interference.",
        "Inspect the GPS receiver mounting and check for shielding/separation from RF-noisy components.",
    ),
    "gps.hdop": (
        "The GPS dilution of precision (HDOP) stayed high, meaning satellite geometry or signal "
        "quality was poor and position accuracy was reduced.",
        "Avoid flying near tall structures or in poor weather. Check GPS signal health.",
    ),
    "gps.jamming": (
        "The receiver reported radio interference in the GPS band for a sustained period, "
        "consistent with jamming or strong onboard RF noise.",
        "Relocate the GPS antenna away from onboard transmitters, cameras and processors. Use shielding.",
    ),
    "gps.spoofing": (
        "The GPS receiver flagged possible spoofing: signals that look like GPS but don't behave like it.",
        "Don't rely on GPS-guided flight modes in the affected area.",
    ),
    "ekf.innovation_rejected": (
        "The Extended Kalman Filter (EKF) rejected measurements from a sensor because they "
        "disagreed too much with its own estimate.",
        "Check the calibration and mounting of the sensor named in the finding.",
    ),
    "ekf.solution_invalid": (
        "The EKF marked part of its navigation solution invalid while armed, so the autopilot "
        "could not trust that estimate.",
        "Do not fly in modes that need this estimate until the cause is found. Recalibrate sensors "
        "and inspect hardware.",
    ),
    "ekf.gps_glitch": (
        "The EKF saw the GPS position jump away from where the vehicle actually was, and stopped "
        "trusting it for a while.",
        "Check for multipath near structures and GPS interference.",
    ),
    "ekf.accel_error": (
        "The EKF flagged the accelerometer data as bad, usually from clipping under heavy vibration. "
        "Height and position estimates can fail when this happens.",
        "Check props, motor mounts and flight-controller damping before flying again.",
    ),
    "ekf.innovation_ratio": (
        "An EKF innovation test ratio went above 1, meaning a sensor's readings were rejected "
        "as inconsistent with the filter's estimate.",
        "Check for vibration issues or magnetic disturbances affecting the sensors.",
    ),
    "ekf.innovation_ratio_high": (
        "An EKF test ratio stayed close to the point where the filter starts rejecting that sensor. "
        "It still trusted the sensor, but with little margin left.",
        "Check the calibration and mounting of that sensor before it gets worse.",
    ),
    "ekf.filter_fault": (
        "ArduPilot's EKF flagged a fault in its own state or in a sensor it was fusing.",
        "Check the sensor named in the finding; for a NaN fault, don't fly again until the cause is found.",
    ),
    "ekf.sensor_timeout": (
        "The EKF stopped getting usable measurements from a sensor for a while during flight, so it "
        "was estimating without it.",
        "Check that sensor's wiring and health, and whether something blocked it (GPS shading, a "
        "magnetometer swamped by current).",
    ),
    "ekf.wind_jump": (
        "The EKF wind estimate jumped suddenly, which usually follows a sensor anomaly rather than "
        "a real gust.",
        "Check airspeed sensor calibration (if equipped) and GPS quality around that time.",
    ),
    "battery.thermal": (
        "The battery temperature exceeded safe operating limits during flight, which accelerates cell "
        "degradation and poses a thermal runaway risk.",
        "Allow the battery to cool down. Reduce payload weight or aggressive manoeuvres to lower current draw.",
    ),
    "battery.c_rate": (
        "The battery current draw exceeded a sensible continuous C-rate for its rated capacity, "
        "stressing the cells.",
        "Use a higher C-rate battery or reduce the aircraft's weight and power draw.",
    ),
    "battery.sag": (
        "The battery voltage dropped more than it should under load, measured from how the voltage "
        "responds to changes in current. That means high internal resistance: an ageing pack, a weak "
        "cell or a bad connection.",
        "Measure the pack's internal resistance on a charger and check connectors.",
    ),
    "battery.capacity_fade": (
        "The battery delivered noticeably less than its rated capacity, indicating cell aging or damage.",
        "Cycle the battery to calibrate, and replace the pack if capacity remains low.",
    ),
    "params.deprecated": (
        "A parameter in the configuration no longer exists in this firmware version and has no effect.",
        "Remove this parameter from your saved parameter file to prevent confusion.",
    ),
    "params.below_range": (
        "A parameter is set below its recommended minimum value, which could cause unstable flight "
        "or safety issues.",
        "Increase the parameter value to within the safe range.",
    ),
    "params.above_range": (
        "A parameter is set above its recommended maximum value, which could cause overshoot, "
        "oscillation, or damage.",
        "Reduce the parameter value to within the safe range.",
    ),
    "params.bat_thr_inverted": (
        "The battery low warning threshold is set lower than the critical threshold, so the "
        "failsafe steps fire in the wrong order.",
        "Set BAT_LOW_THR above BAT_CRIT_THR.",
    ),
    "params.rc_loss_short": (
        "The RC loss timeout is very short, so a brief signal glitch can trigger the failsafe.",
        "Set COM_RC_LOSS_T to 0.5 s or more.",
    ),
    "params.rate_p_high_d_low": (
        "The rate controller P gain is high while its D gain is very low, a combination that "
        "tends to oscillate.",
        "Lower the P gain or raise the D gain towards the firmware default.",
    ),
    "params.arming_checks_off": (
        "Pre-arm safety checks are turned off, so the vehicle will arm with problems it would "
        "normally refuse to fly with.",
        "Set ARMING_CHECK back to 1 (all checks) and fix whatever check was failing instead.",
    ),
    "power.vcc_out_of_range": (
        "The flight controller's own supply voltage left the safe band while armed. A deep dip can "
        "reboot the autopilot in the air.",
        "Check the power module and its cable, and take servos and LEDs off the flight controller's supply.",
    ),
    "power.overcurrent": (
        "A device on the flight controller's peripheral ports drew more current than the port allows.",
        "Find the device drawing too much (radio, GPS, camera, LEDs) and power it separately.",
    ),
    "params.pos_loop_risk": (
        "The position loop P gain is high relative to the velocity loop, which may cause position "
        "overshoot and oscillation.",
        "Lower MPC_XY_P or raise MPC_XY_VEL_P_ACC.",
    ),
}

CATEGORY_FALLBACK = {
    Category.OSCILLATION: "Check rate controller tuning for this axis.",
    Category.VIBRATION: "Check physical frame rigidity, motor mounts, and prop balancing.",
    Category.MOTORS: "Inspect motor and ESC connections and check logs for error flags.",
    Category.GPS: "Ensure clear view of sky and minimal RF interference.",
    Category.EKF: "Verify sensor calibration and check for vibration or magnetic interference.",
    Category.BATTERY: "Inspect battery connections, age, and cell balance.",
    Category.PARAMETERS: "Verify the parameter values against safe default ranges.",
    Category.SYSTEM: "Check the flight controller's power and wiring.",
}
DEFAULT_RECOMMENDATION = "Consult the log details or the autopilot's documentation for troubleshooting."


class ExplanationEngine:
    def __init__(self, *args, **kwargs):
        # takes and ignores the old API-key arguments
        self.token_usage = {"input_tokens": 0, "output_tokens": 0}

    async def explain_findings(self, findings: list[Finding]) -> list[Finding]:
        for f in findings:
            self._explain(f)
        return findings

    def _explain(self, f: Finding) -> None:
        plain, rec = TEMPLATES.get(f.kind or "", (None, None))
        f.plain_english = plain or f.technical_summary
        if not f.recommendation or f.recommendation == f.technical_summary:
            f.recommendation = rec or CATEGORY_FALLBACK.get(f.category, DEFAULT_RECOMMENDATION)

    async def generate_summary(
        self,
        metadata: FlightMetadata,
        findings: list[Finding],
        overall_score: float,
        score_label: str,
        results: Optional[list[AnalyserResult]] = None,
    ) -> str:
        """2-3 sentence summary. Pass results to have it name the modules
        that couldn't be assessed."""
        unassessed = [r.display_name for r in results or [] if not r.assessed]

        if score_label == NOT_ASSESSED_LABEL:
            return (
                "No health score: none of the analysis modules found data they could assess in "
                "this log, so this is not a clean bill of health. Check that the file is a full "
                "flight log with telemetry, not a parameter file or a short bench capture."
            )

        parts = [
            f"Flight health score is {overall_score:.0f}/100 ({score_label}) based on "
            f"{metadata.duration_seconds:.0f}s of log data."
        ]
        criticals = [f for f in findings if f.severity == Severity.CRITICAL]
        warnings = [f for f in findings if f.severity == Severity.WARNING]
        if criticals:
            parts.append(
                f"CRITICAL issue(s) detected: {', '.join(f.title for f in criticals)}. "
                f"Action is required to ensure flight safety."
            )
        elif warnings:
            parts.append(
                f"Warning(s) detected: {', '.join(f.title for f in warnings)}. "
                f"Review the recommendations to optimize performance and reliability."
            )
        elif findings:
            parts.append(f"{len(findings)} minor note(s); no warnings or critical issues.")
        else:
            parts.append("No anomalies detected in the checks that could run.")

        if unassessed:
            parts.append(f"Not assessed (no usable data): {', '.join(unassessed)}.")
        return " ".join(parts)
