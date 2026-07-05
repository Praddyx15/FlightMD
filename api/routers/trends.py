"""
GET /trends/{airframe_label}   — cross-flight trend history for a tagged airframe
GET /diff                      — side-by-side comparison of two flights

Both endpoints are read-only views over data that already exists in the
job store — no new analysis runs here, just reshaping already-computed
reports for charting/comparison.
"""

from fastapi import APIRouter, HTTPException, Query

from api.storage import job_store
from flightmd_core.models.findings import FlightMDReport

router = APIRouter()


@router.get("/trends/{airframe_label}")
async def get_trends(airframe_label: str) -> dict:
    """
    Time-series of overall score, per-module health score, and per-module
    key_metrics across every flight tagged with this airframe label —
    oldest first. Only flights explicitly tagged at upload time are
    included; untagged (ephemeral) reports never appear here.
    """
    flights_with_ts = job_store.list_by_airframe_with_created_at(airframe_label)
    if not flights_with_ts:
        return {"airframe_label": airframe_label, "flight_count": 0, "flights": []}

    flights = []
    for created_at, report in flights_with_ts:
        module_scores = {ar.analyser: ar.health_score for ar in report.analyser_results}
        key_metrics = {
            f"{ar.analyser}.{metric_name}": value
            for ar in report.analyser_results
            for metric_name, value in ar.key_metrics.items()
        }
        flights.append({
            "report_id": report.report_id,
            "file_name": report.file_name,
            "created_at": created_at,
            "overall_score": report.overall_score,
            "letter_grade": report.letter_grade,
            "module_scores": module_scores,
            "key_metrics": key_metrics,
        })

    return {
        "airframe_label": airframe_label,
        "flight_count": len(flights),
        "flights": flights,
    }


@router.get("/diff")
async def get_diff(a: str = Query(...), b: str = Query(...)) -> dict:
    """
    Compare two flights: score deltas, which findings are new/resolved/
    persisting between them, and how each shared parameter recommendation
    changed. `a` is treated as the "before" flight, `b` as "after" — handy
    for checking whether a tuning change actually helped.
    """
    if a == b:
        raise HTTPException(status_code=400, detail="Cannot diff a report against itself.")

    job_a = job_store.get(a)
    job_b = job_store.get(b)
    if job_a is None or job_a.report is None:
        raise HTTPException(status_code=404, detail=f"Report {a} not found or expired.")
    if job_b is None or job_b.report is None:
        raise HTTPException(status_code=404, detail=f"Report {b} not found or expired.")

    report_a, report_b = job_a.report, job_b.report

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


def _module_score_deltas(a: FlightMDReport, b: FlightMDReport) -> dict:
    scores_a = {ar.analyser: ar.health_score for ar in a.analyser_results}
    scores_b = {ar.analyser: ar.health_score for ar in b.analyser_results}
    all_modules = sorted(set(scores_a) | set(scores_b))
    return {
        module: {
            "a": scores_a.get(module),
            "b": scores_b.get(module),
            "delta": (
                round(scores_b[module] - scores_a[module], 2)
                if module in scores_a and module in scores_b else None
            ),
        }
        for module in all_modules
    }


def _key_metric_deltas(a: FlightMDReport, b: FlightMDReport) -> dict:
    metrics_a = {
        f"{ar.analyser}.{k}": v for ar in a.analyser_results for k, v in ar.key_metrics.items()
    }
    metrics_b = {
        f"{ar.analyser}.{k}": v for ar in b.analyser_results for k, v in ar.key_metrics.items()
    }
    all_keys = sorted(set(metrics_a) | set(metrics_b))
    return {
        key: {
            "a": metrics_a.get(key),
            "b": metrics_b.get(key),
            "delta": (
                round(metrics_b[key] - metrics_a[key], 4)
                if key in metrics_a and key in metrics_b else None
            ),
        }
        for key in all_keys
    }


def _findings_diff(a: FlightMDReport, b: FlightMDReport) -> dict:
    """
    Findings are matched by (category, title) — titles include the
    specific frequency/value, so this is closer to "same finding
    recurring" than a loose category match. Anything in A but not B
    is resolved; anything in B but not A is new; anything in both
    (by category, since exact titles rarely repeat) is left for the
    caller to eyeball via the raw finding lists.
    """
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
