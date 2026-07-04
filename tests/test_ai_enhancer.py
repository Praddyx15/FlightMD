"""
Regression tests for the optional AI enhancement layer.

The core guarantee under test: when no API key is configured (the default,
zero-configuration case), AIEnhancer is a complete no-op and never alters
deterministic output.
"""

import pytest

from flightmd_core.services.ai_enhancer import AIEnhancer, NOT_CONFIGURED_MESSAGE
from flightmd_core.models.findings import Finding, Category, Severity, FlightMDReport
from flightmd_core.models.metadata import FlightMetadata


@pytest.fixture
def sample_metadata() -> FlightMetadata:
    return FlightMetadata(duration_seconds=180.0)


@pytest.fixture
def sample_finding() -> Finding:
    return Finding(
        category=Category.BATTERY,
        severity=Severity.WARNING,
        title="High Voltage Sag",
        technical_summary="Sag of 0.6V/cell measured under load.",
        plain_english="The battery sagged more than expected under load.",
        recommendation="Retire or cycle-test this battery pack.",
        confidence=0.8,
    )


def test_disabled_by_default():
    enhancer = AIEnhancer()
    assert enhancer.is_configured is False
    assert enhancer.provider == "groq"  # groq is the default, zero-cost provider


def test_disabled_with_empty_key():
    enhancer = AIEnhancer(api_key="")
    assert enhancer.is_configured is False


def test_groq_configured_with_key():
    enhancer = AIEnhancer(provider="groq", groq_api_key="gsk_fake_key")
    assert enhancer.is_configured is True
    assert enhancer.provider == "groq"


def test_anthropic_configured_with_explicit_provider():
    enhancer = AIEnhancer(provider="anthropic", anthropic_api_key="sk-ant-fake")
    assert enhancer.is_configured is True
    assert enhancer.provider == "anthropic"


def test_anthropic_provider_without_key_not_configured():
    enhancer = AIEnhancer(provider="anthropic")
    assert enhancer.is_configured is False


def test_unknown_provider_is_disabled():
    enhancer = AIEnhancer(provider="not-a-real-provider")
    assert enhancer.is_configured is False


def test_legacy_api_key_alias_resolves_to_anthropic():
    """
    The original AIEnhancer(api_key=...) call shape (no provider argument)
    predates the provider abstraction and must keep working — it should
    resolve to the Anthropic provider, not silently fall through to the new
    groq default.
    """
    enhancer = AIEnhancer(api_key="sk-ant-fake-legacy-key")
    assert enhancer.is_configured is True
    assert enhancer.provider == "anthropic"


@pytest.mark.asyncio
async def test_polish_summary_noop_when_disabled(sample_metadata, sample_finding):
    enhancer = AIEnhancer()
    base_summary = "Flight health score is 82/100 (Good)."
    result = await enhancer.polish_summary(
        base_summary=base_summary,
        findings=[sample_finding],
        metadata=sample_metadata,
    )
    assert result == base_summary


@pytest.mark.asyncio
async def test_answer_question_noop_when_disabled(sample_metadata, sample_finding):
    enhancer = AIEnhancer()
    report = FlightMDReport(
        report_id="test-id",
        overall_score=82.0,
        score_label="Good",
        letter_grade="B",
        executive_summary="Flight health score is 82/100 (Good).",
        metadata=sample_metadata,
        findings=[sample_finding],
        param_change_sheet=[],
        analyser_results=[],
        processing_time_ms=100,
        file_name="test.ulg",
        file_size_bytes=1024,
    )
    result = await enhancer.answer_question("Why did the battery sag?", report)
    assert result == NOT_CONFIGURED_MESSAGE


@pytest.mark.asyncio
async def test_run_analysis_without_ai_enhancer_param_is_backward_compatible():
    """
    run_analysis() must remain callable exactly as before this phase — the
    ai_enhancer parameter is additive and optional.
    """
    import inspect
    from flightmd_core.orchestrator import run_analysis

    sig = inspect.signature(run_analysis)
    assert "ai_enhancer" in sig.parameters
    assert sig.parameters["ai_enhancer"].default is None
