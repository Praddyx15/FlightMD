# API low-level design

FMD-LLD-API, issue 1, 2026-11-22.

As built. Requirements: `05-requirements/hlr-api.sdoc`, `05-requirements/llr-api.sdoc`. Interfaces:
`03-system/icd/icd-http-api.md` (routes) and `03-system/icd/icd-storage.md` (data directory, tables, blobs,
Redis). Short by intent: the LLR carry the numbers and texts.

## 1 Purpose and code

The API item is a FastAPI service around the analysis engine (`flightmd_core.orchestrator.run_analysis`). It
takes an upload, runs the engine in a queue, stores the report once and serves it, its exports and the
per-airframe history.

| File | Role | LLR |
|---|---|---|
| `api/main.py` | Application, middleware (early 413, request id, access log, CORS), start-up, expiry sweep | LLR-API-001..008 |
| `api/config.py` | Settings from the environment and `.env` | LLR-API-009, 010 |
| `api/security.py` | Client address, rate limiter, airframe token errors and claim | LLR-API-011..014 |
| `api/routers/analyse.py` | `POST /analyse`, `/dataset/*` | LLR-API-015..025 |
| `api/routers/report.py` | `/status`, `/report`, `/ask` | LLR-API-026..029 |
| `api/routers/export.py` | `/export/*` | LLR-API-030..033 |
| `api/routers/health.py` | `/health` | LLR-API-034 |
| `api/routers/trends.py` | `/trends`, `/diff` | LLR-API-035..039 |
| `api/routers/airframe.py` | `/airframe/{label}/config`, `/maintenance` | LLR-API-040..044 |
| `api/routers/changes.py` | `/airframe/{label}/changes` | LLR-API-045..047 |
| `api/analysis.py` | One job: run the engine, store, alerts, change verification, contribution | LLR-API-048..052 |
| `api/job_queue.py`, `api/worker.py` | In-process queue or arq over Redis | LLR-API-053..057 |
| `api/storage.py` | Job store (`reports` table) | LLR-API-058..072 |
| `api/db.py` | SQLite database, migrations | LLR-API-073..076 |
| `api/blobs.py` | Local or S3 store for contributed logs | LLR-API-077..080 |
| `api/export_cache.py`, `api/fs.py` | Export cache, atomic writes | LLR-API-081..083, 112 |
| `api/airframe_store.py` | Airframe config, token, maintenance status, alert rules | LLR-API-084..092 |
| `api/param_changes.py` | Applied parameter changes and their verification | LLR-API-093..096 |
| `api/webhook_notifier.py` | Webhook address check and delivery | LLR-API-097..099 |
| `api/metrics.py` | Prometheus metrics | LLR-API-100..102 |
| `api/training_data_store.py` | Contributed logs | LLR-API-103..107 |
| `api/legacy_import.py` | One-time import of the earlier JSON stores | LLR-API-108..111 |
| `api/services/report_qa.py` | Prompt and call for `/ask` | LLR-API-113..116 |

## 2 Structure and data flow

Upload to report:

1. `request_log` refuses a `POST /analyse` whose `Content-Length` is over the size limit plus 64 KiB (413).
   The limiter counts the request per client address.
2. `analyse_log` reads 4096 bytes, detects the format (or `compressed`), checks the label and brief hash,
   prechecks the airframe token, then copies the file to `<data dir>/uploads/flightmd-*<suffix>` while
   hashing it and enforcing the size limit.
3. Same bytes, label and brief within 3600 s: the existing job is returned (`deduplicated`).
4. A `reports` row is created in state `processing` (503 at 100 such rows). An unclaimed label is claimed now.
5. The job (`AnalysisJob`: plain fields) is handed to the queue: `LocalQueue` (asyncio workers in the API
   process, `MAX_CONCURRENT_ANALYSES` at once) or `RedisQueue` (arq; `api/worker.py` runs `run_job`). The
   answer is 200 `processing` with the report id.
6. `run_job` runs the engine with a progress callback that updates the row, sets the report id and hashes,
   and writes the report JSON once (`complete`). For a tagged job it then checks alert rules (webhook) and
   refreshes pending change verifications; for a contributing job it stores the log and a stripped report
   copy. Errors there are logged only. Any earlier error marks the row `failed` with a cleaned text. The
   upload file is always deleted.
7. The client polls `GET /status/{id}` and fetches `GET /report/{id}` or an export. Exports are built once
   per report, schema version and application version, under `<data dir>/exports/<id>/`.

Background: at start-up the legacy stores are imported, and with the in-process queue running jobs are
marked interrupted and all upload files deleted. A sweep at start-up and every 600 s deletes expired rows
and their exports, fails jobs idle for 3600 s and deletes upload files older than 3600 s.

Airframe routes check `X-Airframe-Token` against the SHA-256 stored in `airframes`. A write route to an
unclaimed label checks its body first and claims last, so a refused request does not burn the claim.

## 3 Data

All state is in `<data dir>` (`FLIGHTMD_DATA_DIR`, default `./data`): `flightmd.db` (SQLite, WAL; tables
`reports`, `airframes`, `contributions`, `param_changes`, `schema_migrations`), `uploads/`, `exports/` and
`blobs/` (unless S3 is set). Details in `icd-storage.md`. A stored report is never updated: progress updates
apply only to `processing` rows and `complete` is the only writer of `report_json`. Parsed reports are kept
in a 32-entry in-memory cache.

## 4 Error handling

- Client errors are `HTTPException` with a fixed `detail` text (400, 401, 403, 404, 413, 422, 429, 501, 503);
  validation errors of request bodies are FastAPI's 422.
- An engine error never reaches the client as a traceback: `public_error` keeps a `ValueError` message with
  paths replaced by `<file>` (300 characters at most); anything else is "Analysis failed because of an internal
  error.".
- Work after completion (alerts, change verification, contribution) and the alert webhook never raise into
  the job.
- An export cache that cannot be written still answers; a corrupt airframe row raises rather than being
  overwritten; an unreadable report row reads as not found.

## 5 Resource use and limits

| Limit | Value | Where |
|---|---|---|
| Upload size | `MAX_FILE_SIZE_MB` (50) MiB; header check allows 64 KiB of framing | `main.py`, `routers/analyse.py` |
| Concurrent analyses | `MAX_CONCURRENT_ANALYSES` (2, at least 1) per process or worker | `job_queue.py`, `worker.py` |
| Jobs in `processing` | 100 | `storage.py` |
| Rate limits per client per hour | upload 10, ask 30, each PDF route 30 | `config.py` |
| Untagged report and failed job life | 3600 s; sweep every 600 s | `storage.py`, `main.py` |
| Stalled job | 3600 s without a row update | `main.py` |
| Worker job timeout | 900 s, no retry | `worker.py` |
| Question / context | 500 / 24000 characters; 400 tokens answer | `services/report_qa.py` |
| Webhook | URL 2048 characters, 5 s timeout, no redirect, no retry | `webhook_notifier.py` |
| Airframe body | 50 checklist items of 200, 20 alert rules, interval 0 to 100000 h, label 40 | `routers/airframe.py`, `storage.py` |
| Change body | 1 to 50 changes, names of 32, note 500 | `routers/changes.py` |

## 6 Known gaps and deviations

- PR-023 (confirmed): `/ask` does not check offline mode (`FLIGHTMD_OFFLINE`); with a key set it calls the
  provider in offline mode (LLR-API-029).
- An upload that claims a label and then fails to reach the queue answers 503 without the token, leaving the
  airframe claimed by a token nobody holds (LLR-API-021). Not yet in the problem register.
- A withdrawal of a contribution while its analysis runs answers 404 and the contribution is stored afterwards
  (LLR-API-025). Not yet in the problem register.
- A label longer than 40 characters is cut, not refused (LLR-API-058).
- Hours since maintenance count flights by upload time (LLR-API-090).
- With the Redis queue the analysis counters stay in the worker processes, which serve no `/metrics`
  (LLR-API-100); an arq timeout leaves the job `processing` until the stalled-job sweep (LLR-API-057).
- A 500 for an unhandled exception carries no `X-Request-ID` (LLR-API-002). Rate-limit counts are per process
  (LLR-API-012).
