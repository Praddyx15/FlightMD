"""
explanations.py — Offline template-based explanation and executive summary generator.

Bypasses the LLM entirely, providing expert-authored, deterministic explanations
and recommendations for all flight diagnostics findings, and synthesising
a cohesive report summary.
"""

from typing import Optional
from flightmd_core.models.findings import Finding, Severity, Category, FlightMetadata

# Mapping of finding patterns to template explanations and recommendations
# Matches by lowercase keywords in finding.title
TEMPLATES = {
    # Oscillation
    "roll-axis oscillation": (
        "The flight log detected a sustained oscillation on the roll axis. "
        "This is typically caused by the PID rate controller being too aggressive (high P-gain) "
        "or lacking enough damping (low D-gain), which causes the attitude controller to overcorrect.",
        "Decrease the roll-rate P-gain parameter (e.g., MC_ROLLRATE_P) by approximately 10-15% to dampen the oscillation."
    ),
    "pitch-axis oscillation": (
        "The flight log detected a sustained oscillation on the pitch axis. "
        "This is typically caused by the PID rate controller being too aggressive (high P-gain) "
        "or lacking enough damping (low D-gain), which causes the attitude controller to overcorrect.",
        "Decrease the pitch-rate P-gain parameter (e.g., MC_PITCHRATE_P) by approximately 10-15% to dampen the oscillation."
    ),
    "yaw-axis oscillation": (
        "The flight log detected a sustained oscillation on the yaw axis. "
        "This is typically caused by the yaw rate PID gains being too high or yaw structural resonance.",
        "Decrease the yaw-rate P-gain parameter (e.g., MC_YAWRATE_P) by approximately 10-15% to dampen the oscillation."
    ),

    # Vibration
    "critical vibration": (
        "Vibration levels on the flight controller are dangerously high. "
        "Excessive vibration introduces noise into the IMU sensors, causing EKF state estimation failures "
        "and potentially leading to flyaways or structural failure.",
        "Immediately inspect the airframe. Check for unbalanced/chipped propellers, loose motor mounts, "
        "cracked frame arms, and ensure the flight controller is securely mounted with vibration-damping foam."
    ),
    "elevated vibration": (
        "Vibration levels are elevated, exceeding normal operational thresholds. "
        "While not immediately critical, sustained high vibration degrades sensor accuracy, stresses the "
        "flight controller's internal estimators, and accelerates mechanical fatigue.",
        "Inspect and balance the propellers. Check motor screws and ensure all airframe components are tight."
    ),
    "hard imu clipping": (
        "Hard IMU clipping was detected. The accelerometers saturated because physical vibrations exceeded "
        "their measurement limit. This corrupts attitude and velocity estimation, making a crash highly likely.",
        "Inspect the drone for severe mechanical issues like loose prop nuts, motor bearing wear, or a loose flight controller board. "
        "Improve physical isolation of the autopilot."
    ),
    "imu instance inconsistency": (
        "The multiple IMUs onboard disagreed significantly on vibration levels. "
        "This indicates that one of the IMUs is experiencing much higher vibration path transmission, "
        "possibly due to poor damping or asymmetric airframe flex.",
        "Check flight controller mounting isolation. Inspect the frame for asymmetric stiffness or loose structural parts."
    ),

    # EKF
    "ekf innovation failure": (
        "The Extended Kalman Filter (EKF) innovation test failed. This means the estimator detected "
        "a persistent discrepancy between the expected state and the raw sensor measurements, "
        "indicating a potential sensor malfunction, calibration error, or external interference.",
        "Perform accelerometer, compass, and gyroscope calibration. Inspect for magnetic interference near the compass."
    ),
    "ekf solution invalid": (
        "The EKF attitude or velocity state estimate became invalid. "
        "This is a critical state where the flight controller loses tracking of position/orientation, "
        "often causing position hold failures or sudden flight mode changes.",
        "Ensure proper pre-flight calibration. Inspect log for vibration levels or sensor failures that could have caused the EKF to reject data."
    ),
    "ekf innovation ratio exceeded": (
        "The innovation test ratio for a sensor exceeded 1.0, indicating the EKF is rejecting or questioning "
        "sensor data. Consistent failures will degrade position and altitude hold performance.",
        "Recalibrate the affected sensor (compass/barometer/GPS) and check for environmental/physical noise."
    ),
    "unexpected wind estimation jump": (
        "The EKF wind estimator registered a sudden, major change in wind speed or direction. "
        "This usually points to a sensor glitch (such as compass or airspeed sensor dropouts) rather than real wind.",
        "Review GPS velocity, compass alignment, and airspeed/pitot tube data for anomalies or obstructions."
    ),

    # Battery
    "high voltage sag": (
        "The battery voltage dropped excessively under load. This indicates high internal resistance "
        "in the battery pack, which reduces available capacity, reduces motor thrust headroom, "
        "and risks triggering low-voltage failsafes.",
        "Retire or cycle-test this battery pack. Consider using a pack with a higher C-rating or lower age."
    ),
    "battery capacity fade": (
        "The battery discharged significantly faster than expected relative to its rated capacity. "
        "This indicates a degraded battery pack with lost capacity, accelerating flight time reductions.",
        "Cycle-test the battery using a dedicated discharger. Retire the pack if capacity is under 80% of rated value."
    ),
    "battery thermal stress": (
        "The battery temperature exceeded safe operational limits. High temperatures damage LiPo cells, "
        "risk thermal runaway, and cause permanent capacity degradation.",
        "Allow the battery to cool down fully before charging or flying again. Improve airflow around the battery compartment."
    ),
    "high c-rate stress": (
        "The battery was discharged at a very high rate relative to its capacity. "
        "Consistently high C-rate draws cause rapid heating, voltage sag, and accelerate battery degradation.",
        "Use a higher capacity battery or reduce drone payload/aggressiveness. Ensure the battery is rated for the peak current draw."
    ),

    # GPS
    "poor gps fix quality": (
        "The GPS receiver reported poor fix quality. Low satellite counts or weak signals make autonomous "
        "flight modes unstable and increase the risk of position drift.",
        "Wait for a better GPS fix (e.g., RTK or 3D Lock with >12 satellites) before arming. Fly in an open area."
    ),
    "loss of gps fix": (
        "GPS signal was lost during the flight. This forces the drone out of position control modes "
        "into manual/altitude control, requiring pilot intervention.",
        "Check GPS antenna connection and check for RF noise or obstructions near the GPS module."
    ),
    "sudden satellite count drop": (
        "The number of tracked satellites dropped suddenly. This can be caused by physical shielding (e.g., banking/flips), "
        "multipath interference from tall buildings, or electromagnetic noise from onboard electronics.",
        "Inspect GPS antenna placement. Keep it separated from telemetry transceivers, cameras, and ESC power cables."
    ),
    "high hdop": (
        "Horizontal Dilution of Precision (HDOP) is high, indicating poor satellite geometry. "
        "Position estimates will be less accurate and prone to jumping.",
        "Avoid flying close to tall structures or trees that block the sky view."
    ),
    "gps jamming detected": (
        "Significant RF interference was detected in the GPS frequency bands, indicating active GPS jamming.",
        "Move away from military areas, communication towers, or urban zones. Inspect onboard equipment (e.g. video transmitters) for RF leaks."
    ),
    "gps spoofing detected": (
        "The GPS receiver detected indicators of signal spoofing, meaning external transmitters are "
        "broadcasting fake GPS coordinates to hijack or disrupt navigation.",
        "Immediately land the drone or switch to manual/altitude control. Do not trust autonomous return-to-home."
    ),

    # Parameters & Motors
    "oscillation risk": (
        "A combination of rate controller parameters is configured unsafely, posing a high risk of "
        "sustained control oscillations in flight.",
        "Verify your P and D rate gains (e.g. MC_ROLLRATE_P, MC_ROLLRATE_D) against standard values."
    ),
    "position loop instability risk": (
        "Position controller settings are configured in a way that could cause position loop oscillations "
        "or sluggish control response.",
        "Adjust position loop gains (MPC_XY_P and velocity limits) to recommended PX4 defaults."
    ),
    "battery thresholds inverted": (
        "The low battery warning threshold is configured lower than or equal to the critical threshold.",
        "Correct battery threshold parameters (e.g., set BAT_LOW_THR higher than BAT_CRIT_THR)."
    ),
    "very short rc loss timeout": (
        "The RC transmitter signal loss timeout is set dangerously short. A tiny signal drop could "
        "falsely trigger failsafe behavior.",
        "Increase COM_RC_LOSS_T to at least 1.0 or 2.0 seconds."
    ),
    "deprecated parameter": (
        "The flight controller has one or more parameters that are deprecated in this firmware version.",
        "Remove the deprecated parameter(s) from your configuration profile."
    ),
    "parameter below safe range": (
        "A configuration parameter is set lower than the recommended safe minimum value.",
        "Increase the parameter value to match safe limits."
    ),
    "parameter above safe range": (
        "A configuration parameter exceeds the recommended safe maximum value.",
        "Decrease the parameter value to match safe limits."
    ),
    "motor imbalance": (
        "A significant motor imbalance was detected. One or more motors are running at much higher RPM "
        "or drawing more current than the others to maintain hover.",
        "Inspect all motors for mechanical drag, check propeller condition, and verify physical airframe symmetry."
    ),
    "esc temperature warning": (
        "One or more Electronic Speed Controllers (ESCs) exceeded safe temperature thresholds.",
        "Verify ESC ventilation and check for binding or motor/propeller mismatch."
    ),
    "rpm dropout": (
        "A motor RPM dropout was detected mid-flight, where a motor briefly reported zero speed.",
        "Inspect ESC signal wiring, check for desync issues, or replace the affected motor/ESC."
    ),
    "current imbalance": (
        "One or more ESCs reported drawing significantly more current than the average.",
        "Check for mechanical binding in the motor bearings or a warped propeller."
    ),
}

def fill_explanation(finding: Finding) -> None:
    """
    Look up the deterministic template for the finding based on its title,
    populating plain_english and recommendation fields.
    """
    title_lower = finding.title.lower()
    
    # Try direct keyword matches
    matched_key = None
    for key in TEMPLATES:
        if key in title_lower:
            matched_key = key
            break
            
    if matched_key:
        plain_template, rec_template = TEMPLATES[matched_key]
        
        # Simple context dictionary from technical_summary parsing
        # (Could extract values if needed, otherwise fall back to formatted string or raw templates)
        finding.plain_english = plain_template
        finding.recommendation = rec_template
    else:
        # Default fallback
        finding.plain_english = finding.technical_summary
        finding.recommendation = "Review the technical details to diagnose this issue."


def generate_report_summary(
    metadata: FlightMetadata,
    findings: list[Finding],
    overall_score: float,
    score_label: str
) -> str:
    """
    Generate a cohesive, rule-based executive summary.
    """
    duration_min = round(metadata.duration_seconds / 60, 1)
    
    if not findings:
        return (
            f"Flight completed successfully with an Excellent health score of {overall_score:.0f}/100. "
            f"All systems (battery, vibrations, EKF state estimation, and GPS) operated well within safe limits. "
            f"The aircraft is fully airworthy and ready for its next mission."
        )

    # Sort findings by severity
    criticals = [f for f in findings if f.severity == Severity.CRITICAL]
    warnings = [f for f in findings if f.severity == Severity.WARNING]
    infos = [f for f in findings if f.severity == Severity.INFO]
    
    summary_parts = []
    
    if criticals:
        top_crit = criticals[0]
        summary_parts.append(
            f"CRITICAL: A severe issue was detected during the {duration_min} minute flight: {top_crit.title}."
        )
    elif warnings:
        top_warn = warnings[0]
        summary_parts.append(
            f"WARNING: The {duration_min} minute flight registered a safety warning: {top_warn.title}."
        )
    else:
        top_info = infos[0]
        summary_parts.append(
            f"NOTICE: System notes during the {duration_min} minute flight: {top_info.title}."
        )
        
    # Additional context on other findings
    other_count = len(findings) - 1
    if other_count > 0:
        summary_parts.append(
            f"An additional {other_count} finding(s) require attention."
        )
        
    summary_parts.append(
        f"Overall flight health is graded {overall_score:.0f}/100 ({score_label}). "
        f"Please review the detailed diagnostics and parameter recommendation sheet to restore optimal airworthiness."
    )
    
    return " ".join(summary_parts)
