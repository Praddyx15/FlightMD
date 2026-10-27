"""Read-only views over finished reports: one airframe's history, and a two-flight diff."""

from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query

from api.routers.report import finished_report
from api.security import check_airframe_token
from api.storage import job_store, normalise_airframe_label
from flightmd_core.models.findings import FlightMDReport

router = APIRouter(tags=["Trends"])


def _module_score(ar) -> Optional[float]:
    # a skipped or unassessed module has no score; 100 would plot as "perfect"
    if ar.skipped or getattr(ar, "assessed", True) is False:
        return None
    return ar.health_score


def _module_scores(report: FlightMDReport) -> dict:
    return {ar.analyser: _module_score(ar) for ar in report.analyser_results}


def _key_metrics(report: FlightMDReport) -> dict:
    return {
        f"{ar.analyser}.{k}": v
        for ar in report.analyser_results
        for k, v in ar.key_metrics.items()
    }


@router.get(
    "/trends/{airframe_label}",
    summary="Score and metric history for one airframe",
    responses={401: {"description": "Token missing or airframe unclaimed"}, 403: {"description": "Wrong token"}},
)
def get_trends(airframe_label: str, x_airframe_token: Optional[str] = Header(None)) -> dict:
    """Every flight tagged with this airframe at upload, oldest first. Needs X-Airframe-Token."""
    label = normalise_airframe_label(airframe_label)
    if not label:
        raise HTTPException(status_code=400, detail="Invalid airframe label.")
    check_airframe_token(label, x_airframe_token)

    flights = [
        {
            "report_id": report.report_id,
            "file_name": report.file_name,
            "created_at": created_at,
            "overall_score": report.overall_score,
            "letter_grade": report.letter_grade,
            "module_scores": _module_scores(report),
            "key_metrics": _key_metrics(report),
        }
        for created_at, report in job_store.list_by_airframe_with_created_at(label)
    ]
    return {"airframe_label": label, "flight_count": len(flights), "flights": flights}


@router.get("/diff", summary="Compare two flights")
def get_diff(a: str = Query(...), b: str = Query(...)) -> dict:
    """`a` is the "before" flight and `b` the "after": score deltas, new and
    resolved findings, and how each shared metric moved."""
    if a == b:
        raise HTTPException(status_code=400, detail="Cannot diff a report against itself.")

    report_a = finished_report(a)
    report_b = finished_report(b)

    return {
        "a": _flight_summary(report_a),
        "b": _flight_summary(report_b),
        "overall_score_delta": round(report_b.overall_score - report_a.overall_score, 2),
        "module_score_deltas": _module_score_deltas(report_a, report_b),
        "findings_diff": _findings_diff(report_a, report_b),
        "key_metric_deltas": _key_metric_deltas(report_a, report_b),
    }


def _flight_summary(report: FlightMDReport) -> dict:
    return {
        "report_id": report.report_id,
        "file_name": report.file_name,
        "overall_score": report.overall_score,
        "letter_grade": report.letter_grade,
        "score_label": report.score_label,
    }


def _deltas(before: dict, after: dict, ndigits: int) -> dict:
    out = {}
    for key in sorted(set(before) | set(after)):
        va, vb = before.get(key), after.get(key)
        out[key] = {
            "a": va,
            "b": vb,
            "delta": round(vb - va, ndigits) if va is not None and vb is not None else None,
        }
    return out


def _module_score_deltas(a: FlightMDReport, b: FlightMDReport) -> dict:
    return _deltas(_module_scores(a), _module_scores(b), 2)


def _key_metric_deltas(a: FlightMDReport, b: FlightMDReport) -> dict:
    return _deltas(_key_metrics(a), _key_metrics(b), 4)


def _findings_diff(a: FlightMDReport, b: FlightMDReport) -> dict:
    # Titles carry the specific value ("... at 1.1 Hz"), so matching on title is
    # close to "same finding again". Same category in both is listed separately.
    titles_a = {f.title for f in a.findings}
    titles_b = {f.title for f in b.findings}

    resolved = [f.title for f in a.findings if f.title not in titles_b]
    new      = [f.title for f in b.findings if f.title not in titles_a]

    categories_a = {f.category.value: f.severity.value for f in a.findings}
    categories_b = {f.category.value: f.severity.value for f in b.findings}
    persisting_categories = [
        {"category": cat, "severity_a": categories_a[cat], "severity_b": categories_b[cat]}
        for cat in sorted(set(categories_a) & set(categories_b))
    ]

    return {
        "resolved": resolved,
        "new": new,
        "persisting_categories": persisting_categories,
    }
