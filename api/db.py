"""
One SQLite database for everything the API keeps: reports and their job
state, airframes, dataset contributions and applied parameter changes.

stdlib sqlite3 in WAL mode, one connection per thread. The SQL sticks to what
Postgres accepts too (ON CONFLICT upserts, plain column types, no INSERT OR
REPLACE), so moving there later is a driver swap plus "?" -> "%s".
"""

import logging
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from typing import Optional

logger = logging.getLogger(__name__)

DB_NAME = "flightmd.db"

# (version, statements). Append only; a shipped migration never changes.
MIGRATIONS: list[tuple[int, list[str]]] = [
    (1, [
        """CREATE TABLE reports (
            report_id      TEXT PRIMARY KEY,
            status         TEXT NOT NULL,
            progress       INTEGER NOT NULL DEFAULT 0,
            message        TEXT NOT NULL DEFAULT '',
            eta_at         REAL,
            error          TEXT,
            airframe_label TEXT,
            log_format     TEXT,
            log_sha256     TEXT,
            brief_sha256   TEXT,
            created_at     REAL NOT NULL,
            updated_at     REAL NOT NULL,
            report_json    TEXT
        )""",
        "CREATE INDEX reports_airframe ON reports (airframe_label, created_at)",
        "CREATE INDEX reports_log_sha256 ON reports (log_sha256)",
        "CREATE INDEX reports_status ON reports (status, created_at)",
        """CREATE TABLE airframes (
            label       TEXT PRIMARY KEY,
            token_hash  TEXT,
            config_json TEXT NOT NULL,
            created_at  REAL NOT NULL,
            updated_at  REAL NOT NULL
        )""",
        """CREATE TABLE contributions (
            contribution_id TEXT PRIMARY KEY,
            log_sha256      TEXT NOT NULL,
            log_format      TEXT NOT NULL,
            blob_key        TEXT NOT NULL,
            size_bytes      INTEGER NOT NULL,
            contributed_at  REAL NOT NULL,
            report_json     TEXT NOT NULL
        )""",
        """CREATE TABLE param_changes (
            id             TEXT PRIMARY KEY,
            airframe_label TEXT NOT NULL,
            report_id      TEXT NOT NULL,
            changes_json   TEXT NOT NULL,
            applied_by     TEXT NOT NULL,
            note           TEXT,
            created_at     REAL NOT NULL,
            verify_json    TEXT
        )""",
        "CREATE INDEX param_changes_airframe ON param_changes (airframe_label, created_at)",
    ]),
]


class Database:
    def __init__(self, data_dir: str):
        self.data_dir = os.path.abspath(data_dir)
        os.makedirs(self.data_dir, exist_ok=True)
        self.path = os.path.join(self.data_dir, DB_NAME)
        self._local = threading.local()
        self._all: list[sqlite3.Connection] = []
        self._all_lock = threading.Lock()
        self._migrate()

    def conn(self) -> sqlite3.Connection:
        c = getattr(self._local, "conn", None)
        if c is None:
            # isolation_level=None: we issue BEGIN ourselves, sqlite3's implicit
            # transactions don't cover DDL the way we want
            c = sqlite3.connect(self.path, timeout=30, isolation_level=None, check_same_thread=False)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA synchronous=NORMAL")
            self._local.conn = c
            with self._all_lock:
                self._all.append(c)
        return c

    @contextmanager
    def transaction(self, immediate: bool = True):
        # IMMEDIATE takes the write lock up front, so a read-modify-write
        # can't be interleaved by another thread or process
        c = self.conn()
        c.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
        try:
            yield c
        except BaseException:
            c.execute("ROLLBACK")
            raise
        c.execute("COMMIT")

    def execute(self, sql: str, params: tuple = ()) -> int:
        return self.conn().execute(sql, params).rowcount

    def query(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        return self.conn().execute(sql, params).fetchall()

    def query_one(self, sql: str, params: tuple = ()) -> Optional[sqlite3.Row]:
        return self.conn().execute(sql, params).fetchone()

    def close(self) -> None:
        with self._all_lock:
            for c in self._all:
                c.close()
            self._all.clear()
        self._local = threading.local()

    def _migrate(self) -> None:
        self.conn().execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at REAL NOT NULL)"
        )
        with self.transaction() as c:
            done = {r[0] for r in c.execute("SELECT version FROM schema_migrations")}
            for version, statements in MIGRATIONS:
                if version in done:
                    continue
                for stmt in statements:
                    c.execute(stmt)
                c.execute(
                    "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                    (version, time.time()),
                )
                logger.info(f"database migrated to v{version}")


_db: Optional[Database] = None
_db_lock = threading.Lock()


def get() -> Database:
    """The process-wide database, opened on first use from FLIGHTMD_DATA_DIR."""
    global _db
    if _db is None:
        with _db_lock:
            if _db is None:
                from api.config import get_settings
                _db = Database(get_settings().data_dir)
    return _db
