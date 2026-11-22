# Plan for software aspects of approval (PSAA)

FMD-PSAA, issue 1, 2026-11-20. A short plan in the place of a DO-278A PSAA.
**Nothing here is agreed with anyone, and nothing claims certification,
approval or compliance.** There is no certification project and no authority
involved today; the plan says how the software would be presented if one
asked, and what frame the project works to meanwhile. Clause numbers are left
out; references marked "to confirm" have not been checked against the
standard's text.

## 1. What the software is

FlightMD reads a flight log recorded by an unmanned aircraft's autopilot or
ground station after the flight and reports what it finds: a health score,
findings with their evidence, and parameter changes to consider
(`docs/lifecycle/03-system/conops.md`). It runs on a server, a laptop or
inside another ground application. Nothing of it runs on the aircraft, nothing
of it is in a control or command loop, and it sends nothing to an aircraft.

| Item | What | Code |
|---|---|---|
| `intake` | Format detection, archives, parse cache, the analysis pipeline, command line | `flightmd_core/services/format_detector.py`, `compressed.py`, `columns.py`, `flightmd_core/cache.py`, `orchestrator.py`, `__main__.py` |
| `parsers` | PX4 ULog, ArduPilot dataflash (binary, text), MAVLink telemetry, Betaflight/INAV blackbox, DJI flight record | `flightmd_core/services/*_parser.py` |
| `analysers` | The nine health checks and their framework | `flightmd_core/analysers/` |
| `report` | Report model, score, explanations, exports, flight context, optional AI summary | `flightmd_core/models/`, `flightmd_core/services/` (the rest), `flightmd_core/exporters/` |
| `api` | HTTP service, storage, airframe history, alerts | `api/` |
| `web` | Browser application | `frontend/` |
| `data` | Firmware parameter tables, safe ranges, airframe names | `flightmd_core/data/` |
| `tools` | Table generator, schema export, sample-log generator, trace check | `scripts/`, `tools/trace.py` |

## 2. Which standards, and how honestly they fit

| Standard | Fit | Use here |
|---|---|---|
| DO-178C (airborne software) | Does not apply: no airborne software | Not used |
| DO-278A (ground software of CNS/ATM systems) | Not written for this: FlightMD is not part of a CNS/ATM system. It is the nearest recognised process frame for non-airborne software in aviation | Used **as the process frame**, by choice: its life-cycle data items are the index of `docs/lifecycle/README.md`, and its assurance levels (AL1 to AL6) are the scale for the proposals in section 3. Whether any authority would ask for or accept it for a maintenance-support tool is to confirm |
| SAE ARP4754B, ARP4761A (aircraft system development and safety assessment) | Written for aircraft and their systems | The **method** is used at system and safety level: needs, system requirements, architecture and allocation, functional hazard assessment, FMEA, derived safety requirements. Editions not held; cited by name only (to confirm) |
| DO-200B (processing aeronautical data) | Written for navigation and similar aeronautical data chains. A flight log and a firmware parameter table are not aeronautical data in its sense | Its **data-quality ideas** are used by analogy for the three data sets a result depends on (section 5): accuracy, resolution, integrity, traceability to origin, timeliness, completeness, format. Applicability to confirm |
| DO-330 (tool qualification) | Would matter in two ways: for this project's own check tools, and if an operator took credit for FlightMD's output inside an approved process | Stance in section 6 |
| UAS-specific rules and practices (operator maintenance instructions under the applicable UAS regulation; ASTM F3201 on dependability of software used in UAS, to confirm) | These are what an operator would actually be held to; none prescribes a log-analysis tool | Not assessed in this issue (open item OI-002) |

## 3. Proposed assurance levels

From the hazard assessment (`docs/lifecycle/04-safety/hazard-assessment.md`,
section 5), under its assumptions A1 to A5. **Proposals, to be agreed with the
authority concerned if there ever is one.** The mapping of severity classes to
DO-278A levels is to confirm.

| Item | Worst failure effect | Proposed level |
|---|---|---|
| `intake`, `parsers`, `analysers`, `report`, `data` | A wrong or misleading result (a fault missed, a fault invented, a wrong parameter recommendation) that a person acts on: Minor under the assumptions | AL5 |
| `api` | The wrong report served, or a report lost: Minor | AL5 |
| `web` | A value shown wrongly or a not-assessed check read as healthy: Minor | AL5 |
| Flight context (weather, place name), optional AI summary and Q&A | Misleading context; not used in any finding: No safety effect to Minor | AL6 for context; AL5 for the guard that keeps AI output out of findings |
| `tools` | Section 6 | n/a |

What would raise a level: a clean report used as the sole basis for return to
service (A2 false); recommended parameters loaded without review (A3 false);
use for aircraft carrying people or in a category where one aircraft loss is
Hazardous or worse (A5 false); any output acted on automatically (A1 false).
Each needs the hazard assessment redone.

## 4. Life-cycle plans and data

The plans are `sdp.md`, `svp.md`, `scmp.md`, `sqap.md` beside this file; the
standards are in `docs/lifecycle/02-standards/`; the index of every data item
with its state is `docs/lifecycle/README.md`. The code was written before this
process existed, so requirements and design were written from the code
("as-built", decision D-03) and the gaps are logged as problem reports
(`docs/lifecycle/10-configuration/problem-reports.md`).

Objectives not met today, whatever level were agreed: independence of
verification and of quality assurance (one developer), reviewed requirements,
structural coverage analysis beyond the line coverage CI measures, and
verification of every low-level requirement by test (the matrix lists those
verified by inspection).

## 5. Data the result depends on

| Data | Origin | Quality needs (by analogy with DO-200B) | State |
|---|---|---|---|
| The flight log | The user's autopilot or ground station | Integrity: identified by SHA-256 in the report; format identified from content. Completeness and accuracy are the recorder's; FlightMD states what it skipped or guessed (SAF-004) | In place |
| Firmware parameter tables (`flightmd_core/data/param_tables/`) | Generated by `scripts/gen_param_tables.py` from the metadata the PX4 and ArduPilot projects publish | Traceability to the firmware version, accuracy of ranges, timeliness as firmware versions appear, format | Generated and versioned by file name; no check that a table still matches its upstream source, no record of the retrieval date and source hash in the table (open item OI-006) |
| Safe ranges and risky combinations (`param_safe_ranges.json`, rules in `parameters.py`) | Written by the developer | Each value needs a stated source | Sources not recorded per value (OI-006) |
| Thresholds of the checks | Constants in the code, some from autopilot documentation, some from experience | Each is stated in an LLR with its unit (requirements standard RS-18); source of each to record | Stated; sources partly recorded in code comments |

## 6. Tools

| Tool | Used for | Stance |
|---|---|---|
| `pytest`, Vitest, Playwright | Running tests | Output is read by a person and by CI; no credit beyond pass or fail |
| `tools/trace.py` | Trace check and matrix | A verification tool whose output is relied on. Kept small enough to review in one sitting, reads the `.sdoc` files itself, and StrictDoc's own export cross-checks it. Not qualified; qualification data would be needed only if credit were claimed without the cross-check |
| StrictDoc | Authoring, HTML | Not relied on for the check |
| `ruff`, ESLint, `tsc` | Coding standard | Findings are fixed or listed as deviations; no credit for absence of errors |
| `scripts/gen_param_tables.py` | Produces shipped data | Its output is reviewed in the pull request diff; section 5 |

If an operator wanted to take credit for FlightMD's output in an approved
maintenance process, FlightMD itself would be a tool in that process and the
operator's authority would decide what evidence it needs. Nothing is planned
for that today.

## 7. Open

OI-001 (levels and assumptions to be agreed, if an authority is ever
involved), OI-002 (which rules apply to an operator using the tool), OI-003
(independence).
