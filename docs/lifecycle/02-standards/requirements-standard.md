# Requirements standard

FMD-RS, issue 1, 2026-11-20. How requirements are written and kept, at every
level, in StrictDoc, and how code and tests name the requirements they
implement and cover. Reviews cite the rule ids (RS-nn). `tools/trace.py --check`
enforces the rules marked **[checked]**; the rest are review items
(`docs/lifecycle/09-reviews/review-checklists.md`).

## 1. Levels

| Level | Id form | Document | States | Parent | Verified by |
|---|---|---|---|---|---|
| Stakeholder need | `STK-nnn` | `03-system/stakeholder-needs.sdoc` | What a stakeholder needs, in their words | None; SOURCE names the ConOps section | Validation with the stakeholder |
| Safety requirement | `SAF-nnn` | `04-safety/safety-requirements.sdoc` | What must hold to keep a failure condition at its class | None; SOURCE names the failure condition or FMEA row | Through its SYS children; analysis |
| System requirement | `SYS-nnn` | `03-system/system-requirements.sdoc` | What the system does, allocated to items | One or more STK or SAF | Tests of its HLR children; analysis |
| Software high-level requirement (HLR) | `HLR-<ITEM>-nnn` | `05-requirements/hlr-<item>.sdoc` | Behaviour of one software item, observable at its interfaces | One or more SYS | Requirements-based tests; review with a stated reason (RS-05) |
| Software low-level requirement (LLR) | `LLR-<ITEM>-nnn` | `05-requirements/llr-<item>.sdoc` | Detail from which code is written directly: the function, inputs, outputs, thresholds with units, error behaviour | One or more HLR | Tests; review or analysis with a stated reason (RS-05) |

ITEM is the software item's short name and matches the file name
(`llr-prs.sdoc` holds `LLR-PRS-nnn`). The items are those of
`03-system/system-architecture.md`:

| ITEM | Item | Code |
|---|---|---|
| `INT` | Intake and pipeline | Format detection, archives, parse cache, orchestrator, command line |
| `PRS` | Parsers | The six log parsers |
| `ANL` | Analyser framework and checks | Base class, registry, phases, vehicle; GPS, battery, motors, power, parameters; parameter tables and their generator |
| `DYN` | Flight-dynamics checks | Oscillation, vibration, EKF, ascent profile |
| `RPT` | Report | Models, score, explanations, report builder, exports, flight context, optional AI summary |
| `API` | HTTP service | `api/` |
| `WEB` | Web application | `frontend/` |

## 2. Rules

| Rule | Text |
|---|---|
| RS-01 | **[checked]** Every requirement is a `[REQUIREMENT]` node of the grammar `02-standards/requirements.sgra`, with its fields in grammar order and choice values from the grammar |
| RS-02 | **[checked]** UIDs are unique across all documents and never reused. A dropped requirement keeps its UID with `STATUS: Deleted` |
| RS-03 | **[checked]** Parent levels: SYS to STK or SAF; HLR to SYS; LLR to HLR. Every active or proposed SYS, HLR and LLR has a parent; STK and SAF have a SOURCE |
| RS-04 | **[checked]** SYS, HLR and LLR state a VERIFICATION method (Test, Analysis, Inspection, Demonstration) |
| RS-05 | **[checked]** An active HLR or LLR whose VERIFICATION includes `Test` is named by at least one test (`covers: <id>`). One that is not tested has a `VERIFICATION_NOTE` saying that no test exercises it and what a review checks; the matrix lists these as open. No test names an id that is not an active requirement |
| RS-06 | One requirement, one testable statement. Numbers have units and limits; "fast", "robust", "user-friendly" are not requirements |
| RS-07 | Say what, not how, unless the how is the requirement (a file format, a threshold, an algorithm a finding depends on) |
| RS-08 | State failure behaviour: what is refused, what is reported, what the caller sees |
| RS-09 | ALLOCATION names the item(s) from `03-system/system-architecture.md`. HLR and LLR name software items, `tools`, `data` or `procedure` |
| RS-10 | STATUS: `Active` when it is built and in force; `Proposed` when it is needed and not yet built (allowed without tests or tags); `Deleted` when dropped |
| RS-11 | A requirement the parent does not ask for is marked `DERIVED: Yes` with a RATIONALE, and goes to the hazard assessment for a look |
| RS-12 | No requirement contradicts an ICD, the published report schema or another requirement |
| RS-13 | Changing a requirement's meaning changes its tests in the same pull request; changing only its wording does not need a new UID |
| RS-14 | **[checked]** Every active HLR has at least one active LLR child, or a `VERIFICATION_NOTE` saying why it is verified at HLR level only |
| RS-15 | **[checked]** Every active LLR is tagged in the code that implements it (section 6), unless its ALLOCATION includes `procedure`. A tag names only active LLR ids, with `scope=function`, `class` or `file` |
| RS-16 | **[checked]** An HLR or LLR id carries the item of the file it is in |
| RS-17 | An LLR is written from the code as built and is precise enough to test and to code from. Where the code does less than its HLR asks, the gap is a problem report (`10-configuration/problem-reports.md`), not a softened LLR |
| RS-18 | A threshold that decides a finding's severity is stated with its number and unit in an LLR, so a change to it is a requirement change (RS-13) |

## 3. Fields

| Field | Use |
|---|---|
| `UID` | The id |
| `STATUS` | Proposed, Active, Deleted |
| `TITLE` | Short name; required |
| `STATEMENT` | The requirement. "shall" for SYS and SAF; HLR and LLR in the present tense ("`open_log` raises ...") |
| `RATIONALE` | Why, when it isn't obvious |
| `SOURCE` | Where an STK or SAF comes from |
| `VERIFICATION` | One or more methods |
| `VERIFICATION_NOTE` | Why an HLR or LLR is not tested, or why an HLR has no LLR (RS-05, RS-14) |
| `ALLOCATION` | `intake`, `parsers`, `analysers`, `report`, `api`, `web`, `tools`, `data`, `deployment`, `procedure` |
| `DERIVED` | Yes or No (RS-11) |
| `COMMENT` | Anything else: partial compliance, a problem report number |
| `RELATIONS` | `- TYPE: Parent` / `  VALUE: <UID>` |

## 4. Format

StrictDoc `.sdoc` files (StrictDoc 0.31.0): `[DOCUMENT]` header with TITLE,
UID, VERSION, DATE and `MARKUP: Markdown`; `[GRAMMAR]` with
`IMPORT_FROM_FILE: @flightmd` (the alias is set in
`08-traceability/strictdoc_config.py`); `[TEXT]` for prose; `[[SECTION]]` and
`[[/SECTION]]` for grouping. Multi-line values between `>>>` and `<<<`. Files
are UTF-8 with LF line endings.

## 5. Tools

- `python tools/trace.py --check` reads the `.sdoc` files itself (no StrictDoc
  import), applies the [checked] rules and writes `08-traceability/matrix.md`.
  `tests/test_trace.py` runs the same check inside `pytest`, and the CI
  workflow runs it as its own step.
- `python tools/trace.py --html` also runs `strictdoc export` into
  `.local/strictdoc` for browsing; StrictDoc rejects grammar errors there too.

## 6. Code and test tags

LLR are tied to code with StrictDoc's source markers, so StrictDoc's HTML shows
the code beside each requirement, and `trace.py` reads the same markers.

| Language | Where the tag goes | Form |
|---|---|---|
| Python function | Last line of its docstring (a function with none gets a one-line docstring holding the tag) | `@relation(LLR-INT-003, scope=function)` |
| Python class | Last line of the class docstring; not on pydantic models (the docstring would enter the published schema) | `@relation(LLR-ANL-004, scope=class)` |
| Python module | Last line of the module docstring. Used for pydantic models, FastAPI route handlers (their docstring is the OpenAPI description) and argparse text | `@relation(LLR-API-010, scope=file)` |
| TypeScript, TSX | One comment near the top of the file; file scope only | `// @relation(LLR-WEB-001, scope=file)` |
| JSON data, HTML templates, CSS | Not tagged; the LLR is tagged where the code reads them | |

Tags are ids only. `trace.py` searches `flightmd_core/`, `api/`, `scripts/`,
`frontend/lib`, `frontend/components`, `frontend/app` and `frontend/i18n`.

A test names what it covers on the line above it: `# covers: HLR-INT-001,
LLR-INT-003` in Python, `// covers: ...` in TypeScript. Only ids the test really
exercises.
