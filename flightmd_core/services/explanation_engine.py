import logging
from flightmd_core.models.findings import Finding, Category, Severity
from flightmd_core.models.metadata import FlightMetadata

logger = logging.getLogger(__name__)

class ExplanationEngine:
    """
    Deterministic explanation and summary generator for FlightMD.
    Provides plain-English explanations, recommendations, and executive summaries
    without requiring external LLM API calls.
    """

    def __init__(self, *args, **kwargs):
        # Accept and ignore API keys or model names for compatibility
        self.token_usage = {"input_tokens": 0, "output_tokens": 0}

    async def explain_findings(self, findings: list[Finding]) -> list[Finding]:
        """
        Populate plain_english and recommendation fields for all findings.
        """
        for f in findings:
            self._explain_single(f)
        return findings

    def _explain_single(self, f: Finding) -> None:
        title_lower = f.title.lower()

        # --- Category: OSCILLATION ---
        if f.category == Category.OSCILLATION:
            axis = "roll" if "roll" in title_lower else "pitch" if "pitch" in title_lower else "yaw" if "yaw" in title_lower else "unknown"
            f.plain_english = (
                f"Sustained oscillation detected on the {axis} axis. This is typically "
                f"caused by PID rate gains that are too high (excessive P term) or "
                f"insufficient damping (low D term), leading to limit-cycle behavior."
            )
            param_name = "MC_ROLLRATE_P" if axis == "roll" else "MC_PITCHRATE_P" if axis == "pitch" else "MC_YAWRATE_P"
            f.recommendation = (
                f"Reduce the {axis}-axis rate controller P gain ({param_name}) by approximately "
                f"10-15%. If the oscillation persists, consider increasing the rate D gain."
            )

        # --- Category: VIBRATION ---
        elif f.category == Category.VIBRATION:
            if "critical vibration" in title_lower:
                f.plain_english = (
                    "Vibration levels on the flight controller are extremely high, exceeding "
                    "critical safety limits. Severe vibration can saturate internal sensors and "
                    "cause catastrophic EKF estimation failures or flyaways."
                )
                f.recommendation = (
                    "Do not fly. Inspect propellers for balance or damage. Check all motor bell "
                    "screws and ensure the frame arms and flight controller mounts are tight."
                )
            elif "elevated vibration" in title_lower:
                f.plain_english = (
                    "Vibration levels are higher than normal. Elevated vibration increases noise "
                    "in the attitude estimation, reducing flight efficiency and potentially degrading "
                    "positioning accuracy."
                )
                f.recommendation = (
                    "Balance propellers using a prop balancer. Inspect motor mounts and check if "
                    "the flight controller mounting tape or dampers are worn out."
                )
            elif "hard imu clipping" in title_lower:
                f.plain_english = (
                    "The inertial measurement unit (IMU) saturated due to severe physical impacts or "
                    "extremely high-frequency vibration, causing loss of sensor data."
                )
                f.recommendation = (
                    "Check for a loose propeller, bent motor shaft, or motor bell. Ensure the "
                    "flight controller is securely mounted on vibration-damping foam."
                )
            elif "inconsistency" in title_lower:
                f.plain_english = (
                    "The redundant IMU sensors on the flight controller measured significantly different "
                    "vibration levels, indicating a mounting, isolation, or internal hardware issue."
                )
                f.recommendation = (
                    "Inspect the flight controller mounting. Verify that one side is not touching "
                    "the frame directly or pinched by wires, bypassing the dampening."
                )
            else:
                f.plain_english = f.technical_summary
                f.recommendation = "Check physical frame rigidity, motor mounts, and prop balancing."

        # --- Category: MOTORS ---
        elif f.category == Category.MOTORS:
            if "imbalance" in title_lower:
                f.plain_english = (
                    "The flight controller is commanding significantly different thrust levels to opposite "
                    "motors to keep the drone level, indicating a physical asymmetry or motor efficiency loss."
                )
                f.recommendation = (
                    "Inspect for bent arms, twisted motor mounts, warped propellers, or motor bearings "
                    "with high mechanical drag."
                )
            elif "thermal stress" in title_lower:
                f.plain_english = (
                    "The electronic speed controller (ESC) temperature exceeded safe operating limits, "
                    "risking thermal shutdown or permanent hardware failure."
                )
                f.recommendation = (
                    "Check motor loading, reduce payload weight, or improve airflow/cooling around the ESCs."
                )
            elif "dropout" in title_lower:
                f.plain_english = (
                    "A motor output dropout was detected where commanded thrust briefly fell to zero or near-zero, "
                    "which can cause sudden attitude instability."
                )
                f.recommendation = (
                    "Check ESC signal wiring, power connectors, and check logs for desync events or "
                    "propeller slips."
                )
            else:
                f.plain_english = f.technical_summary
                f.recommendation = "Inspect motor and ESC connections and check logs for error flags."

        # --- Category: GPS ---
        elif f.category == Category.GPS:
            if "lost" in title_lower:
                f.plain_english = (
                    "The GPS receiver completely lost its 3D position fix during flight, forcing the autopilot "
                    "to fall back to non-GPS manual or altitude-stabilized modes."
                )
                f.recommendation = (
                    "Ensure clear sky view. Check GPS antenna connection and inspect for RF interference "
                    "from onboard electronics (cameras, transmitters)."
                )
            elif "degradation" in title_lower:
                f.plain_english = (
                    "The quality of the GPS position estimate degraded, which can cause positioning drift, "
                    "toilet-bowling behavior, or safety warnings."
                )
                f.recommendation = (
                    "Check for GPS antenna shading or local RF interference sources such as cameras or "
                    "telemetry transmitters."
                )
            elif "drop" in title_lower:
                f.plain_english = (
                    "The number of tracked GPS satellites dropped rapidly, indicating antenna obstruction "
                    "or severe RF interference."
                )
                f.recommendation = (
                    "Inspect the GPS receiver mounting and check for shielding/separation from RF-noisy "
                    "components."
                )
            elif "uncertainty" in title_lower or "hdop" in title_lower:
                f.plain_english = (
                    "The GPS dilution of precision (HDOP) was high, meaning satellite geometry or signal "
                    "quality was poor, reducing position accuracy."
                )
                f.recommendation = (
                    "Avoid flying near tall structures or in poor weather. Check GPS signal health."
                )
            elif "interference" in title_lower or "jam" in title_lower:
                f.plain_english = (
                    "High levels of radio frequency interference (RFI) were detected in the GPS frequency band, "
                    "jamming the receiver."
                )
                f.recommendation = (
                    "Relocate GPS antenna away from onboard transmitters, cameras, and processors. Use shielding."
                )
            elif "spoofing" in title_lower:
                f.plain_english = (
                    "The GPS receiver detected potential signal spoofing, where fake GPS signals are being broadcast."
                )
                f.recommendation = (
                    "Land immediately. Do not rely on GPS-guided flight modes in the affected area."
                )
            else:
                f.plain_english = f.technical_summary
                f.recommendation = "Ensure clear view of sky and minimal RF interference."

        # --- Category: EKF ---
        elif f.category == Category.EKF:
            if "failure" in title_lower:
                f.plain_english = (
                    "The Extended Kalman Filter (EKF) rejected sensor measurements because they differed too much "
                    "from internal state estimates."
                )
                f.recommendation = (
                    "Check sensor calibration (magnetometer, accelerometer). Inspect for mechanical vibration."
                )
            elif "invalid" in title_lower:
                f.plain_english = (
                    "The EKF status flags indicated that the navigation solution became invalid, meaning the "
                    "autopilot could not estimate its position or attitude reliably."
                )
                f.recommendation = (
                    "Do not fly in GPS or altitude-stabilized modes. Recalibrate sensors and inspect hardware."
                )
            elif "ratio" in title_lower:
                f.plain_english = (
                    "The EKF innovation ratio exceeded safe thresholds, indicating high discrepancy between sensor "
                    "measurements and EKF state."
                )
                f.recommendation = (
                    "Check for vibration issues or magnetic disturbances affecting the sensors."
                )
            elif "wind" in title_lower:
                f.plain_english = (
                    "The EKF wind velocity estimate jumped suddenly, which is often caused by sensor anomalies "
                    "or sudden external aerodynamic changes."
                )
                f.recommendation = (
                    "Check airspeed sensor calibration (if equipped) and verify EKF compass alignment."
                )
            else:
                f.plain_english = f.technical_summary
                f.recommendation = "Verify sensor calibration and check for vibration or magnetic interference."

        # --- Category: BATTERY ---
        elif f.category == Category.BATTERY:
            if "thermal" in title_lower:
                f.plain_english = (
                    "The battery temperature exceeded safe operating limits during flight, which accelerates cell "
                    "degradation and poses a thermal runaway risk."
                )
                f.recommendation = (
                    "Allow the battery to cool down. Reduce payload weight or aggressive maneuvers to lower "
                    "current draw."
                )
            elif "c-rate" in title_lower:
                f.plain_english = (
                    "The battery current draw exceeded its rated continuous C-rate, causing severe stress to the cells."
                )
                f.recommendation = (
                    "Use a higher C-rate battery or optimize the drone's weight and motor-propeller efficiency."
                )
            elif "sag" in title_lower:
                f.plain_english = (
                    "The battery voltage dropped excessively under load, indicating high internal resistance, a "
                    "weak cell, or an overloaded battery."
                )
                f.recommendation = (
                    "Retire or replace this battery pack, as it is nearing the end of its useful life."
                )
            elif "capacity" in title_lower:
                f.plain_english = (
                    "The calculated battery capacity is significantly below its rated value, indicating cell aging "
                    "or health degradation."
                )
                f.recommendation = (
                    "Cycle the battery to calibrate, and replace the pack if capacity remains low."
                )
            else:
                f.plain_english = f.technical_summary
                f.recommendation = "Inspect battery connections, age, and cell balance."

        # --- Category: PARAMETERS ---
        elif f.category == Category.PARAMETERS:
            if "deprecated" in title_lower:
                f.plain_english = (
                    "A parameter in the flight controller config is deprecated in this firmware version and has "
                    "no effect."
                )
                f.recommendation = "Remove this parameter from your configuration file to prevent confusion."
            elif "below safe range" in title_lower:
                f.plain_english = (
                    "A parameter is set below its recommended safe minimum value, which could cause unstable "
                    "flight or safety issues."
                )
                f.recommendation = "Increase the parameter value to within the safe range."
            elif "above safe range" in title_lower:
                f.plain_english = (
                    "A parameter is set above its recommended safe maximum value, which could cause overshoot, "
                    "oscillation, or damage."
                )
                f.recommendation = "Reduce the parameter value to within the safe range."
            elif "inverted" in title_lower:
                f.plain_english = (
                    "The battery low warning threshold is set lower than the critical warning threshold, which "
                    "renders failsafes ineffective."
                )
                f.recommendation = "Correct the battery thresholds so that BAT_LOW_THR is greater than BAT_CRIT_THR."
            elif "loss timeout" in title_lower:
                f.plain_english = (
                    "The RC loss connection timeout is set extremely short, which could trigger failsafe actions "
                    "on brief signal glitches."
                )
                f.recommendation = "Set COM_RC_LOSS_T to a safe value (typically 0.5s or greater)."
            elif "high rate p" in title_lower:
                f.plain_english = (
                    "The PID rate controller P gain is high while the D gain is extremely low, creating a high risk "
                    "of rapid rate oscillations."
                )
                f.recommendation = "Lower the P gain or increase the D gain to stabilize rate control."
            elif "instability risk" in title_lower:
                f.plain_english = (
                    "The position loop P gain is set high relative to velocity loop limits, which may cause "
                    "position overshoot and oscillation."
                )
                f.recommendation = "Adjust the position loop gains or increase acceleration limits to prevent instability."
            else:
                f.plain_english = f.technical_summary
                f.recommendation = "Verify the parameter values against safe default ranges."

        # --- Fallback ---
        else:
            f.plain_english = f.technical_summary
            f.recommendation = "Consult the log details or PX4 documentation for troubleshooting."

    async def generate_summary(
        self,
        metadata: FlightMetadata,
        findings: list[Finding],
        overall_score: float,
        score_label: str,
    ) -> str:
        """
        Generate a concise, deterministic executive summary based on the findings
        and metadata.
        """
        if not findings:
            return (
                f"Flight analysed. Health score: {overall_score:.0f}/100 ({score_label}). "
                f"All systems operating within safe nominal parameters. No anomalies detected."
            )

        criticals = [f for f in findings if f.severity == Severity.CRITICAL]
        warnings  = [f for f in findings if f.severity == Severity.WARNING]

        summary_parts = []
        summary_parts.append(
            f"Flight health score is {overall_score:.0f}/100 ({score_label}) based on "
            f"{metadata.duration_seconds:.0f}s of log data."
        )

        if criticals:
            summary_parts.append(
                f"CRITICAL issue(s) detected: {', '.join(f.title for f in criticals)}. "
                f"Action is required to ensure flight safety."
            )
        elif warnings:
            summary_parts.append(
                f"Warning(s) detected: {', '.join(f.title for f in warnings)}. "
                f"Review the recommendations to optimize performance and reliability."
            )
        else:
            summary_parts.append(
                f"Note: {len(findings)} minor issue(s) detected. All critical metrics remain healthy."
            )

        return " ".join(summary_parts)
