from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from api.config import get_settings
from api.security import limiter
from api.services import report_qa
from api.storage import JobStatus, job_store
from flightmd_core.services.ai_enhancer import AIEnhancer

router = APIRouter(tags=["Reports"])
settings = get_settings()

NOT_FOUND = "Report not found or expired."


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=report_qa.MAX_QUESTION_CHARS)


def finished_report(report_id: str):
    """The completed report, or the HTTP error that says why there isn't one."""
    job = job_store.get(report_id)
    if job is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    if job.status == JobStatus.PROCESSING:
        raise HTTPException(status_code=202, detail="Analysis still in progress.")
    if job.status == JobStatus.FAILED:
        raise HTTPException(status_code=422, detail=job.error or "Analysis failed.")
    if job.report is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    return job.report


@router.get("/status/{report_id}", summary="Poll analysis progress")
def get_status(report_id: str) -> dict:
    summary = job_store.status_summary(report_id)
    if summary["status"] == "not_found":
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    return summary


@router.get(
    "/report/{report_id}",
    summary="Full report JSON",
    responses={202: {"description": "Still processing"}, 404: {"description": "Unknown or expired"},
               422: {"description": "Analysis failed"}},
)
def get_report(report_id: str):
    report = finished_report(report_id)
    return JSONResponse(
        report.model_dump(mode="json"),
        headers={"X-FlightMD-Schema-Version": report.schema_version},
    )


@router.post("/ask/{report_id}", summary="Ask the optional AI about a finished report")
@limiter.limit(f"{settings.ask_rate_limit_per_hour}/hour")
async def ask_question(request: Request, report_id: str, body: AskRequest) -> dict:
    """Answers only from the report's own data. Without an AI key this returns
    `{"configured": false, "answer": null}` and the frontend falls back to keyword search."""
    report = await run_in_threadpool(finished_report, report_id)

    enhancer = AIEnhancer(
        provider=settings.ai_provider,
        groq_api_key=settings.groq_api_key,
        anthropic_api_key=settings.anthropic_api_key,
    )
    if not enhancer.is_configured:
        return {"configured": False, "answer": None}

    answer = await report_qa.answer(enhancer, body.question, report)
    return {"configured": True, "answer": answer}
