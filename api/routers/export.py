"""
GET /export/pdf/{report_id}  — returns WeasyPrint-generated PDF
GET /export/json/{report_id} — returns FlightMDReport as downloadable JSON
"""

import json
import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from api.storage import job_store
from api.services.pdf_generator import PDFGenerator

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
