import json
import logging
import threading
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import Response

from api import airframe_store as afs
from api.config import get_settings
from api.routers.report import finished_report
from api.security import check_airframe_token, limiter
from api.services.pdf_generator import PDFGenerator
from api.storage import job_store, normalise_airframe_label
from flightmd_core.services.geo_export import generate_gpx, generate_kml

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Export"])
settings = get_settings()
pdf_gen = PDFGenerator()

PDF_LIMIT = f"{settings.pdf_rate_limit_per_hour}/hour"

# a finished report never changes, so its PDF can be reused
_pdf_cache: "OrderedDict[str, bytes]" = OrderedDict()
_pdf_cache_lock = threading.Lock()
PDF_CACHE_SIZE = 8


def _attachment(data: bytes, media_type: str, filename: str, ascii_name: Optional[str] = None) -> Response:
    # header values must be latin-1, so an ascii fallback + the real name per RFC 5987
    disposition = f'attachment; filename="{ascii_name or filename}"'
    if ascii_name:
        disposition += f"; filename*=UTF-8''{quote(filename)}"
    return Response(content=data, media_type=media_type, headers={"Content-Disposition": disposition})


def _report_pdf(report) -> bytes:
    with _pdf_cache_lock:
        cached = _pdf_cache.get(report.report_id)
        if cached is not None:
            _pdf_cache.move_to_end(report.report_id)
            return cached
    pdf = pdf_gen.generate(report)
    with _pdf_cache_lock:
        _pdf_cache[report.report_id] = pdf
        while len(_pdf_cache) > PDF_CACHE_SIZE:
            _pdf_cache.popitem(last=False)
    return pdf


# Plain `def` routes on purpose: FastAPI runs them in its threadpool, so
# WeasyPrint and the disk reads don't stall everyone else's /status polling.

@router.get("/export/pdf/{report_id}", summary="Report as PDF")
@limiter.limit(PDF_LIMIT)
def export_pdf(request: Request, report_id: str) -> Response:
    report = finished_report(report_id)
    try:
        pdf_bytes = _report_pdf(report)
    except Exception:
        logger.exception(f"PDF generation failed for {report_id}")
        raise HTTPException(status_code=500, detail="PDF generation failed.")
    return _attachment(pdf_bytes, "application/pdf", f"flightmd_report_{report_id[:8]}.pdf")


@router.get("/export/gpx/{report_id}", summary="GPS track as GPX")
def export_gpx(report_id: str) -> Response:
    report = finished_report(report_id)
    if not report.metadata.gps_path:
        raise HTTPException(status_code=422, detail="This flight log has no GPS track to export.")
    try:
        data = generate_gpx(report)
    except Exception:
        logger.exception(f"GPX generation failed for {report_id}")
        raise HTTPException(status_code=500, detail="GPX generation failed.")
    return _attachment(data, "application/gpx+xml", f"flightmd_track_{report_id[:8]}.gpx")


@router.get("/export/kml/{report_id}", summary="GPS track as KML")
def export_kml(report_id: str) -> Response:
    report = finished_report(report_id)
    if not report.metadata.gps_path:
        raise HTTPException(status_code=422, detail="This flight log has no GPS track to export.")
    try:
        data = generate_kml(report)
    except Exception:
        logger.exception(f"KML generation failed for {report_id}")
        raise HTTPException(status_code=500, detail="KML generation failed.")
    return _attachment(data, "application/vnd.google-earth.kml+xml", f"flightmd_track_{report_id[:8]}.kml")


@router.get(
    "/export/airframe/{label}/pdf",
    summary="Flight and maintenance record for one airframe",
    responses={401: {"description": "Token missing or airframe unclaimed"}, 403: {"description": "Wrong token"}},
)
@limiter.limit(PDF_LIMIT)
def export_airframe_record(
    request: Request,
    label: str,
    x_airframe_token: Optional[str] = Header(None),
) -> Response:
    normalised = normalise_airframe_label(label)
    if not normalised:
        raise HTTPException(status_code=400, detail="Invalid airframe label.")
    check_airframe_token(normalised, x_airframe_token)

    config = afs.airframe_store.get(normalised)
    flights_with_ts = job_store.list_by_airframe_with_created_at(normalised)
    status = afs.compute_maintenance_status(config, flights_with_ts)

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
    except Exception:
        logger.exception("airframe record PDF failed")
        raise HTTPException(status_code=500, detail="PDF generation failed.")

    ascii_name = "".join(c if c.isascii() and c.isalnum() else "_" for c in normalised)
    return _attachment(
        pdf_bytes, "application/pdf",
        f"flightmd_airframe_{normalised}.pdf",
        ascii_name=f"flightmd_airframe_{ascii_name}.pdf",
    )


@router.get("/export/json/{report_id}", summary="Report as a JSON download")
def export_json(report_id: str) -> Response:
    report = finished_report(report_id)
    # passed through as-is, schema_version included, so consumers can check the contract
    body = json.dumps(report.model_dump(mode="json"), indent=2, default=str).encode("utf-8")
    resp = _attachment(body, "application/json", f"flightmd_report_{report_id[:8]}.json")
    resp.headers["X-FlightMD-Schema-Version"] = report.schema_version
    return resp
