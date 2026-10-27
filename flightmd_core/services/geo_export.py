"""
GPX and KML export of a report's flight path, for Google Earth, QGIS and the like.
Built with ElementTree so names like the file name get XML-escaped.
"""

import math
import xml.etree.ElementTree as ET

from flightmd_core.models.findings import FlightMDReport

GPX_NS = "http://www.topografix.com/GPX/1/1"
KML_NS = "http://www.opengis.net/kml/2.2"


def _alt(point) -> float | None:
    if len(point) > 2 and point[2] is not None and math.isfinite(point[2]):
        return point[2]
    return None


def generate_gpx(report: FlightMDReport) -> bytes:
    """GPX 1.1 with the flight path as one track."""
    path = report.metadata.gps_path or []

    # xmlns as a plain attribute; register_namespace would change ET's global state
    gpx = ET.Element("gpx", version="1.1", creator="FlightMD", xmlns=GPX_NS)
    trk = ET.SubElement(gpx, "trk")
    ET.SubElement(trk, "name").text = report.file_name
    trkseg = ET.SubElement(trk, "trkseg")

    for point in path:
        trkpt = ET.SubElement(trkseg, "trkpt", lat=f"{point[0]:.7f}", lon=f"{point[1]:.7f}")
        alt = _alt(point)
        if alt is not None:
            ET.SubElement(trkpt, "ele").text = f"{alt:.2f}"

    return b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(gpx, encoding="utf-8")


def generate_kml(report: FlightMDReport) -> bytes:
    """KML with the flight path as a LineString."""
    path = report.metadata.gps_path or []

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

    return b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(kml, encoding="utf-8")
