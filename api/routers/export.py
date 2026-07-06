"""
GET /export/pdf/{report_id}       — returns WeasyPrint-generated PDF
GET /export/json/{report_id}      — returns FlightMDReport as downloadable JSON
GET /export/gpx/{report_id}       — returns flight path as GPX track
GET /export/kml/{report_id}       — returns flight path as KML LineString
GET /export/airframe/{label}/pdf  — flight/maintenance record for one airframe
"""

import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from api.airframe_store import airframe_store, compute_maintenance_status
from api.storage import job_store, normalise_airframe_label
from api.services.pdf_generator import PDFGenerator
from flightmd_core.services.geo_export import generate_gpx, generate_kml

logger = logging.getLogger(__name__)
router = APIRouter()
pdf_gen = PDFGenerator()


@router.get("/export/pdf/{report_id}")
async def export_pdf(report_id: str) -> Response:
    job = job_store.get(report_id)
    if job is None or job.report is None:
        raise HTTPException(status_code=404, detail="Report not found or expired.")
    if job.status.value != "complete":
        raise HTTPException(status_code=202, detail="Analysis still in progress.")

    try:
        pdf_bytes = pdf_gen.generate(job.report)
    except Exception as e:
        logger.error(f"PDF generation failed for {report_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="PDF generation failed.")

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="flightmd_report_{report_id[:8]}.pdf"'
        },
    )


@router.get("/export/gpx/{report_id}")
async def export_gpx(report_id: str) -> Response:
    job = job_store.get(report_id)
    if job is None or job.report is None:
        raise HTTPException(status_code=404, detail="Report not found or expired.")
    if job.status.value != "complete":
        raise HTTPException(status_code=202, detail="Analysis still in progress.")
    if not job.report.metadata.gps_path:
        raise HTTPException(status_code=422, detail="This flight log has no GPS track to export.")

    try:
        gpx_bytes = generate_gpx(job.report)
    except Exception as e:
        logger.error(f"GPX generation failed for {report_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="GPX generation failed.")

    return Response(
        content=gpx_bytes,
        media_type="application/gpx+xml",
        headers={
            "Content-Disposition": f'attachment; filename="flightmd_track_{report_id[:8]}.gpx"'
        },
    )


@router.get("/export/kml/{report_id}")
async def export_kml(report_id: str) -> Response:
    job = job_store.get(report_id)
    if job is None or job.report is None:
        raise HTTPException(status_code=404, detail="Report not found or expired.")
    if job.status.value != "complete":
        raise HTTPException(status_code=202, detail="Analysis still in progress.")
    if not job.report.metadata.gps_path:
        raise HTTPException(status_code=422, detail="This flight log has no GPS track to export.")

    try:
        kml_bytes = generate_kml(job.report)
    except Exception as e:
        logger.error(f"KML generation failed for {report_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="KML generation failed.")

    return Response(
        content=kml_bytes,
        media_type="application/vnd.google-earth.kml+xml",
        headers={
            "Content-Disposition": f'attachment; filename="flightmd_track_{report_id[:8]}.kml"'
        },
    )


@router.get("/export/airframe/{label}/pdf")
async def export_airframe_record(label: str) -> Response:
    normalised = normalise_airframe_label(label)
    if not normalised:
        raise HTTPException(status_code=400, detail="Invalid airframe label.")

    config = airframe_store.get(normalised)
    flights_with_ts = job_store.list_by_airframe_with_created_at(normalised)
    status = compute_maintenance_status(config, flights_with_ts)

    flights = [
        {
            "date": datetime.fromtimestamp(created_at, tz=timezone.utc).strftime("%Y-%m-%d"),
            "file_name": r.file_name,
            "duration_minutes": round(r.metadata.duration_seconds / 60, 1),
            "overall_score": round(r.overall_score),
            "letter_grade": r.letter_grade,
        }
        for created_at, r in flights_with_ts
    ]

    try:
        pdf_bytes = pdf_gen.generate_airframe_record(
            airframe_label=normalised,
            flights=flights,
            config=config,
            total_flight_hours=status["total_flight_hours"],
            hours_since_maintenance=status["hours_since_maintenance"],
            maintenance_due=status["maintenance_due"],
        )
    except Exception as e:
        logger.error(f"Airframe record PDF generation failed for {normalised!r}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="PDF generation failed.")

    safe_name = "".join(c if c.isalnum() else "_" for c in normalised)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="flightmd_airframe_{safe_name}.pdf"'
        },
    )


@router.get("/export/json/{report_id}")
async def export_json(report_id: str) -> Response:
    job = job_store.get(report_id)
    if job is None or job.report is None:
        raise HTTPException(status_code=404, detail="Report not found or expired.")
    if job.status.value != "complete":
        raise HTTPException(status_code=202, detail="Analysis still in progress.")

    json_bytes = json.dumps(job.report.model_dump(), indent=2, default=str).encode("utf-8")

    return Response(
        content=json_bytes,
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="flightmd_report_{report_id[:8]}.json"'
        },
    )
