"""
GET /report/{report_id}   — full report JSON
GET /status/{report_id}   — lightweight polling endpoint
POST /ask/{report_id}     — optional AI Q&A over a completed report
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.config import get_settings
from api.storage import job_store
from flightmd_core.services.ai_enhancer import AIEnhancer

router = APIRouter()


class AskRequest(BaseModel):
    question: str


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


@router.get("/reports")
async def get_reports():
    return job_store.get_all_reports()


@router.post("/ask/{report_id}")
async def ask_question(report_id: str, body: AskRequest) -> dict:
    """
    Optional AI Q&A over a completed report. If no AI provider is
    configured, returns {"configured": False} so the frontend can fall back
    to local keyword search — this endpoint never requires AI to be set up.
    """
    job = job_store.get(report_id)
    if job is None or job.report is None:
        raise HTTPException(status_code=404, detail="Report not found or expired.")
    if job.status.value != "complete":
        raise HTTPException(status_code=202, detail="Analysis still in progress.")

    settings = get_settings()
    enhancer = AIEnhancer(
        provider=settings.ai_provider,
        groq_api_key=settings.groq_api_key,
        anthropic_api_key=settings.anthropic_api_key,
    )
    if not enhancer.is_configured:
        return {"configured": False, "answer": None}

    answer = await enhancer.answer_question(body.question, job.report)
    return {"configured": True, "answer": answer}
