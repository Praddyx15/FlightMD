"""
GET /report/{report_id}  — full report JSON
GET /status/{report_id}  — lightweight polling endpoint
"""

from fastapi import APIRouter, HTTPException
from api.storage import job_store

router = APIRouter()


@router.get("/status/{report_id}")
async def get_status(report_id: str) -> dict:
    summary = job_store.status_summary(report_id)
    if summary["status"] == "not_found":
        raise HTTPException(status_code=404, detail="Report not found or expired.")
    return summary


@router.get("/report/{report_id}")
async def get_report(report_id: str):
    job = job_store.get(report_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Report not found or expired.")
    if job.status.value == "processing":
        raise HTTPException(status_code=202, detail="Analysis still in progress.")
    if job.status.value == "failed":
        raise HTTPException(status_code=500, detail=job.error or "Analysis failed.")
    if job.report is None:
        raise HTTPException(status_code=404, detail="Report not found or expired.")
    return job.report.model_dump()
