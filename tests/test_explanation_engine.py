"""
Tests for ExplanationEngine — verifies deterministic mappings for all finding categories and titles.
"""

import pytest
from flightmd_core.models.findings import Finding, Category, Severity
from flightmd_core.models.metadata import FlightMetadata
from flightmd_core.services.explanation_engine import ExplanationEngine


@pytest.fixture
def engine():
    return ExplanationEngine()


@pytest.fixture
def mock_metadata():
    return FlightMetadata(
        duration_seconds=600.0,
        start_time_utc="2026-07-04T12:00:00Z",
        hardware="PX4_FMU_V5",
        firmware_version="1.14.0",
        original_filename="test_flight.ulg",
    )


@pytest.mark.asyncio
async def test_oscillation_explanation(engine):
    finding = Finding(
        category=Category.OSCILLATION,
        severity=Severity.WARNING,
        title="Roll-axis oscillation",
        technical_summary="Sustained oscillation detected on roll axis.",
        plain_english="",
        recommendation="",
        confidence=1.0,
    )
    results = await engine.explain_findings([finding])
    f = results[0]
    assert "roll" in f.plain_english.lower()
    assert "MC_ROLLRATE_P" in f.recommendation


@pytest.mark.asyncio
async def test_vibration_explanations(engine):
    findings = [
        Finding(
            category=Category.VIBRATION,
            severity=Severity.CRITICAL,
            title="Critical vibration levels",
            technical_summary="Vibrations exceeded critical safety limits.",
            plain_english="",
            recommendation="",
            confidence=1.0,
        ),
        Finding(
            category=Category.VIBRATION,
            severity=Severity.WARNING,
            title="Elevated vibration levels",
            technical_summary="Vibrations are elevated.",
            plain_english="",
            recommendation="",
            confidence=1.0,
        ),
        Finding(
            category=Category.VIBRATION,
            severity=Severity.CRITICAL,
            title="Hard IMU clipping detected",
            technical_summary="IMU saturated.",
            plain_english="",
            recommendation="",
            confidence=1.0,
        ),
        Finding(
            category=Category.VIBRATION,
            severity=Severity.WARNING,
            title="IMU inconsistency issue",
            technical_summary="IMUs inconsistent.",
            plain_english="",
            recommendation="",
            confidence=1.0,
        ),
    ]
    results = await engine.explain_findings(findings)
    assert "critical safety limits" in results[0].plain_english
    assert "Balance propellers" in results[1].recommendation
    assert "saturated" in results[2].plain_english
    assert "mounting" in results[3].recommendation


@pytest.mark.asyncio
async def test_motor_explanations(engine):
    findings = [
        Finding(
            category=Category.MOTORS,
            severity=Severity.WARNING,
            title="Motor thrust imbalance",
            technical_summary="Thrust imbalance detected.",
            plain_english="",
            recommendation="",
            confidence=1.0,
        ),
        Finding(
            category=Category.MOTORS,
            severity=Severity.WARNING,
            title="ESC thermal stress",
            technical_summary="ESC temperature high.",
            plain_english="",
            recommendation="",
            confidence=1.0,
        ),
        Finding(
            category=Category.MOTORS,
            severity=Severity.WARNING,
            title="Motor output dropout",
            technical_summary="Thrust dropped to zero.",
            plain_english="",
            recommendation="",
            confidence=1.0,
        ),
    ]
    results = await engine.explain_findings(findings)
    assert "thrust levels" in results[0].plain_english
    assert "ESC" in results[1].plain_english
    assert "dropout" in results[2].plain_english


@pytest.mark.asyncio
async def test_gps_explanations(engine):
    findings = [
        Finding(
            category=Category.GPS,
            severity=Severity.CRITICAL,
            title="GPS signal lost",
            technical_summary="GPS lost.",
            plain_english="",
            recommendation="",
            confidence=1.0,
        ),
        Finding(
            category=Category.GPS,
            severity=Severity.WARNING,
            title="GPS accuracy degradation",
            technical_summary="Accuracy degraded.",
            plain_english="",
            recommendation="",
            confidence=1.0,
        ),
        Finding(
            category=Category.GPS,
            severity=Severity.WARNING,
            title="Satellite count drop",
            technical_summary="Satellites dropped.",
            plain_english="",
            recommendation="",
            confidence=1.0,
        ),
        Finding(
            category=Category.GPS,
            severity=Severity.WARNING,
            title="High HDOP / uncertainty",
            technical_summary="HDOP high.",
            plain_english="",
            recommendation="",
            confidence=1.0,
        ),
        Finding(
            category=Category.GPS,
            severity=Severity.WARNING,
            title="GPS jamming / interference",
            technical_summary="Jamming detected.",
            plain_english="",
            recommendation="",
            confidence=1.0,
        ),
        Finding(
            category=Category.GPS,
            severity=Severity.CRITICAL,
            title="GPS spoofing detected",
            technical_summary="Spoofing.",
            plain_english="",
            recommendation="",
            confidence=1.0,
        ),
    ]
    results = await engine.explain_findings(findings)
    assert "completely lost" in results[0].plain_english
    assert "degraded" in results[1].plain_english
    assert "antenna obstruction" in results[2].plain_english
    assert "HDOP" in results[3].plain_english
    assert "jamming" in results[4].plain_english
    assert "spoofing" in results[5].plain_english


@pytest.mark.asyncio
async def test_ekf_explanations(engine):
    findings = [
        Finding(
            category=Category.EKF,
            severity=Severity.CRITICAL,
            title="EKF innovation failure",
            technical_summary="Innovation test failed.",
            plain_english="",
            recommendation="",
            confidence=1.0,
        ),
        Finding(
            category=Category.EKF,
            severity=Severity.CRITICAL,
            title="EKF solution invalid",
            technical_summary="State invalid.",
            plain_english="",
            recommendation="",
            confidence=1.0,
        ),
        Finding(
            category=Category.EKF,
            severity=Severity.WARNING,
            title="EKF innovation ratio exceeded",
            technical_summary="Ratio exceeded.",
            plain_english="",
            recommendation="",
            confidence=1.0,
        ),
        Finding(
            category=Category.EKF,
            severity=Severity.WARNING,
            title="EKF wind estimate jump",
            technical_summary="Wind jump.",
            plain_english="",
            recommendation="",
            confidence=1.0,
        ),
    ]
    results = await engine.explain_findings(findings)
    assert "rejected" in results[0].plain_english
    assert "invalid" in results[1].plain_english
    assert "ratio" in results[2].plain_english
    assert "wind" in results[3].plain_english


@pytest.mark.asyncio
async def test_battery_explanations(engine):
    findings = [
        Finding(
            category=Category.BATTERY,
            severity=Severity.WARNING,
            title="Battery thermal stress",
            technical_summary="Temp high.",
            plain_english="",
            recommendation="",
            confidence=1.0,
        ),
        Finding(
            category=Category.BATTERY,
            severity=Severity.WARNING,
            title="High C-rate draw",
            technical_summary="C-rate high.",
            plain_english="",
            recommendation="",
            confidence=1.0,
        ),
        Finding(
            category=Category.BATTERY,
            severity=Severity.WARNING,
            title="High voltage sag",
            technical_summary="Sag high.",
            plain_english="",
            recommendation="",
            confidence=1.0,
        ),
        Finding(
            category=Category.BATTERY,
            severity=Severity.WARNING,
            title="Battery capacity fade",
            technical_summary="Capacity low.",
            plain_english="",
            recommendation="",
            confidence=1.0,
        ),
    ]
    results = await engine.explain_findings(findings)
    assert "temperature" in results[0].plain_english
    assert "C-rate" in results[1].plain_english
    assert "voltage dropped" in results[2].plain_english
    assert "capacity" in results[3].plain_english


@pytest.mark.asyncio
async def test_parameter_explanations(engine):
    findings = [
        Finding(
            category=Category.PARAMETERS,
            severity=Severity.INFO,
            title="Deprecated parameter",
            technical_summary="Deprecated.",
            plain_english="",
            recommendation="",
            confidence=1.0,
        ),
        Finding(
            category=Category.PARAMETERS,
            severity=Severity.WARNING,
            title="Parameter below safe range",
            technical_summary="Below range.",
            plain_english="",
            recommendation="",
            confidence=1.0,
        ),
        Finding(
            category=Category.PARAMETERS,
            severity=Severity.WARNING,
            title="Parameter above safe range",
            technical_summary="Above range.",
            plain_english="",
            recommendation="",
            confidence=1.0,
        ),
        Finding(
            category=Category.PARAMETERS,
            severity=Severity.CRITICAL,
            title="Battery thresholds inverted",
            technical_summary="Inverted.",
            plain_english="",
            recommendation="",
            confidence=1.0,
        ),
        Finding(
            category=Category.PARAMETERS,
            severity=Severity.WARNING,
            title="RC loss timeout short",
            technical_summary="Timeout short.",
            plain_english="",
            recommendation="",
            confidence=1.0,
        ),
        Finding(
            category=Category.PARAMETERS,
            severity=Severity.WARNING,
            title="High rate P gain",
            technical_summary="P gain high.",
            plain_english="",
            recommendation="",
            confidence=1.0,
        ),
        Finding(
            category=Category.PARAMETERS,
            severity=Severity.WARNING,
            title="Position loop instability risk",
            technical_summary="Instability risk.",
            plain_english="",
            recommendation="",
            confidence=1.0,
        ),
    ]
    results = await engine.explain_findings(findings)
    assert "deprecated" in results[0].plain_english
    assert "minimum" in results[1].plain_english
    assert "maximum" in results[2].plain_english
    assert "threshold" in results[3].plain_english
    assert "timeout" in results[4].plain_english
    assert "PID" in results[5].plain_english
    assert "overshoot" in results[6].plain_english


@pytest.mark.asyncio
async def test_fallback_explanation(engine):
    finding = Finding(
        category=Category.SYSTEM,
        severity=Severity.WARNING,
        title="Some undocumented finding",
        technical_summary="System anomaly.",
        plain_english="",
        recommendation="",
        confidence=1.0,
    )
    results = await engine.explain_findings([finding])
    f = results[0]
    assert f.plain_english == "System anomaly."
    assert "Consult" in f.recommendation


@pytest.mark.asyncio
async def test_summary_generation_empty(engine, mock_metadata):
    summary = await engine.generate_summary(mock_metadata, [], 95.0, "Excellent")
    assert "Excellent" in summary
    assert "95" in summary
    assert "All systems operating within safe nominal parameters" in summary


@pytest.mark.asyncio
async def test_summary_generation_with_findings(engine, mock_metadata):
    findings = [
        Finding(
            category=Category.VIBRATION,
            severity=Severity.CRITICAL,
            title="Critical vibration levels",
            technical_summary="Vibrations exceeded critical safety limits.",
            plain_english="",
            recommendation="",
            confidence=1.0,
        ),
        Finding(
            category=Category.OSCILLATION,
            severity=Severity.WARNING,
            title="Roll-axis oscillation",
            technical_summary="Sustained oscillation detected on roll axis.",
            plain_english="",
            recommendation="",
            confidence=1.0,
        ),
    ]
    summary = await engine.generate_summary(mock_metadata, findings, 45.0, "Poor")
    assert "45" in summary
    assert "Poor" in summary
    assert "CRITICAL issue(s) detected: Critical vibration levels" in summary
