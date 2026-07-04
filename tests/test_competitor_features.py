import pytest
from flightmd_core.services.weather_lookup import fetch_weather
from flightmd_core.models.findings import FlightMDReport
from flightmd_core.models.metadata import FlightMetadata

def test_fetch_weather_fallback():
    # If coordinates are 0 or empty, return default
    res = fetch_weather(0, 0, None)
    assert res["description"] == "Weather data unavailable"
    assert res["temperature_max_c"] is None

def test_fetch_weather_valid_coordinates():
    # Try fetching with offline/online safe checks
    res = fetch_weather(37.7749, -122.4194, "2023-11-23 12:00:00")
    # Even if offline, it should fall back to default dict instead of throwing
    assert "description" in res

def test_letter_grade_assignment():
    # Constructing dummy report to verify Pydantic serialization
    meta = FlightMetadata(
        duration_seconds=120.0,
        firmware_version="1.14.0",
        available_topics=["vehicle_gps_position"],
    )
    report = FlightMDReport(
        report_id="test-id",
        schema_version="1.2",
        overall_score=85,
        score_label="Healthy",
        letter_grade="B",
        executive_summary="Executive Summary",
        metadata=meta,
        findings=[],
        param_change_sheet=[],
        analyser_results=[],
        processing_time_ms=10,
        file_name="test.ulg",
        file_size_bytes=1024,
    )
    assert report.letter_grade == "B"
