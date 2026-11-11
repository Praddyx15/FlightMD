"""
Finished reports never change, so their PDF/GPX/KML/JSON exports are built
once and kept under <data dir>/exports/<report id>/.

The file name carries the report's schema version and the app version, so a
deploy that changes an exporter doesn't keep serving the old output.
"""

import logging
import os
import re
import shutil
from typing import Any, Callable

from api import db
from api.config import get_settings
from api.fs import write_atomic
from api.storage import REPORT_ID_RE

logger = logging.getLogger(__name__)


def _dir(report_id: str) -> str:
    if not REPORT_ID_RE.match(report_id):
        raise ValueError(f"bad report id {report_id!r}")
    return os.path.join(db.get().data_dir, "exports", report_id)


def _name(kind: str, schema_version: str) -> str:
    tag = re.sub(r"[^A-Za-z0-9.]+", "_", f"{schema_version}-{get_settings().app_version}")
    return f"{kind}-{tag}"


def get_or_build(report, kind: str, build: Callable[[Any], bytes]) -> bytes:
    path = os.path.join(_dir(report.report_id), _name(kind, report.schema_version))
    try:
        with open(path, "rb") as f:
            return f.read()
    except FileNotFoundError:
        pass

    data = build(report)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        write_atomic(path, data)
    except OSError as e:
        # still a good response, it just gets rebuilt next time
        logger.warning(f"could not cache {kind} export for {report.report_id}: {e}")
    return data


def drop(report_id: str) -> None:
    shutil.rmtree(_dir(report_id), ignore_errors=True)
