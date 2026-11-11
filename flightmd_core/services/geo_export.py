"""
GPX and KML export of a report's flight path, for Google Earth, QGIS and the like.
Built with ElementTree so names like the file name get XML-escaped.
"""

import math
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from typing import Optional

from flightmd_core.models.findings import FlightMDReport

GPX_NS = "http://www.topografix.com/GPX/1/1"
KML_NS = "http://www.opengis.net/kml/2.2"


def _alt(point) -> float | None:
    if len(point) > 2 and point[2] is not None and math.isfinite(point[2]):
        return point[2]
    return None


def _at(values, i):
    if values is None or i >= len(values):
        return None
    v = values[i]
    return v if v is not None and math.isfinite(v) else None


def _point_times(report: FlightMDReport) -> list[Optional[datetime]]:
    """UTC time of each path point; all None when the log has no absolute time."""
    md = report.metadata
    path = md.gps_path or []
    t_s = md.gps_path_t_s
    if not md.log_start_utc or not t_s or len(t_s) != len(path):
        return [None] * len(path)
    start = datetime.strptime(md.log_start_utc, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return [start + timedelta(seconds=t) if t is not None else None for t in t_s]


def _iso(t: datetime) -> str:
    # GPX and KML both take xsd:dateTime; ms is plenty
    return t.strftime("%Y-%m-%dT%H:%M:%S.") + f"{t.microsecond // 1000:03d}Z"


def generate_gpx(report: FlightMDReport) -> bytes:
    """GPX 1.1 with the flight path as one track; <time> per point when the log
    has an absolute start time."""
    path = report.metadata.gps_path or []
    times = _point_times(report)

    # xmlns as a plain attribute; register_namespace would change ET's global state
    gpx = ET.Element("gpx", version="1.1", creator="FlightMD", xmlns=GPX_NS)
    trk = ET.SubElement(gpx, "trk")
    ET.SubElement(trk, "name").text = report.file_name
    trkseg = ET.SubElement(trk, "trkseg")

    for point, t in zip(path, times):
        trkpt = ET.SubElement(trkseg, "trkpt", lat=f"{point[0]:.7f}", lon=f"{point[1]:.7f}")
        # GPX wants ele before time
        alt = _alt(point)
        if alt is not None:
            ET.SubElement(trkpt, "ele").text = f"{alt:.2f}"
        if t is not None:
            ET.SubElement(trkpt, "time").text = _iso(t)

    return b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(gpx, encoding="utf-8")


def generate_kml(report: FlightMDReport) -> bytes:
    """KML with the flight path as a LineString, plus a hidden folder of the path
    points carrying HDOP and wind as ExtendedData."""
    md = report.metadata
    path = md.gps_path or []
    times = _point_times(report)

    kml = ET.Element("kml", xmlns=KML_NS)
    doc = ET.SubElement(kml, "Document")
    ET.SubElement(doc, "name").text = report.file_name

    placemark = ET.SubElement(doc, "Placemark")
    ET.SubElement(placemark, "name").text = "Flight Path"
    linestring = ET.SubElement(placemark, "LineString")
    ET.SubElement(linestring, "altitudeMode").text = "relativeToGround"
    ET.SubElement(linestring, "extrude").text = "1"

    # KML wants lon,lat,alt - yes, backwards
    coords = " ".join(f"{p[1]:.7f},{p[0]:.7f},{(_alt(p) or 0):.2f}" for p in path)
    ET.SubElement(linestring, "coordinates").text = coords

    if path and (md.gps_path_hdop or md.gps_path_wind_speed_ms or md.gps_path_t_s):
        folder = ET.SubElement(doc, "Folder")
        ET.SubElement(folder, "name").text = "Path points"
        # 500 pins would bury the line; they're there for the data
        ET.SubElement(folder, "visibility").text = "0"
        for i, p in enumerate(path):
            pm = ET.SubElement(folder, "Placemark")
            ET.SubElement(pm, "visibility").text = "0"
            t = times[i]
            if t is not None:
                ET.SubElement(ET.SubElement(pm, "TimeStamp"), "when").text = _iso(t)
            ext = ET.SubElement(pm, "ExtendedData")
            for name, value in [
                ("t_s", _at(md.gps_path_t_s, i)),
                ("hdop", _at(md.gps_path_hdop, i)),
                ("wind_speed_ms", _at(md.gps_path_wind_speed_ms, i)),
            ]:
                if value is not None:
                    data = ET.SubElement(ext, "Data", name=name)
                    ET.SubElement(data, "value").text = f"{value:g}"
            pt = ET.SubElement(pm, "Point")
            ET.SubElement(pt, "altitudeMode").text = "relativeToGround"
            ET.SubElement(pt, "coordinates").text = f"{p[1]:.7f},{p[0]:.7f},{(_alt(p) or 0):.2f}"

    return b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(kml, encoding="utf-8")
