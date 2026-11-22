# ICD: API storage

FMD-ICD-STORE, issue 1, 2026-11-22.

What the API item keeps and where, as built in `api/db.py`, `api/storage.py`, `api/airframe_store.py`,
`api/param_changes.py`, `api/training_data_store.py`, `api/blobs.py`, `api/export_cache.py`,
`api/job_queue.py`, `api/worker.py` and `api/legacy_import.py`. Governing requirements: HLR-API-009, 010,
011, 013, 027 to 031 and LLR-API-006 to 008, 055 to 083, 103 to 112. The API process and any arq workers must
share this directory.

## 1 Data directory

`FLIGHTMD_DATA_DIR` (default `data`, relative to the working directory). At start-up the API also sets the
variable for the engine when it came only from `.env`.

| Path | Content | Written by | Removed |
|---|---|---|---|
| `flightmd.db` (+ `-wal`, `-shm`) | SQLite database, section 2 | All stores | Never by the API |
| `uploads/flightmd-<random><suffix>` | One uploaded log while its job is queued or running | `POST /analyse` | When the job ends; at start-up (in-process queue: all); by the sweep after 3600 s |
| `exports/<report id>/<kind>-<schema version>-<app version>` | Cached `report.pdf`, `report.json`, `track.gpx`, `track.kml` (characters other than letters, digits and `.` in the tag become `_`) | Export routes | With the report (expiry) |
| `blobs/<contribution id><suffix>` | Contributed logs, as uploaded, when no S3 bucket is set | Contribution | `DELETE /dataset/{id}` |
| `cache/` | The engine's parse cache (`icd-cli-library.md`) | Engine | Engine |

Temporary files are written beside their target (`.tmp-*`) and renamed into place.

## 2 Database

SQLite in WAL mode, `synchronous=NORMAL`, 30 s lock timeout, one connection per thread. Read-modify-write
steps run in `BEGIN IMMEDIATE` transactions. The SQL avoids SQLite-only forms (upserts are
`ON CONFLICT ... DO UPDATE` / `DO NOTHING`).

### 2.1 `schema_migrations`

`version INTEGER PRIMARY KEY, applied_at REAL NOT NULL`. Each migration of `db.MIGRATIONS` runs once, in
order, and is recorded. Shipped migrations are never changed. Current version: 1.

### 2.2 `reports` (one row per job)

| Column | Type | Meaning |
|---|---|---|
| `report_id` | TEXT PK | UUID4 |
| `status` | TEXT NOT NULL | `processing`, `complete`, `failed` |
| `progress` | INTEGER NOT NULL, default 0 | 0 to 100 |
| `message` | TEXT NOT NULL, default '' | Progress or failure text |
| `eta_at` | REAL | Expected end time while processing, else null |
| `error` | TEXT | Failure text shown to the client |
| `airframe_label` | TEXT | Tag; null for untagged |
| `log_format` | TEXT | Detected format |
| `log_sha256` | TEXT | SHA-256 of the uploaded bytes |
| `brief_sha256` | TEXT | Planning-brief hash |
| `created_at`, `updated_at` | REAL NOT NULL | Unix seconds |
| `report_json` | TEXT | The report, written once when complete |

Indexes: `reports_airframe (airframe_label, created_at)`, `reports_log_sha256 (log_sha256)`,
`reports_status (status, created_at)`.

### 2.3 `airframes`

`label TEXT PK, token_hash TEXT, config_json TEXT NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT
NULL`. `token_hash` is the SHA-256 hex of the airframe token (null until claimed). `config_json` holds
`airframe_label`, `checklist_items`, `maintenance_log` (`date`, `maintenance_type`, `notes`, sorted by date),
`maintenance_interval_hours`, `alert_rules` (`metric`, `comparison`, `threshold`, `label`) and `webhook_url`;
never the token or its hash.

### 2.4 `contributions`

`contribution_id TEXT PK` (first 32 hex of the log's SHA-256), `log_sha256 TEXT NOT NULL`, `log_format TEXT NOT
NULL`, `blob_key TEXT NOT NULL`, `size_bytes INTEGER NOT NULL`, `contributed_at REAL NOT NULL`, `report_json
TEXT NOT NULL` (the report with `file_name` and `report_id` empty and `location_name`, `gps_path`,
`gps_path_wind_speed_ms`, `gps_path_hdop` null). No name, address or file name of the uploader is stored.

### 2.5 `param_changes`

`id TEXT PK` (UUID4 hex), `airframe_label TEXT NOT NULL`, `report_id TEXT NOT NULL`, `changes_json TEXT NOT
NULL` (`[{"name", "from_value", "to_value"}]`), `applied_by TEXT NOT NULL` (`user` or `uaop`), `note TEXT`,
`created_at REAL NOT NULL`, `verify_json TEXT` (last stored verification). Index `param_changes_airframe
(airframe_label, created_at)`.

## 3 Blob store

Contributed logs only. Keys are made by the API (`<contribution id><suffix>`) and must be 1 to 128 letters,
digits, `.`, `_`, `-`, not starting with `.` and without `..`.

| Setting | Store |
|---|---|
| `FLIGHTMD_S3_BUCKET` empty | `<data dir>/blobs/<key>` |
| `FLIGHTMD_S3_BUCKET` set | Object `<FLIGHTMD_S3_PREFIX><key>` (prefix default `contributions/`) in the bucket; endpoint `FLIGHTMD_S3_ENDPOINT_URL` and region `FLIGHTMD_S3_REGION` when set; credentials from the usual `AWS_*` variables. Needs the `s3` extra (boto3) |

## 4 Redis (optional)

Only when `FLIGHTMD_REDIS_URL` is set, and only as the arq job queue; no state is kept there that `/status`
needs. The API enqueues function `analyse` with job id = report id and the payload `{"report_id",
"log_path", "file_name", "file_size", "log_format", "airframe_label", "contribute_to_dataset", "log_sha256",
"planning_brief_sha256"}`; `log_path` is a file under `<data dir>/uploads`. Workers (`arq
api.worker.WorkerSettings`) run at most `MAX_CONCURRENT_ANALYSES` jobs, 900 s each, one try. Needs the `queue`
extra.

## 5 Retention

| Data | Kept |
|---|---|
| Untagged complete report | 3600 s from upload, then deleted with its exports by the sweep (start-up and every 600 s) |
| Failed job, tagged or not | 3600 s from upload |
| Tagged complete report | Until deleted by hand; never expired |
| Processing job | Until it ends; failed as interrupted after 3600 s without a row update, or at start-up with the in-process queue |
| Upload file | Until its job ends; at most 3600 s by the sweep |
| Airframe, applied change | Until deleted by hand |
| Contribution (row and blob) | Until withdrawn |

## 6 Earlier stores

At start-up `reports/`, `airframes/` and `training_contributions/` (one JSON file per item) under `api/data`
and under the data directory are imported without replacing existing rows, then renamed to `<name>.imported`
(or `<name>.imported-<Unix time>`). Files that cannot be read stay in the renamed directory.
