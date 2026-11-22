# ICD: web application

FMD-ICD-WEB, issue 1, 2026-11-22.

What the web application (`frontend/`) shows at its addresses, what it asks of the HTTP API, what it keeps in the
browser and where it links out. Facts are from `frontend/app/`, `frontend/components/`, `frontend/lib/`,
`frontend/i18n/request.ts` and `frontend/next.config.js` as built. Governing requirements: HLR-WEB-001 to 028;
detail in LLR-WEB-001 to 063. Design: `06-design/lld-web.md`.

## 1 Pages

| Address | Page | Notes |
|---|---|---|
| `/` | Upload form and the recent list of this browser | HLR-WEB-001, 002, 014 |
| `/report/<id>` | Progress, then the report | Server render first; `robots: noindex, nofollow`; HLR-WEB-003 to 013 |
| `/compare?a=<id>&b=<id>` | Comparison of two flights | Swaps `a` and `b` (replacing the address) when `a` flew later; HLR-WEB-015 |
| `/airframe/<label>` | Trends, history, token, maintenance, alerts, applied changes | `<label>` is URL-encoded; HLR-WEB-016 to 020 |
| any other | "Page not found" | `app/not-found.tsx` |

No address carries a locale; the one locale is `en` (LLR-WEB-062). Every response carries
`X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY` and `Referrer-Policy: strict-origin-when-cross-origin`.

## 2 Calls to the API

The browser calls `<NEXT_PUBLIC_API_URL>` (LLR-WEB-001); the Next server calls `<API_URL>` (LLR-WEB-014). Ids and
labels in paths are URL-encoded, except the report id in export addresses. Airframe calls send the stored token in
`X-Airframe-Token` and never in the address.

| Call | Used by | Time limit | On failure |
|---|---|---|---|
| `POST /analyse` (multipart: `file`, `airframe_label`, `contribute_to_dataset`, `planning_brief_sha256`) | Upload | 10 min | 401/403, 413, 429, 503, other, no connection, time limit, cancel each have their own text (LLR-WEB-007) |
| `GET /report/<id>` | Report page, server render | 8 s | 404: report expired; 422: analysis failed with reason; else the browser polls (LLR-WEB-014) |
| `GET /status/<id>` | Report page, browser | 20 s | 404: expired; 422/500: failed; 5 other failures in a row: "Can't reach the server" (LLR-WEB-016) |
| `GET /report/<id>` | Report page after `complete`; comparison | 20 s | 202: keep polling; else as above |
| `GET /export/{pdf,json,gpx,kml}/<id>` | Export bar | 60 s | PDF 501: print dialog; else server text or "Download failed (<status>)." |
| `POST /ask/<id>` (`{"question"}`, at most 500 characters) | Report search | 60 s | 429: "Too many questions"; else server text or "The AI request failed (<status>)." |
| `GET /diff?a=<id>&b=<id>` | Comparison | 20 s | 404: "One or both reports were not found or have expired."; else server text or code |
| `DELETE /dataset/<contribution_id>` | Recent list | 20 s | 404 counts as done; else server text or "Could not withdraw the contribution (<status>)." |
| `GET /trends/<label>`, `GET /airframe/<label>/config`, `GET /airframe/<label>/changes` | Airframe page | 20 s | 401/403: token form; else server text or the call's own text (LLR-WEB-004, 005) |
| `PUT /airframe/<label>/config` | Claim, maintenance settings, alert rules | 20 s | as above |
| `POST /airframe/<label>/maintenance` | Maintenance log | 20 s | as above |
| `POST /airframe/<label>/changes` | Parameter sheet, "Mark as applied" | 20 s | as above |
| `GET /export/airframe/<label>/pdf` | Flight record download | 60 s | 401/403: token needed; else "Download failed (<status>)." |

Every failure shows the API's `detail` text when it sent one (the first message of a validation list), except
503 on upload, 404 on the comparison and 429 on AI questions, which always show the app's own text. No
connection reads "Network error. Is the API running?"; a time limit "The server took too long to answer."
(LLR-WEB-002, 003, 018). An `airframe_token` in any answer is stored for that label (LLR-WEB-004, 007).

## 3 Browser storage

| Key | Form | Content |
|---|---|---|
| `flightmd.recent` | JSON array | This browser's uploads, newest first, at most 20 (LLR-WEB-028) |
| `flightmd.airframeTokens` | JSON object | Airframe token by lower-cased label (LLR-WEB-029) |
| `flightmd.units` | JSON string | `metric`, `imperial` or `aviation` (LLR-WEB-030) |
| `flightmd.theme` | Plain text | `light` or `dark` (LLR-WEB-033, 034) |

All in `localStorage`; nothing in cookies or session storage. The app works when storage is blocked
(LLR-WEB-027).

## 4 Address parameters

| Page | Parameter | Meaning |
|---|---|---|
| `/report/<id>` | path `<id>` | Report id from the upload answer |
| `/compare` | `a`, `b` | Report ids; `a` is shown as the earlier flight |
| `/airframe/<label>` | path `<label>` | Airframe label; one that cannot be decoded reads "This airframe link is malformed." |

## 5 Links out

| Link | Address | When |
|---|---|---|
| Audit airspace in AirBrief | `<NEXT_PUBLIC_AIRBRIEF_URL>/w/view?m=flight-audit&report_url=<origin>/report/<id>` (encoded), new tab | Setting given and report has a GPS path (LLR-WEB-013) |
| Open in AirBrief | `<NEXT_PUBLIC_AIRBRIEF_URL>/w/report?brief=<sha256>`, new tab | Setting given and report has a 64-hex planning brief hash |
| API documentation | `<NEXT_PUBLIC_API_URL>/docs` | `NEXT_PUBLIC_API_URL` set |
| Source repository | Fixed address in `app/layout.tsx` | Always, in the page header |
| Map tiles | `NEXT_PUBLIC_TILE_URL`, else OpenStreetMap tiles | Report with a GPS path |

## 6 Environment variables

| Variable | Read | Default |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | Build time, browser and layout | Same origin on https, else `http://localhost:8000` |
| `API_URL` | Next server, at run time | `NEXT_PUBLIC_API_URL`, else `http://localhost:8000` |
| `NEXT_PUBLIC_AIRBRIEF_URL` | Build time | None: no AirBrief links |
| `NEXT_PUBLIC_MAX_FILE_SIZE_MB` | Build time | 50 |
| `NEXT_PUBLIC_TILE_URL` | Build time | OpenStreetMap tiles |
