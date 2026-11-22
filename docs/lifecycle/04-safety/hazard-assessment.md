# Functional hazard assessment

FMD-FHA, issue 1, 2026-11-20. A hazard assessment in the manner of SAE
ARP4761A, sized for an analysis tool: the system functions, how each can fail
(loss, erroneous or misleading, untimely), what that leads to, how severe it
is, and the assurance level proposed for the items that implement it. ARP4761A
and ARP4754B are aircraft-system standards; their method is used here by
analogy and they are cited by name only (editions not held, to confirm).
**Nothing here is agreed: classes and levels are proposals, to be agreed with
the authority concerned if one is ever involved.** It has not been reviewed by
a safety engineer.

Inputs: the ConOps (`docs/lifecycle/03-system/conops.md`), the system
architecture, and the code as built. Outputs: the failure conditions below,
the safety requirements (`safety-requirements.sdoc`, SAF-001 to SAF-015) and
the FMEA (`fmea.md`). Security (someone causing these failures on purpose, or
reading other people's data) is not assessed here beyond the points noted;
there is no threat model yet (open item OI-011).

## 1. The hazard, classes and assumptions

FlightMD touches no aircraft. Its only path to harm is through a person:

> **A wrong or misleading analysis result leads someone to a wrong
> maintenance, airworthiness or operational decision about an unmanned
> aircraft.**

Three forms matter:

- **False clean.** A real fault in the log is not reported, or a check that
  did not run is read as passed. The aircraft flies again with the fault.
- **False alarm or wrong diagnosis.** A fault is reported that is not there,
  or the wrong cause is named. Time is lost, a good part is replaced, a
  correct tune is changed; trust in the tool falls and real findings get
  ignored.
- **Wrong recommendation.** A suggested parameter value is wrong for the
  vehicle and is loaded into it. This is the one output that can change how an
  aircraft flies.

Severity is judged on what the later flight could do: people and property on
the ground, other airspace users, and loss of the aircraft.

| Class | Meaning here | DO-278A level (mapping to confirm) |
|---|---|---|
| Catastrophic | Could cause loss of life | AL1 |
| Hazardous | Large reduction in safety margins: loss of control of an aircraft near people | AL2 |
| Major | Significant reduction in safety margins: loss of an aircraft away from people, or a flight continued with a degraded system the crew does not know about | AL3 |
| Minor | Slight reduction in margins: a wrong conclusion that other checks and a careful flight would normally catch | AL5 |
| No safety effect | Inconvenience; no effect on a later decision | AL6 |

Assumptions. Each one changes the result if it is false, and the product does
not yet tell its users about them (SAF-015, proposed):

- **A1. Advisory.** A person reads the report and decides. Nothing on an
  aircraft, in a ground station or in a maintenance system acts on a report
  automatically.
- **A2. Not the only barrier.** The operator's own pre-flight checks, the
  autopilot's arming checks and failsafes, and the maintainer's judgement stay
  in place. A clean report is never the sole basis for returning an aircraft
  to service.
- **A3. Recommendations are reviewed.** A suggested parameter change is
  checked against the firmware documentation by someone competent and proven
  in a cautious test flight before normal operation.
- **A4. Honest input.** The log is the user's own, recorded by a working
  recorder. Deliberately crafted logs are a security matter, not a safety one.
- **A5. Small unmanned aircraft, no people on board,** operated so that the
  loss of one aircraft is at worst Major. Use for aircraft carrying people, or
  where a single loss is Hazardous or worse, needs this assessment redone.

## 2. Functions

| # | Function | Items |
|---|---|---|
| F1 | Take in a log and identify its format | `intake` |
| F2 | Parse the log into topics, parameters and metadata | `parsers` |
| F3 | Work out when the vehicle was armed and flying | `analysers`, `intake` |
| F4 | Check the flight and produce findings | `analysers` |
| F5 | Score the flight | `report`, `analysers` |
| F6 | Explain findings and recommend parameter changes | `analysers`, `report`, `data` |
| F7 | Assemble, identify, store and serve the report | `report`, `api` |
| F8 | Export the report, the track and the parameter file | `report`, `api`, `web` |
| F9 | Follow an airframe: trends, tune-fly-verify, maintenance log, alerts | `api`, `web` |
| F10 | Optional AI summary and questions | `report`, `api` |
| F11 | Present the report | `web` |
| F12 | Add flight context: weather, place, planning brief | `report`, `api` |

## 3. Failure conditions

| Id | Function | Failure condition | Effect | Class | Existing mitigation | Safety req. |
|---|---|---|---|---|---|---|
| FC-1.1 | F1 | Log refused or analysis fails (unknown format, too large, damaged, timeout) | No report. The user uses another tool | No safety effect | Refusal carries the reason | - |
| FC-1.2 | F1 | Format identified wrongly; a file parsed as something it is not | Nonsense topics; findings invented or missed | Minor | Detection from content, several consecutive frames needed for telemetry logs, extension never trusted alone; "no analysable telemetry" refusal | SAF-003 |
| FC-2.1 | F2 | Erroneous parse: a field mapped to the wrong column, a wrong unit or scale, a wrong sign, a wrong clock | Checks run on wrong numbers: false clean or false alarm in any module, for every log of that format and firmware | Minor | One internal form; unit tests per parser with built logs; corpus with real logs for PX4 and ArduPilot; autopilot's own health figures preferred | SAF-004, SAF-014 |
| FC-2.2 | F2 | Partial parse: messages, a time span or a topic dropped (damaged or truncated log, unknown message version, decoder limit) | A fault in the dropped part is missed; durations and counts are wrong | Minor | Parse warnings; modules without inputs are "not assessed" | SAF-004, SAF-001 |
| FC-3.1 | F3 | Flight phases wrong or unknown: ground time judged as flight or flight time left out | Pad effects reported as faults (false alarm), or in-flight faults outside the window missed (false clean) | Minor | Fallback to the whole log with a warning; armed used when the land detector never clears | SAF-013, SAF-004 |
| FC-3.2 | F3 | All samples fall outside the flight windows and a check still reports clean | False clean for that module | Minor | Checks return a skip when they have nothing to check | SAF-013, SAF-001 |
| FC-4.1 | F4 | A check misses a real fault above its threshold (rule error, numerical error, wrong threshold for this vehicle) | False clean | Minor | Fixed thresholds stated in LLR; tests on both sides of thresholds; corpus | SAF-002, SAF-005, SAF-014 |
| FC-4.2 | F4 | A check that could not run or crashed is shown as passed | False clean, and the reader has no cue to look elsewhere | Minor | Skipped is not assessed; errors become a skip with the reason; assessed share reported | SAF-001 |
| FC-4.3 | F4 | A check reports a fault that is not there, or with the wrong severity or cause | False alarm; wrong repair; loss of trust | Minor | Sustain times, in-flight gating, confidence, evidence on every finding | SAF-005, SAF-013 |
| FC-4.4 | F4 | The log does not record what would show the fault (low rate, missing topic) and the report does not say so | False clean by omission | Minor | Not-assessed modules listed; Nyquist and sample-count guards in the checks where present (FMEA) | SAF-001 |
| FC-5.1 | F5 | Score or grade higher than the findings justify (unassessed modules counted as healthy, weights wrong, nothing assessed shown as 100) | False clean at a glance | Minor | Weighted mean over assessed modules only; "Not assessed" when none; assessed share | SAF-001 |
| FC-5.2 | F5 | Score lower than justified | False alarm | No safety effect | - | - |
| FC-6.1 | F6 | A recommended parameter value is wrong: outside the firmware's range, wrong direction, wrong parameter for the vehicle, computed from a bad current value | If loaded: degraded control, oscillation or loss of the aircraft in the next flight | Minor under A3; **Major if A3 does not hold** | Vehicle-aware names; no advice where none is safe; non-finite values dropped; conflicts flagged on the sheet. No common range check (SAF-008, proposed) | SAF-007, SAF-008, SAF-015 |
| FC-6.2 | F6 | The change sheet contradicts a finding, or two checks pull one parameter opposite ways unnoticed | A change applied that another finding argues against | Minor | One entry per parameter; the first (most severe) wins and the conflict is written on the entry | SAF-007 |
| FC-6.3 | F6 | Parameter check uses the table of the wrong firmware version or vehicle | Good values flagged, or out-of-range values passed | Minor | Table chosen from the firmware in the log (FMEA AN-06 for what happens when none matches) | SAF-008 |
| FC-6.4 | F6 | An explanation says something the data does not support | Wrong diagnosis | Minor | Templates keyed on the rule identifier, filled from the finding's own numbers | SAF-005 |
| FC-7.1 | F7 | The report served is not the one made for that log (mix-up of identifiers, stale cache entry, wrong dedupe) | A decision about one aircraft made from another's flight | Minor | Random identifiers; parse cache and dedupe keyed by SHA-256; the report names its input | SAF-011, SAF-009 |
| FC-7.2 | F7 | A report cannot be traced to its log or to the rules that made it | A later review cannot tell which engine said what | No safety effect (latent: hides FC-2.1 and FC-4.1) | Log hash, schema version and time in the report. Engine version missing (SAF-010, proposed) | SAF-009, SAF-010 |
| FC-7.3 | F7 | Report lost (expiry, disk wiped on redeploy) | Re-upload needed; history lost | No safety effect | Stated in the README | - |
| FC-8.1 | F8 | An export differs from the report: a value changed, rounded away or a unit lost in the PDF, JSON, GPX, KML or parameter file | Wrong value read or loaded | Minor | Exports format copies of the report data; schema test | SAF-012, SAF-007 |
| FC-9.1 | F9 | Trend or tune-fly-verify verdict wrong ("finding gone" when it is not, or flights of two airframes mixed under one label) | False confidence that a fix worked | Minor | Matching on rule identifier and parameter names; token per airframe | SAF-011 |
| FC-9.2 | F9 | An alert is not sent, or sent late | A threshold crossing goes unnoticed until someone opens the report | No safety effect under A2 | Delivery failure does not fail the analysis; nothing tells the user an alert failed (FMEA) | - |
| FC-10.1 | F10 | The AI summary or an answer states something the findings do not support | A reader who reads only the summary is misled | Minor | AI gets the report only and replaces only the summary string; findings, scores and recommendations cannot be reached by it; off by default | SAF-006 |
| FC-10.2 | F10 | AI output alters a finding, score or recommendation | As FC-4.x or FC-6.1, without a rule behind it | Minor | No code path (design standard DS-12) | SAF-006 |
| FC-11.1 | F11 | The web application shows a value in the wrong unit, a not-assessed module as healthy, or hides a warning | Misreading | Minor | Conversion for display only, unit shown; tests of the conversions | SAF-012, SAF-001 |
| FC-12.1 | F12 | Weather or place wrong or missing | Misleading context; not used by any check | No safety effect | "Not available" with the reason | - |

## 4. What decides the classification

Every failure condition that can mislead is classed **Minor**, and that rests
on A1 to A3 and A5: a person, other barriers and a reviewed test flight stand
between a wrong report and a wrong flight. Two things deserve saying plainly:

- **FC-6.1 is the sharp one.** A parameter file is made to be loaded into a
  vehicle. If users load it without review (A3 false) a wrong value has a
  direct path to how the aircraft flies, and the condition is Major. The
  proposed safety requirements SAF-008 (range check against the firmware
  metadata) and SAF-015 (limits of use shown) are there to keep A3 true in
  practice. Until they are built the proposal of AL5 for the recommendation
  path stands only on the assumption.
- **False clean is the common one.** FC-2.1, 2.2, 3.2, 4.1, 4.2, 4.4 and 5.1
  all end in "the report looked fine". The architecture's answer is the same
  each time: say what was not assessed, say what was guessed, and keep the
  score from counting what was not checked (SAF-001, SAF-004).

## 5. Proposed assurance levels

To be agreed with the authority concerned if there is ever one; the mapping
of classes to DO-278A levels is to confirm.

| Item | Worst failure condition | Class | Proposed level | Rationale |
|---|---|---|---|---|
| `parsers` | FC-2.1, FC-2.2 | Minor | AL5 | Every result depends on them; errors are systematic per format |
| `intake` | FC-1.2, FC-3.1, FC-7.1 (cache) | Minor | AL5 | Decides what is parsed and which parse is used |
| `analysers` | FC-4.1 to 4.4, FC-6.1 | Minor (Major without A3) | AL5 | The rules; AL3 for the recommendation path if A3 cannot be assumed |
| `report` | FC-5.1, FC-6.2, FC-6.4, FC-8.1 | Minor | AL5 | Score, change sheet, explanations, exports |
| `data` | FC-6.3 | Minor | AL5, with the data-quality needs of `psaa.md` section 5 | Ranges the parameter check and any future range check rely on |
| `api` | FC-7.1, FC-9.1 | Minor | AL5 | Serves and stores reports and airframe verdicts |
| `web` | FC-11.1, FC-8.1 (parameter file) | Minor | AL5 | Last step before the reader and the ground station |
| `report` (weather, geocoding), `api` (alerts, metrics) | FC-12.1, FC-9.2 | No safety effect | AL6 | Context and convenience |
| Optional AI (in `report`, `api`) | FC-10.1 | Minor | AL5 for the guard that confines it; the AI provider itself is outside the system and has no level | Its output is free text a reader may believe |

## 6. What reduces the risk further

- **Results on real logs** (SAF-014): the corpus, reviewed by a person. It
  covers PX4 and ArduPilot today; Betaflight, INAV, DJI and MAVLink telemetry
  results rest on built logs and a few samples only
  (`07-verification/README.md`).
- **The autopilot's own figures first**: vibration metrics, clip counts, EKF
  test ratios and board power come from the autopilot where logged, so the
  tool repeats a judgement the firmware already made rather than inventing
  one.
- **Independence**: none today (open item OI-003). A second reader for
  threshold changes and golden results is the cheapest improvement.

## 7. Not assessed

Common-cause analysis (for example one numeric library used by every check),
the security assessment (OI-011), and human factors of how a report is read
(what a score circle or a colour suggests) beyond the points in the FMEA.
