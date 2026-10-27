"""
Tests for ExplanationEngine — templates keyed by Finding.kind, summaries.
"""

import pytest

from flightmd_core.models.findings import AnalyserResult, Finding, Category, Severity
from flightmd_core.models.metadata import FlightMetadata
from flightmd_core.services.explanation_engine import ExplanationEngine, TEMPLATES


@pytest.fixture
def engine():
    return ExplanationEngine()


@pytest.fixture
def metadata():
    return FlightMetadata(duration_seconds=600.0, firmware_version="1.14.0")


def finding(category, kind, title="Some title", severity=Severity.WARNING, recommendation=""):
    return Finding(
        category=category,
        severity=severity,
        kind=kind,
        title=title,
        technical_summary=f"technical summary for {kind}",
        plain_english="",
        recommendation=recommendation,
        confidence=0.9,
    )


ANALYSER_KINDS = [
    (Category.OSCILLATION, "oscillation.rate_p"),
    (Category.OSCILLATION, "oscillation.rate_d"),
    (Category.OSCILLATION, "oscillation.mechanical"),
    (Category.VIBRATION, "vibration.critical"),
    (Category.VIBRATION, "vibration.elevated"),
    (Category.VIBRATION, "vibration.clipping"),
    (Category.VIBRATION, "vibration.imu_mismatch"),
    (Category.MOTORS, "motors.rpm_imbalance"),
    (Category.MOTORS, "motors.current_imbalance"),
    (Category.MOTORS, "motors.esc_thermal"),
    (Category.MOTORS, "motors.dropout"),
    (Category.GPS, "gps.no_fix"),
    (Category.GPS, "gps.fix_lost"),
    (Category.GPS, "gps.fix_degraded"),
    (Category.GPS, "gps.sat_drop"),
    (Category.GPS, "gps.hdop"),
    (Category.GPS, "gps.jamming"),
    (Category.GPS, "gps.spoofing"),
    (Category.EKF, "ekf.innovation_rejected"),
    (Category.EKF, "ekf.solution_invalid"),
    (Category.EKF, "ekf.gps_glitch"),
    (Category.EKF, "ekf.accel_error"),
    (Category.EKF, "ekf.innovation_ratio"),
    (Category.EKF, "ekf.wind_jump"),
    (Category.BATTERY, "battery.thermal"),
    (Category.BATTERY, "battery.c_rate"),
    (Category.BATTERY, "battery.sag"),
    (Category.BATTERY, "battery.capacity_fade"),
    (Category.PARAMETERS, "params.deprecated"),
    (Category.PARAMETERS, "params.below_range"),
    (Category.PARAMETERS, "params.above_range"),
    (Category.PARAMETERS, "params.bat_thr_inverted"),
    (Category.PARAMETERS, "params.rc_loss_short"),
    (Category.PARAMETERS, "params.rate_p_high_d_low"),
    (Category.PARAMETERS, "params.pos_loop_risk"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("category, kind", ANALYSER_KINDS)
async def test_every_analyser_kind_has_a_template(engine, category, kind):
    assert kind in TEMPLATES
    [f] = await engine.explain_findings([finding(category, kind)])
    assert f.plain_english == TEMPLATES[kind][0]
    assert f.recommendation == TEMPLATES[kind][1]


@pytest.mark.asyncio
async def test_dispatch_ignores_the_title(engine):
    """Titles are display text; 'Motor Balance Warning' used to match no
    rule and 'Current Imbalance' got the thrust text."""
    a = finding(Category.MOTORS, "motors.current_imbalance", title="Motor Balance Warning")
    b = finding(Category.MOTORS, "motors.rpm_imbalance", title="Motor Current Imbalance")
    await engine.explain_findings([a, b])
    assert a.plain_english == TEMPLATES["motors.current_imbalance"][0]
    assert b.plain_english == TEMPLATES["motors.rpm_imbalance"][0]


@pytest.mark.asyncio
async def test_analyser_recommendation_is_kept(engine):
    """The analyser's own recommendation names the parameter and values;
    the old engine replaced it with generic text."""
    f = finding(Category.OSCILLATION, "oscillation.rate_p",
                recommendation="Reduce MC_ROLLRATE_P from 0.15 to 0.1305 (about 13%), then re-test.")
    await engine.explain_findings([f])
    assert f.recommendation.startswith("Reduce MC_ROLLRATE_P from 0.15 to 0.1305")


@pytest.mark.asyncio
async def test_mid_band_oscillation_text_does_not_say_raise_d(engine):
    [f] = await engine.explain_findings([finding(Category.OSCILLATION, "oscillation.rate_d")])
    assert "increase the rate D" not in f.recommendation
    assert "Lower the rate D" in f.recommendation


@pytest.mark.asyncio
async def test_unknown_kind_falls_back_to_technical_summary(engine):
    f = finding(Category.SYSTEM, None, title="Some undocumented finding")
    await engine.explain_findings([f])
    assert f.plain_english == f.technical_summary
    assert "Consult" in f.recommendation


@pytest.mark.asyncio
async def test_ascent_findings_keep_their_own_text(engine):
    f = finding(Category.ASCENT_PROFILE, "ascent.apogee", severity=Severity.GOOD,
                recommendation="No action needed — this is a factual measurement of the flight profile.")
    await engine.explain_findings([f])
    assert f.plain_english == f.technical_summary
    assert f.recommendation.startswith("No action needed")


@pytest.mark.asyncio
async def test_summary_without_findings(engine, metadata):
    summary = await engine.generate_summary(metadata, [], 95.0, "Excellent")
    assert "95/100 (Excellent)" in summary
    assert "No anomalies detected" in summary
    assert "All systems" not in summary


@pytest.mark.asyncio
async def test_summary_not_assessed_is_not_a_clean_bill(engine, metadata):
    summary = await engine.generate_summary(metadata, [], 0.0, "Not assessed")
    assert "No health score" in summary
    assert "/100" not in summary


@pytest.mark.asyncio
async def test_summary_lists_unassessed_modules(engine, metadata):
    results = [
        AnalyserResult(analyser="gps", display_name="GPS Analysis", findings=[]),
        AnalyserResult(analyser="ekf", display_name="EKF Health Analysis", findings=[],
                       skipped=True, skip_reason="no estimator_status"),
    ]
    summary = await engine.generate_summary(metadata, [], 100.0, "Excellent", results=results)
    assert "Not assessed (no usable data): EKF Health Analysis." in summary


@pytest.mark.asyncio
async def test_summary_with_findings(engine, metadata):
    findings = [
        finding(Category.VIBRATION, "vibration.critical", title="Critical Vibration — IMU 0",
                severity=Severity.CRITICAL),
        finding(Category.OSCILLATION, "oscillation.rate_p", title="Roll-Axis Oscillation at 6.1 Hz"),
    ]
    summary = await engine.generate_summary(metadata, findings, 45.0, "Critical")
    assert "45/100 (Critical)" in summary
    assert "CRITICAL issue(s) detected: Critical Vibration — IMU 0" in summary
