# Web application low-level design

FMD-LLD-WEB, issue 1, 2026-11-22.

As built. Requirements: `05-requirements/hlr-web.sdoc`, `05-requirements/llr-web.sdoc`. Interface:
`03-system/icd/icd-web-ui.md`. Decision D-10: in this issue LLR exist for `frontend/lib/` and the tested
components; pages and the other components are verified at HLR level (open item OI-012).

## 1 Purpose and code

The web application is a Next.js app (`frontend/`). It uploads a log to the HTTP API, follows the analysis, shows
the report, compares two flights and shows an airframe's history. It holds no data of its own beyond the
browser's local storage.

| File | Contents | LLR |
|---|---|---|
| `lib/api.ts` | Browser API client: address, `request`, `ApiError`, `AirframeAuthError`, every API call, downloads, AirBrief addresses | LLR-WEB-001 to 013 |
| `lib/serverApi.ts` | `fetchReportOnServer`, used by the report page's server render | LLR-WEB-014 |
| `lib/useReport.ts` | `pollReport` (status polling state machine) and the `useReport` hook | LLR-WEB-015 to 017 |
| `lib/errors.ts` | `useErrorText`: error to user text | LLR-WEB-018 |
| `lib/format.ts` | Number, time, date, parameter and unit formatting; unit conversion | LLR-WEB-019 to 026 |
| `lib/storage.ts` | Local storage: recent reports, airframe tokens, unit choice | LLR-WEB-027 to 030 |
| `lib/units.ts`, `components/shared/UnitsToggle.tsx` | Unit preference hook and selector | LLR-WEB-031, 032 |
| `lib/themeScript.ts`, `lib/theme.ts` | Theme set before first paint, theme switch, CSS values for canvas | LLR-WEB-033 to 035 |
| `lib/utils.ts` | Severity and score tones, assessed checks, finding times, clipboard | LLR-WEB-036 to 040 |
| `lib/groupFindings.ts` | Grouping of repeated checks | LLR-WEB-041, 042 |
| `lib/paramFile.ts` | Autopilot guess, Mission Planner and QGroundControl text | LLR-WEB-043 to 045 |
| `lib/chartData.ts` | `chart_data` to chart specs | LLR-WEB-046 to 053 |
| `lib/metricLabels.ts`, `lib/useLabels.ts` | Module and metric names, units, decimals | LLR-WEB-054 to 057 |
| `components/three/flightPathGeometry.ts` | Path sampling, scene projection, colour ramp | LLR-WEB-058 to 060 |
| `components/shared/DeltaBadge.tsx` | Score change badge | LLR-WEB-061 |
| `i18n/request.ts` | Locale and messages | LLR-WEB-062 |
| `lib/types.ts` | Report and API answer types (compile time only) | LLR-WEB-063 |
| `app/**`, other `components/**` | Pages and components | HLR level only |

## 2 Structure and data flow

**Upload.** `app/page.tsx` checks the file (`components/upload/DropZone.tsx`), calls `uploadLog`, adds the answer
to the recent list (`addRecentReport`) and goes to `/report/<id>`.

**Report page.** `app/report/[id]/page.tsx` runs on the Next server. It calls `fetchReportOnServer` once per
request (shared by the page metadata and the page through React `cache`):

- `done`: renders `ReportDone`, which updates the recent entry (score, grade, label, flight start, vehicle,
  firmware) and renders `ReportView` inside an error boundary;
- `missing`: the route's not-found page ("Report expired");
- `failed`: `FailedProblem` with the reason;
- `pending`: `ReportLive`, a browser island that runs `useReport` (polling `GET /status/<id>` and, at
  `complete`, `GET /report/<id>`) and renders the progress view, an end state or `ReportDone`.

`ReportView` passes the report object, unchanged, to its sections: header, findings and timeline, charts
(`collectCharts`), path map and 3D view (`flightPathGeometry`), parameter sheet (`paramFile`), flight details,
search and AI questions, exports. Values are converted to the unit preference only where they are drawn
(`useUnits`, `toUnit`, `fmtQty`, `Labels.convert`).

**Comparison.** `app/compare/page.tsx` reads `a` and `b` from the address and calls `getDiff` and `getReport` for
both.

**Airframe page.** `app/airframe/[label]/page.tsx` calls `getTrends`, `getAirframeConfig` and
`getAppliedChanges` through `airframeRequest`, which adds the stored token and keeps any token returned. The
panels (`AirframeAccess`, `MaintenancePanel`, `AlertsPanel`, `ChangesPanel`) call the other airframe functions.

**Text.** All user text comes from `messages/en.json` through next-intl; `i18n/request.ts` always picks `en`.

**Colours.** `frontend/design/tokens.json` holds both themes' colours. `frontend/scripts/tokens-to-css.mjs` runs
before `npm run dev` and `npm run build` (`predev`, `prebuild`) and writes `frontend/app/tokens.css` (dark values
on the root, light values under `.light`). The generated file is committed; `test/tokens.test.ts` checks the
contrast limits and that the CSS matches the JSON. The script is outside the directories the trace tool reads, so
HLR-WEB-028 is verified at HLR level.

## 3 Data

Browser local storage (all access through `lib/storage.ts`, except the theme):

| Key | Value | Written by |
|---|---|---|
| `flightmd.recent` | JSON array of recent uploads, at most 20 (LLR-WEB-028) | upload, report page, recent list |
| `flightmd.airframeTokens` | JSON object, lower-cased label to token (LLR-WEB-029) | any airframe answer with a token, token form |
| `flightmd.units` | JSON string: `metric`, `imperial` or `aviation` (LLR-WEB-030) | unit selector |
| `flightmd.theme` | Plain text `light` or `dark` (LLR-WEB-033, 034) | theme switch |

Window events `flightmd-units` and `flightmd-theme` tell every hook on the page that the choice changed. No
session storage, cookies or IndexedDB are used. The report object from the API is never changed or stored; the
recent list keeps only summary fields.

## 4 Error handling

- Every API call fails with `ApiError` (status, server text or an `errors.*` code); airframe calls fail with
  `AirframeAuthError` on 401 and 403 (LLR-WEB-002 to 004, 007). `useErrorText` turns either into the text shown:
  the server's own text when it sent one, else the message for the code (LLR-WEB-018).
- No connection gives code `network`, a time limit `timeout` (or `uploadTimeout`); polling gives up after 5
  failed calls in a row or 10 minutes and offers a retry (LLR-WEB-016).
- `chart_data` is checked before drawing: a bad shape gives no chart, a bad value a gap, and an exception while
  building is dropped (LLR-WEB-046, 053). Charts, the charts section, the map and the 3D view each sit in an
  `ErrorBoundary`; the whole report view sits in one that points to the exports. `app/error.tsx` catches the
  rest; `app/not-found.tsx` answers unknown addresses.
- Local storage that throws is ignored; the app works without it (LLR-WEB-027).

## 5 Resource use and limits

| Limit | Value | Where |
|---|---|---|
| API call time limit | 20 s; 60 s for downloads and AI questions; upload 10 min; server render 8 s | LLR-WEB-002, 006, 014 |
| Polling | at once, then 1 s growing by 1.5 to 5 s; 5 failures in a row; 10 min | LLR-WEB-015, 016 |
| Chart points | 500 per time chart; IMU sources 3, EKF series 6, motors 8 | LLR-WEB-046 to 052 |
| Path points | 1,000 | LLR-WEB-058 |
| Recent list | 20 entries | LLR-WEB-028 |
| AI question | 500 characters | LLR-WEB-011 |
| Upload size | `NEXT_PUBLIC_MAX_FILE_SIZE_MB`, 50 MB when unset | HLR-WEB-001 |

## 6 Known gaps and deviations

These are written into the LLR or HLR notes as they are; the first four and the raw-score one are in
`10-configuration/problem-reports.md` as PR-038 to PR-042.

| What | Where |
|---|---|
| The poller asks for the status at once; HLR-WEB-003 says first after 1 s | LLR-WEB-015 |
| `fmtParam` writes whole numbers in full and values below 1e-6 with 10 decimals, so not always 7 significant digits as HLR-WEB-025 says | LLR-WEB-025 |
| QGroundControl type 6 or 9 is guessed from the values; a float parameter with whole values gets 6 | LLR-WEB-045 |
| The raw overall score of a not-assessed flight is still shown in: the airframe page's overall score line and flight history row, the comparison page's flight cards and overall change, and the overall change in an applied-change record | `app/airframe/[label]/page.tsx`, `app/compare/page.tsx`, `ChangesPanel.tsx` (HLR-WEB-005) |
| Polling goes on while the tab is hidden | LLR-WEB-017 |
| API answers are not checked at run time, apart from `chart_data` | LLR-WEB-063 |
| The export addresses do not URL-encode the report id | LLR-WEB-009 |
| The clipboard fallback does not report a failed copy | LLR-WEB-040 |
| `getDatasetStats` is not used by any page | LLR-WEB-012 |
| Limits of use are not shown with the report | HLR-WEB-026 (Proposed), PR-017 |
