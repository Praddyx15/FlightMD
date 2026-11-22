# ICD: HTTP API

FMD-ICD-HTTP, issue 1, 2026-11-22.

The HTTP interface of the API item, as built in `api/main.py` and `api/routers/`. Governing requirements:
HLR-API-001 to 027 and LLR-API-001 to 047, 097 to 102. Report JSON content is in
`icd-report-and-exports.md`; stored data in `icd-storage.md`. The live schema is served at `/openapi.json`,
`/docs` and `/redoc` (`/metrics` is left out of it).

## 1 Common rules

| Item | Rule |
|---|---|
| Base | One service, no path prefix, no version in the path. The application version is `GET /health` `version` |
| Identity | No accounts, no cookies. A report is reached by its id only; airframe routes need `X-Airframe-Token` (section 1.1) |
| Request id | Every handled response carries `X-Request-ID`, 12 hexadecimal characters |
| CORS | Origins from `CORS_ORIGINS`; no credentials; all methods and headers; exposed `X-Request-ID`, `X-FlightMD-Schema-Version`, `Content-Disposition` |
| Errors | JSON `{"detail": "<text>"}` for every refusal of the routes below. A body or query that fails validation gives FastAPI's 422 with `detail` as a list |
| Rate limits | Per client address and hour, counted in process memory: `POST /analyse` 10, `POST /ask` 30, each PDF route 30 (`RATE_LIMIT_PER_HOUR`, `ASK_RATE_LIMIT_PER_HOUR`, `PDF_RATE_LIMIT_PER_HOUR`). Over the limit: 429 with slowapi's JSON body |
| Client address | The socket peer; when the peer is inside `TRUSTED_PROXIES`, the right-most `X-Forwarded-For` entry that is not a trusted proxy |
| Report id | A UUID4 made by the API. An id that is not 1 to 64 letters, digits or `-` is treated as unknown (404) |

### 1.1 Airframe token

A label is 1 to 40 characters after trimming (longer is cut to 40), without `/`, `\` or control characters;
otherwise 400 "Invalid airframe label.". The first accepted write to an unclaimed label (a tagged
`POST /analyse`, `PUT /airframe/{label}/config` or `POST /airframe/{label}/maintenance`) returns
`airframe_token` once in its answer. Afterwards every airframe route needs the header
`X-Airframe-Token: <token>`.

| Case | Status | `detail` |
|---|---|---|
| Airframe unclaimed (read routes, changes routes) | 401 | "Airframe not claimed yet. Saving its config, logging maintenance or tagging an upload with it claims it." |
| Header missing | 401 | "This airframe needs its X-Airframe-Token header." |
| Wrong token | 403 | "Wrong airframe token." |

## 2 Analysis

### 2.1 `POST /analyse`

Multipart form. Rate limited.

| Field | Kind | Rule |
|---|---|---|
| `file` | file, required | The log, compressed (gzip, zip) or not. Format from the first 4096 bytes |
| `airframe_label` | form, optional | Tags the report (kept for the airframe's history). Claims an unclaimed label |
| `contribute_to_dataset` | form, default false | Keep the log and a stripped report copy |
| `planning_brief_sha256` | form, optional | 64 hexadecimal characters, stored in lower case in the report |
| `X-Airframe-Token` | header | Needed when the label is claimed |

200 answer:

```json
{"report_id": "<uuid4>", "status": "processing", "estimated_seconds": 20, "deduplicated": false,
 "airframe_token": "<only when this upload claimed the label>",
 "contribution_id": "<32 hex, only when contributing>"}
```

The same bytes with the same label and brief hash within 3600 s of an earlier processing or complete job
(not when contributing or claiming) answer `{"report_id": <earlier>, "status": <its status>,
"estimated_seconds": 0 if complete else 20, "deduplicated": true}` and start nothing.

| Status | `detail` |
|---|---|
| 400 | "Invalid file. Must be a PX4 ULog (.ulg), ArduPilot (.bin), or MAVLink telemetry (.tlog) file." (under 8 bytes); the format detector's message; "Invalid airframe label (no slashes or control characters)."; "planning_brief_sha256 must be 64 hex characters." |
| 401, 403 | Section 1.1 (claimed label) |
| 413 | "File too large. Maximum size is <n>MB." (`Content-Length` over the limit plus 65536 bytes, refused before the body is read; or the copy passes the limit) |
| 429 | Rate limit |
| 503 | "Too many analyses in progress. Try again in a minute." (100 jobs processing); "The analysis queue is unavailable. Try again in a minute." |

### 2.2 `GET /status/{report_id}`

200 `{"status": "processing" | "complete" | "failed", "progress": 0-100, "message": "<text>",
"eta_seconds": <seconds to 0.1 or null>, "error": "<only when failed>"}`. A job cut off by a restart or
idle for 3600 s is `failed` with an error starting "interrupted:". 404 "Report not found or expired.".

### 2.3 `GET /report/{report_id}`

200 the report JSON, header `X-FlightMD-Schema-Version`. 202 "Analysis still in progress."; 422 the job's
error text (or "Analysis failed."); 404 "Report not found or expired." (unknown, expired, malformed id or
unreadable row). No token, also for tagged reports. No route lists reports.

### 2.4 `POST /ask/{report_id}`

Body `{"question": "<1 to 500 characters>"}`. Rate limited. Report status rules of 2.3. 200
`{"configured": false, "answer": null}` when no AI provider key is set (no outbound call), else
`{"configured": true, "answer": "<text>"}`. A provider failure gives the answer "The AI assistant couldn't
answer that just now. Try the keyword search instead."; an empty one "Not in this report.". Nothing is stored.
Offline mode is not checked here (PR-023).

## 3 Exports

All take the status rules of 2.3 and answer an attachment (`Content-Disposition: attachment;
filename="..."`). `<8>` is the first 8 characters of the report id.

| Route | Type | File name | Other answers |
|---|---|---|---|
| `GET /export/pdf/{report_id}` | `application/pdf` | `flightmd_report_<8>.pdf` | 501 "PDF export isn't available on this server."; 500 "PDF generation failed."; rate limited |
| `GET /export/json/{report_id}` | `application/json` (indented 2), `X-FlightMD-Schema-Version` | `flightmd_report_<8>.json` | |
| `GET /export/gpx/{report_id}` | `application/gpx+xml` | `flightmd_track_<8>.gpx` | 422 "This flight log has no GPS track to export."; 500 "GPX generation failed." |
| `GET /export/kml/{report_id}` | `application/vnd.google-earth.kml+xml` | `flightmd_track_<8>.kml` | 422 as GPX; 500 "KML generation failed." |
| `GET /export/airframe/{label}/pdf` | `application/pdf` | `filename="flightmd_airframe_<ascii>.pdf"; filename*=UTF-8''<encoded real name>` | Token (1.1); 400 bad label; 500 "PDF generation failed."; rate limited |

## 4 Comparison and history

### 4.1 `GET /diff?a=<report_id>&b=<report_id>`

No token. 400 "Cannot diff a report against itself."; status rules of 2.3 for each. 200:

```json
{"a": {"report_id", "file_name", "overall_score", "letter_grade", "score_label"}, "b": {...},
 "overall_score_delta": 0.00,
 "module_score_deltas": {"<analyser>": {"a": 0.0, "b": 0.0, "delta": 0.00}},
 "findings_diff": {"resolved": ["<title>"], "new": ["<title>"],
                   "persisting_categories": [{"category", "severity_a", "severity_b"}]},
 "key_metric_deltas": {"<analyser>.<name>": {"a": 0.0, "b": 0.0, "delta": 0.0000}}}
```

`delta` is null when either side is null or missing; a skipped or not-assessed module scores null.

### 4.2 `GET /trends/{airframe_label}`

Token (1.1); 400 bad label. 200 `{"airframe_label", "flight_count", "flights": [{"report_id", "file_name",
"created_at" (upload time, Unix seconds), "overall_score", "letter_grade", "module_scores": {...},
"key_metrics": {"<analyser>.<name>": value}}]}`, oldest upload first, each distinct log once.

## 5 Airframe

### 5.1 `GET /airframe/{label}/config`, `PUT /airframe/{label}/config`

`PUT` body (every field optional; a field left out stays, null clears it):

| Field | Rule (422 otherwise) |
|---|---|
| `checklist_items` | At most 50 strings of at most 200 characters |
| `maintenance_interval_hours` | Above 0, at most 100000, or null |
| `alert_rules` | At most 20 of `{"metric", "comparison": "lt" \| "gt", "threshold": number, "label": <= 120 characters}`; a `metric` not of 1 to 64 letters, digits, `_`, `.` gives 400 |
| `webhook_url` | Checked as in section 6; refused with 400 and the checker's text |

Answer of both (and of 5.2): `{"airframe_label", "checklist_items", "maintenance_log": [{"date",
"maintenance_type", "notes"}], "maintenance_interval_hours", "alert_rules", "webhook_url",
"total_flight_hours", "hours_since_maintenance" (2 decimals), "maintenance_due", "flight_count",
"airframe_token" (only when this request claimed)}`. Rule metrics are `overall_score`, `module.<analyser>`
or `<analyser>.<key metric>`.

### 5.2 `POST /airframe/{label}/maintenance`

Body `{"date": "<ISO 8601>", "maintenance_type": "<1 to 120>", "notes": "<at most 2000>"}`. 400 "date must be
an ISO 8601 date, e.g. 2026-07-05". Claims an unclaimed label.

### 5.3 `POST /airframe/{label}/changes`, `GET /airframe/{label}/changes`

Token (1.1), never claims. `POST` body: `{"report_id": "<1 to 64>", "changes": [{"name": "<1 to 32 of
A-Z a-z 0-9 _>", "from_value": number | null, "to_value": number}] (1 to 50), "applied_by": "user" | "uaop",
"note": "<at most 500>"}`. 400 "report_id must be a finished flight tagged with this airframe.". 201 the stored
row `{"id", "airframe_label", "report_id", "changes", "applied_by", "note", "created_at", "verify"}`.

`GET` answers the rows newest first. `verify` is `{"status": "pending" | "improved" | "worse" | "mixed" |
"unchanged", "next_report_id", "findings_resolved", "findings_new", "metric_deltas": {"overall_score",
"module.<analyser>"}}`.

## 6 Alert webhook (outbound)

Sent once after a tagged analysis completes when the airframe has alert rules and a `webhook_url` and at
least one rule is breached (strictly below `lt` or above `gt` the threshold; a rule whose metric the report
lacks is skipped). Not sent for a deduplicated upload.

| Item | Rule |
|---|---|
| Address | At most 2048 characters, no whitespace or control character, `https` (or `http` with `ALLOW_HTTP_WEBHOOKS`), a host whose every resolved address is public unicast. Checked when saved and before each send |
| Request | `POST <path>?<query>` to the first checked address, TLS checked against the host name; `Content-Type: application/json`, `User-Agent: FlightMD-webhook` |
| Delivery | 5 s timeout, no redirect followed, no retry; only 2xx counts as delivered. A failure is logged and does not change the analysis |

Body (Slack and Discord accept it):

```json
{"content": "<text>", "text": "<text>"}
```

`<text>` is a first line ``⚠️ FlightMD alert — *<label>* (report `<report id>`)`` and one line per breached
rule `• <rule label or metric>: <value, 3 significant digits> (< or > <threshold>)`, joined by line feeds.

## 7 Dataset, health and metrics

| Route | Answer |
|---|---|
| `GET /dataset/stats` | 200 `{"contributed_logs": n, "total_bytes": n}` |
| `DELETE /dataset/{contribution_id}` | 204; 404 "No contribution with that id." (also for an id not of 32 lower-case hexadecimal characters). No token: the id comes from the log's bytes |
| `GET /health` | 200 `{"status": "ok", "version", "schema_version", "ai_configured", "uptime_seconds", "active_jobs"}` |
| `GET /metrics` | Prometheus text. When `METRICS_TOKEN` is set: `Authorization: Bearer <token>`, 401 "Metrics need a bearer token." (with `WWW-Authenticate: Bearer`), 403 "Wrong metrics token." Series: HTTP metrics by route template, `flightmd_analyses_total{format, outcome}`, `flightmd_analysis_duration_seconds{format}` |

## 8 Versioning

Routes are not versioned. The report body carries `schema_version`, also sent as `X-FlightMD-Schema-Version`
on `GET /report` and the JSON export. A change to a route, status or field listed here is an interface change
under HLR-API and needs this document updated.
