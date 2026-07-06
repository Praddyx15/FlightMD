"""
Tests for GPX/KML flight-path export.
"""

import xml.etree.ElementTree as ET

import pytest

from flightmd_core.models.findings import FlightMDReport
from flightmd_core.models.metadata import FlightMetadata
from flightmd_core.services.geo_export import generate_gpx, generate_kml


def make_report(gps_path=None) -> FlightMDReport:
    meta = FlightMetadata(duration_seconds=120.0, firmware_version="1.14.0", gps_path=gps_path)
    return FlightMDReport(
        report_id="test-id",
        overall_score=85.0,
        score_label="Good",
        letter_grade="B",
        executive_summary="Summary",
        metadata=meta,
        findings=[],
        param_change_sheet=[],
        analyser_results=[],
        processing_time_ms=10,
        file_name="test.ulg",
        file_size_bytes=1024,
    )


PATH = [
    [37.7749, -122.4194, 10.0],
    [37.7750, -122.4195, 15.0],
    [37.7751, -122.4196, 20.0],
]


class TestGPX:
    def test_produces_well_formed_xml(self):
        gpx_bytes = generate_gpx(make_report(PATH))
        root = ET.fromstring(gpx_bytes)
        assert root.tag.endswith("gpx")

    def test_track_points_match_path_length(self):
        gpx_bytes = generate_gpx(make_report(PATH))
        root = ET.fromstring(gpx_bytes)
        trkpts = root.findall(".//{http://www.topografix.com/GPX/1/1}trkpt")
        assert len(trkpts) == len(PATH)

    def test_lat_lon_round_trip(self):
        gpx_bytes = generate_gpx(make_report(PATH))
        root = ET.fromstring(gpx_bytes)
        trkpt = root.find(".//{http://www.topografix.com/GPX/1/1}trkpt")
        assert float(trkpt.get("lat")) == pytest.approx(PATH[0][0], abs=1e-6)
        assert float(trkpt.get("lon")) == pytest.approx(PATH[0][1], abs=1e-6)

    def test_empty_path_produces_valid_document_with_no_points(self):
        gpx_bytes = generate_gpx(make_report(None))
        root = ET.fromstring(gpx_bytes)
        trkpts = root.findall(".//{http://www.topografix.com/GPX/1/1}trkpt")
        assert trkpts == []

    def test_file_name_is_escaped_not_injected(self):
        report = make_report(PATH)
        report.file_name = 'evil"><script>alert(1)</script>'
        gpx_bytes = generate_gpx(report)
        # Must still parse as well-formed XML — proves the unsafe characters
        # were escaped by ElementTree rather than concatenated raw.
        root = ET.fromstring(gpx_bytes)
        name_el = root.find(".//{http://www.topografix.com/GPX/1/1}name")
        assert name_el.text == report.file_name


class TestKML:
    def test_produces_well_formed_xml(self):
        kml_bytes = generate_kml(make_report(PATH))
        root = ET.fromstring(kml_bytes)
        assert root.tag.endswith("kml")

    def test_coordinates_are_lon_lat_alt_order(self):
        kml_bytes = generate_kml(make_report(PATH))
        root = ET.fromstring(kml_bytes)
        coords_el = root.find(".//{http://www.opengis.net/kml/2.2}coordinates")
        first_point = coords_el.text.strip().split(" ")[0]
        lon, lat, alt = (float(v) for v in first_point.split(","))
        assert lon == pytest.approx(PATH[0][1], abs=1e-6)
        assert lat == pytest.approx(PATH[0][0], abs=1e-6)
        assert alt == pytest.approx(PATH[0][2], abs=1e-6)

    def test_empty_path_produces_valid_document(self):
        kml_bytes = generate_kml(make_report(None))
        root = ET.fromstring(kml_bytes)
        coords_el = root.find(".//{http://www.opengis.net/kml/2.2}coordinates")
        assert not coords_el.text
