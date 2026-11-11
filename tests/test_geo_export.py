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


def test_nan_altitude_is_left_out():
    path = [[37.7749, -122.4194, float("nan")], [37.7750, -122.4195, 15.0]]
    root = ET.fromstring(generate_gpx(make_report(path)))
    eles = root.findall(".//{http://www.topografix.com/GPX/1/1}ele")
    assert [e.text for e in eles] == ["15.00"]

    kml = ET.fromstring(generate_kml(make_report(path)))
    coords = kml.find(".//{http://www.opengis.net/kml/2.2}coordinates").text
    assert "nan" not in coords


GPX = "{http://www.topografix.com/GPX/1/1}"
KML = "{http://www.opengis.net/kml/2.2}"


def timed_report(start="2026-10-01T09:12:33Z"):
    report = make_report(PATH)
    report.metadata.log_start_utc = start
    report.metadata.gps_path_t_s = [10.0, 10.5, 11.25]
    report.metadata.gps_path_hdop = [0.8, None, 1.2]
    report.metadata.gps_path_wind_speed_ms = [3.5, 4.0, None]
    return report


def test_gpx_time_per_point():
    root = ET.fromstring(generate_gpx(timed_report()))
    times = [e.text for e in root.iter(f"{GPX}time")]
    assert times == ["2026-10-01T09:12:43.000Z", "2026-10-01T09:12:43.500Z", "2026-10-01T09:12:44.250Z"]


def test_gpx_time_comes_after_ele():
    root = ET.fromstring(generate_gpx(timed_report()))
    trkpt = root.find(f".//{GPX}trkpt")
    assert [c.tag for c in trkpt] == [f"{GPX}ele", f"{GPX}time"]


def test_gpx_no_time_without_utc_start():
    report = timed_report()
    report.metadata.log_start_utc = None
    root = ET.fromstring(generate_gpx(report))
    assert list(root.iter(f"{GPX}time")) == []


def test_gpx_no_time_when_lengths_disagree():
    report = timed_report()
    report.metadata.gps_path_t_s = [10.0]
    root = ET.fromstring(generate_gpx(report))
    assert list(root.iter(f"{GPX}time")) == []


def test_kml_points_carry_hdop_wind_and_time():
    root = ET.fromstring(generate_kml(timed_report()))
    folder = root.find(f".//{KML}Folder")
    points = folder.findall(f"{KML}Placemark")
    assert len(points) == len(PATH)

    def data(pm):
        return {d.get("name"): float(d.find(f"{KML}value").text) for d in pm.iter(f"{KML}Data")}

    assert data(points[0]) == {"t_s": 10.0, "hdop": 0.8, "wind_speed_ms": 3.5}
    # missing readings are left out, not written as 0
    assert data(points[1]) == {"t_s": 10.5, "wind_speed_ms": 4.0}
    assert data(points[2]) == {"t_s": 11.25, "hdop": 1.2}
    assert points[0].find(f"{KML}TimeStamp/{KML}when").text == "2026-10-01T09:12:43.000Z"
    # the line is still the first coordinates element
    first = root.find(f".//{KML}coordinates").text.split(" ")[0]
    assert float(first.split(",")[0]) == pytest.approx(PATH[0][1])


def test_kml_without_point_data_has_no_folder():
    root = ET.fromstring(generate_kml(make_report(PATH)))
    assert root.find(f".//{KML}Folder") is None
