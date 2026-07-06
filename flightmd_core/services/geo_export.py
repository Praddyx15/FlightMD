"""
GPX and KML export of a report's flight path — lets a user open it in
Google Earth, QGIS, or any other GIS/mapping tool. Built with stdlib
xml.etree.ElementTree rather than string concatenation so field values
(file names, etc.) are XML-escaped automatically instead of risking
malformed or injectable output.
"""

import xml.etree.ElementTree as ET

from flightmd_core.models.findings import FlightMDReport

GPX_NS = "http://www.topografix.com/GPX/1/1"
KML_NS = "http://www.opengis.net/kml/2.2"


def generate_gpx(report: FlightMDReport) -> bytes:
    """Return a GPX 1.1 document containing the flight path as a single track."""
    path = report.metadata.gps_path or []

    ET.register_namespace("", GPX_NS)
    gpx = ET.Element("gpx", version="1.1", creator="FlightMD", xmlns=GPX_NS)
    trk = ET.SubElement(gpx, "trk")
    ET.SubElement(trk, "name").text = report.file_name
    trkseg = ET.SubElement(trk, "trkseg")

    for point in path:
        lat, lon = point[0], point[1]
        trkpt = ET.SubElement(trkseg, "trkpt", lat=f"{lat:.7f}", lon=f"{lon:.7f}")
        if len(point) > 2 and point[2] is not None:
            ET.SubElement(trkpt, "ele").text = f"{point[2]:.2f}"

    return b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(gpx, encoding="utf-8")


def generate_kml(report: FlightMDReport) -> bytes:
    """Return a KML document containing the flight path as a LineString."""
    path = report.metadata.gps_path or []

    kml = ET.Element("kml", xmlns=KML_NS)
    doc = ET.SubElement(kml, "Document")
    ET.SubElement(doc, "name").text = report.file_name

    placemark = ET.SubElement(doc, "Placemark")
    ET.SubElement(placemark, "name").text = "Flight Path"
    linestring = ET.SubElement(placemark, "LineString")
    ET.SubElement(linestring, "altitudeMode").text = "relativeToGround"
    ET.SubElement(linestring, "extrude").text = "1"

    coords = " ".join(
        f"{point[1]:.7f},{point[0]:.7f},{(point[2] if len(point) > 2 and point[2] is not None else 0):.2f}"
        for point in path
    )
    ET.SubElement(linestring, "coordinates").text = coords

    return b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(kml, encoding="utf-8")
