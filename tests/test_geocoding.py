"""
Tests for reverse geocoding — must never raise, and must degrade to None
on any network/parse failure since it's a nice-to-have enrichment, not a
required field.
"""

import urllib.error

from flightmd_core.services import geocoding


class TestReverseGeocode:
    def test_missing_coordinates_returns_none(self):
        assert geocoding.reverse_geocode(0.0, 0.0) is None
        assert geocoding.reverse_geocode(None, None) is None

    def test_network_failure_returns_none_not_raise(self, monkeypatch):
        def raise_error(*args, **kwargs):
            raise urllib.error.URLError("no network")
        monkeypatch.setattr(geocoding.urllib.request, "urlopen", raise_error)
        assert geocoding.reverse_geocode(37.7749, -122.4194) is None

    def test_prefers_city_and_country(self, monkeypatch):
        class FakeResponse:
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False
            def read(self):
                import json
                return json.dumps({
                    "address": {"city": "San Francisco", "country": "United States"},
                    "display_name": "fallback",
                }).encode("utf-8")
        monkeypatch.setattr(geocoding.urllib.request, "urlopen", lambda *a, **k: FakeResponse())
        assert geocoding.reverse_geocode(37.7749, -122.4194) == "San Francisco, United States"

    def test_falls_back_to_display_name(self, monkeypatch):
        class FakeResponse:
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False
            def read(self):
                import json
                return json.dumps({"address": {}, "display_name": "Somewhere remote"}).encode("utf-8")
        monkeypatch.setattr(geocoding.urllib.request, "urlopen", lambda *a, **k: FakeResponse())
        assert geocoding.reverse_geocode(1.23, 4.56) == "Somewhere remote"

    def test_malformed_response_returns_none(self, monkeypatch):
        class FakeResponse:
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False
            def read(self):
                return b"not json"
        monkeypatch.setattr(geocoding.urllib.request, "urlopen", lambda *a, **k: FakeResponse())
        assert geocoding.reverse_geocode(37.7749, -122.4194) is None
