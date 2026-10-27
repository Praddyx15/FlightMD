"""
Prompt building for POST /ask.

The model only sees the report JSON. Strings in it come from the uploaded log
(param names, firmware strings, mode names), so every one goes through
clean_text() before it's embedded, and the whole thing is size-capped.
"""

import json
import logging

from flightmd_core.services.ai_enhancer import SYSTEM_PROMPT, clean_text

logger = logging.getLogger(__name__)

MAX_QUESTION_CHARS = 500
MAX_CONTEXT_CHARS = 24_000
MAX_STRING_CHARS = 400

NOT_IN_REPORT = "Not in this report."
CALL_FAILED = "The AI assistant couldn't answer that just now. Try the keyword search instead."

# bulky or identifying, and never needed to answer a question
_DROP_META = (
    "gps_path", "gps_path_wind_speed_ms", "gps_path_hdop", "available_topics",
    "location_name", "armed_windows",
)

QA_SYSTEM = SYSTEM_PROMPT + (
    " Answer the question using only facts in the report. If the report does not "
    f"contain the answer, reply exactly: {NOT_IN_REPORT} Quote numbers as the report "
    "gives them, with their units. Plain text, five sentences at most, no markdown."
)


def _clean(value):
    if isinstance(value, str):
        return clean_text(value, limit=MAX_STRING_CHARS)
    if isinstance(value, dict):
        return {clean_text(k, limit=80): _clean(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    return value


def report_context(report) -> str:
    data = report.model_dump(mode="json")
    data.pop("file_name", None)
    meta = data.get("metadata") or {}
    for key in _DROP_META:
        meta.pop(key, None)
    for f in data.get("findings", []):
        f.pop("chart_data", None)
    # per-module findings repeat the top-level list
    for ar in data.get("analyser_results", []):
        ar["finding_count"] = len(ar.pop("findings", None) or [])

    data = _clean(data)
    text = json.dumps(data, separators=(",", ":"))
    # findings come sorted worst first, so trim from the end
    while len(text) > MAX_CONTEXT_CHARS and data.get("findings"):
        data["findings"].pop()
        data["findings_truncated"] = True
        text = json.dumps(data, separators=(",", ":"))
    return text[:MAX_CONTEXT_CHARS]


def build_prompt(question: str, report) -> str:
    q = clean_text(question, limit=MAX_QUESTION_CHARS)
    return f"<report>\n{report_context(report)}\n</report>\n\nQuestion: {q}"


async def answer(enhancer, question: str, report) -> str:
    try:
        text = await enhancer.complete(build_prompt(question, report), max_tokens=400, system=QA_SYSTEM)
    except Exception as e:
        # provider outage, quota, bad key: the user gets the fallback text
        logger.warning(f"Q&A call failed: {type(e).__name__}")
        return CALL_FAILED
    return (text or "").strip() or NOT_IN_REPORT
