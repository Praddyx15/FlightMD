import json

import pytest

from flightmd_core.services import weather_lookup


class FakeResponse:
    def __init__(self, body):
        self._body = json.dumps(body).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._body


def daily(temp_max=30.0, temp_min=20.0, wind_kmh=18.0, rain=0.0):
    return {"daily": {
        "temperature_2m_max": [temp_max],
        "temperature_2m_min": [temp_min],
        "wind_speed_10m_max": [wind_kmh],
        "rain_sum": [rain],
    }}


@pytest.fixture
def urls(monkeypatch):
    seen = []

    def fake_urlopen(req, timeout=None):
        seen.append(req.full_url)
        return FakeResponse(responses.pop(0))

    responses = []
    monkeypatch.setattr(weather_lookup.urllib.request, "urlopen", fake_urlopen)
    return seen, responses


def test_no_flight_date_means_no_lookup(urls):
    seen, _ = urls
    res = weather_lookup.fetch_weather(37.77, -122.42, None)
    assert res["description"] == "Weather data unavailable"
    assert seen == []


def test_uses_the_flight_date(urls):
    seen, responses = urls
    responses.append(daily())
    res = weather_lookup.fetch_weather(37.77, -122.42, "2026-10-01T09:12:33Z")

    assert "start_date=2026-10-01&end_date=2026-10-01" in seen[0]
    assert res["wind_speed_max_ms"] == pytest.approx(5.0)
    assert res["description"].endswith("Dry")


def test_unknown_rain_is_not_reported_as_dry(urls):
    _, responses = urls
    responses.append(daily(rain=None))
    res = weather_lookup.fetch_weather(37.77, -122.42, "2026-10-01T09:12:33Z")
    assert "Dry" not in res["description"]
    assert res["rain_sum_mm"] is None


def test_recent_flight_falls_back_to_forecast_api(urls):
    seen, responses = urls
    responses.append(daily(temp_max=None, temp_min=None, wind_kmh=None, rain=None))  # archive not there yet
    responses.append(daily(temp_max=25.0))
    res = weather_lookup.fetch_weather(37.77, -122.42, "2026-10-26T09:00:00Z")

    assert "api.open-meteo.com/v1/forecast" in seen[1]
    assert res["temperature_max_c"] == 25.0


def test_equator_and_meridian_are_real_places(urls):
    seen, responses = urls
    responses.append(daily())
    weather_lookup.fetch_weather(0.0, 32.5, "2026-10-01T09:12:33Z")
    assert len(seen) == 1
