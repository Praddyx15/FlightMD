"""
Parsed-topic cache, keyed by the log's sha256, so a re-upload, the Q&A, the PDF and the
trends don't parse the same log again.

One gzip'd pickle per log under $FLIGHTMD_DATA_DIR/cache. Pickle is only safe because
nothing but this module ever writes into that directory; never point it at files
someone else can drop in.

Environment:
  FLIGHTMD_DATA_DIR      base directory (default ./data)
  FLIGHTMD_CACHE         1/0 forces the cache on/off (default: on when FLIGHTMD_DATA_DIR is set)
  FLIGHTMD_CACHE_TTL_S   entries older than this are dropped (default 3600)
  FLIGHTMD_CACHE_MAX_MB  total size cap; oldest go first (default 1024)
"""

import gzip
import logging
import os
import pickle
import re
import tempfile
import time
from pathlib import Path
from typing import Optional

import pandas as pd

from flightmd_core.models.metadata import FlightMetadata

logger = logging.getLogger(__name__)

# bump when a parser change makes old entries wrong
CACHE_VERSION = 2

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SUFFIX = f".v{CACHE_VERSION}.pkl.gz"


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


def _drop(p: Path) -> None:
    # on Windows a file another process has open can't be deleted; next prune gets it
    try:
        p.unlink(missing_ok=True)
    except OSError:
        pass


def enabled() -> bool:
    flag = os.environ.get("FLIGHTMD_CACHE", "").strip().lower()
    if flag:
        return flag not in ("0", "false", "no", "off")
    # on by default only where someone chose a data dir (the API does); a CLI run
    # shouldn't leave a ./data folder behind
    return bool(os.environ.get("FLIGHTMD_DATA_DIR"))


def cache_dir() -> Path:
    return Path(os.environ.get("FLIGHTMD_DATA_DIR") or "data") / "cache"


def _path(sha256: str) -> Path:
    if not _SHA256.match(sha256 or ""):
        raise ValueError(f"not a sha256 hex digest: {sha256!r}")
    return cache_dir() / f"{sha256}{_SUFFIX}"


def get(sha256: str) -> Optional[tuple[dict[str, pd.DataFrame], dict[str, float], FlightMetadata]]:
    """(topics, params, metadata) as the parser returned them, or None."""
    if not enabled():
        return None
    p = _path(sha256)
    try:
        age = time.time() - p.stat().st_mtime
        if age > _env_float("FLIGHTMD_CACHE_TTL_S", 3600):
            _drop(p)
            return None
        with gzip.open(p, "rb") as f:
            entry = pickle.load(f)
    except FileNotFoundError:
        return None
    except (OSError, EOFError, pickle.UnpicklingError, AttributeError, ImportError) as e:
        # half-written by a crashed process, or from an older FlightMD
        logger.warning(f"dropping unreadable cache entry {p.name}: {e}")
        _drop(p)
        return None

    try:
        os.utime(p)
    except OSError:
        pass
    return entry["topics"], entry["params"], FlightMetadata.model_validate(entry["metadata"])


def put(sha256: str, topics, params, metadata: FlightMetadata) -> None:
    if not enabled():
        return
    p = _path(sha256)
    p.parent.mkdir(parents=True, exist_ok=True)
    entry = {"topics": topics, "params": params, "metadata": metadata.model_dump()}

    # write next to it and rename, so a reader never sees half a file
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".tmp-", suffix=".pkl.gz")
    try:
        with os.fdopen(fd, "wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", compresslevel=3) as f:
            pickle.dump(entry, f, protocol=pickle.HIGHEST_PROTOCOL)
        os.replace(tmp, p)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    prune()


def prune() -> None:
    """Drop expired entries, then the oldest until the total is under the cap."""
    d = cache_dir()
    if not d.is_dir():
        return
    ttl = _env_float("FLIGHTMD_CACHE_TTL_S", 3600)
    cap = _env_float("FLIGHTMD_CACHE_MAX_MB", 1024) * 1e6
    now = time.time()

    entries = []
    for p in d.iterdir():
        try:
            st = p.stat()
        except FileNotFoundError:
            continue
        stale_tmp = p.name.startswith(".tmp-") and now - st.st_mtime > 3600
        expired = p.name.endswith(".pkl.gz") and not p.name.startswith(".tmp-") and (
            now - st.st_mtime > ttl or not p.name.endswith(_SUFFIX))
        if stale_tmp or expired:
            _drop(p)
        elif p.name.endswith(_SUFFIX):
            entries.append((st.st_mtime, st.st_size, p))

    total = sum(size for _, size, _ in entries)
    for _, size, p in sorted(entries, key=lambda e: e[0]):
        if total <= cap:
            break
        _drop(p)
        total -= size
