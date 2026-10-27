"""
What happens to one upload once it is queued: run the engine, store the
report, fire alert webhooks, re-check applied parameter changes and save the
dataset contribution. Shared by the in-process queue and the arq worker.
"""

import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Optional

from fastapi.concurrency import run_in_threadpool

from api import airframe_store as afs
from api import metrics, param_changes
from api.config import get_settings
from api.storage import job_store
from api.training_data_store import training_data_store
from api.webhook_notifier import send_alert_webhook
from flightmd_core.orchestrator import run_analysis
from flightmd_core.services.ai_enhancer import AIEnhancer
from flightmd_core.services.format_detector import UnsupportedFormatError

logger = logging.getLogger(__name__)

# absolute paths (two or more separators); leaves "m/s" and "1/2" alone
_PATHS = re.compile(r"(?<![\w.])(?:[A-Za-z]:)?[\\/](?:[^\s'\"\\/:]+[\\/])+[^\s'\"\\/:]*")


@dataclass
class AnalysisJob:
    # plain fields only: the Redis queue sends this as a dict
    report_id: str
    log_path: str
    file_name: str
    file_size: int
    log_format: str
    airframe_label: Optional[str] = None
    contribute_to_dataset: bool = False
    log_sha256: Optional[str] = None
    planning_brief_sha256: Optional[str] = None


def public_error(e: Exception) -> str:
    """What a client may see about a failed analysis.

    The parsers raise ValueError with a usable message for bad input; anything
    else is our bug, and its text (with temp paths in it) stays in the log.
    """
    if isinstance(e, (ValueError, UnsupportedFormatError)):
        msg = _PATHS.sub("<file>", str(e)).strip()
        return msg[:300] or "The log could not be analysed."
    return "Analysis failed because of an internal error."


def remove_file(path: Optional[str]) -> None:
    if path:
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass


async def run_job(job: AnalysisJob) -> None:
    """Runs one analysis and always removes job.log_path afterwards. Never raises."""
    settings = get_settings()
    outcome = "error"
    try:
        await run_in_threadpool(job_store.update_progress, job.report_id, 1, "Starting analysis…")

        async def on_progress(progress: int, message: str, eta_s: Optional[float] = None):
            await run_in_threadpool(job_store.update_progress, job.report_id, progress, message, eta_s)

        ai_enhancer = AIEnhancer(
            provider=settings.ai_provider,
            groq_api_key=settings.groq_api_key,
            anthropic_api_key=settings.anthropic_api_key,
        )
        started = time.perf_counter()
        report = await run_analysis(
            ulog_path=job.log_path,
            file_name=job.file_name,
            file_size=job.file_size,
            progress_callback=on_progress,
            ai_enhancer=ai_enhancer,
        )
        metrics.observe_duration(job.log_format, time.perf_counter() - started)

        # the orchestrator makes up its own id
        report.report_id = job.report_id
        meta = report.metadata
        if job.log_sha256 and not meta.log_sha256:
            meta.log_sha256 = job.log_sha256
        if job.planning_brief_sha256:
            meta.planning_brief_sha256 = job.planning_brief_sha256

        await run_in_threadpool(job_store.complete, job.report_id, report)
        outcome = "complete"
        logger.info(f"job {job.report_id} complete: {report.overall_score}/100")

        if job.airframe_label:
            await _check_alert_rules(job.airframe_label, job.report_id, report)
            try:
                await run_in_threadpool(param_changes.refresh_pending, job.airframe_label)
            except Exception:
                logger.exception(f"change verification after {job.report_id} failed")

        if job.contribute_to_dataset:
            suffix = os.path.splitext(job.log_path)[1]
            try:
                await run_in_threadpool(
                    training_data_store.save, job.log_path, suffix, job.log_format, report, job.log_sha256
                )
            except Exception as e:
                # the uploader's report is already done; a dataset hiccup mustn't touch it
                logger.error(f"dataset contribution for {job.report_id} not saved: {e}")

    except Exception as e:
        if isinstance(e, (ValueError, UnsupportedFormatError)):
            outcome = "rejected"
            logger.info(f"job {job.report_id} rejected: {e}")
        else:
            logger.error(f"job {job.report_id} failed", exc_info=True)
        try:
            await run_in_threadpool(job_store.fail, job.report_id, public_error(e))
        except Exception:
            logger.exception(f"could not mark job {job.report_id} failed")
    finally:
        metrics.count_analysis(job.log_format, outcome)
        remove_file(job.log_path)


async def _check_alert_rules(airframe_label: str, report_id: str, report) -> None:
    """Fire the airframe's webhook for any breached rule. Never raises."""
    try:
        config = await run_in_threadpool(afs.airframe_store.get, airframe_label)
        if not config.alert_rules or not config.webhook_url:
            return
        triggered = afs.evaluate_alert_rules(report, config.alert_rules)
        if not triggered:
            return
        sent = await run_in_threadpool(
            send_alert_webhook, config.webhook_url, airframe_label, report_id, triggered
        )
        logger.info(f"alert webhook for {report_id} ({len(triggered)} rule(s)): {'sent' if sent else 'failed'}")
    except Exception as e:
        logger.error(f"alert rule check failed for {report_id}: {e}")

