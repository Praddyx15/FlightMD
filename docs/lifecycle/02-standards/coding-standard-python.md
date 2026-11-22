# Python coding standard

FMD-CS-PY, issue 1, 2026-11-20. For `flightmd_core/`, `api/`, `scripts/`,
`tools/` and `tests/`. Python 3.11 to 3.13. Rules marked **ruff** are enforced
in CI, once OI-019 lands (job "Python lint": `ruff check flightmd_core api scripts tools tests`,
ruff 0.8.4, configuration in `pyproject.toml` `[tool.ruff]`); the others are
review items. Every exception is in the deviations list, section 4.

Before this issue CI ran ruff with `E`, `W`, `F` only, on `flightmd_core` and
`api`. This issue adds the rule sets below, which the code already met apart
from the listed deviations, and extends the check to `scripts`, `tools` and
`tests`. No code was changed to satisfy a rule.

## 1. Tools in force

| Rule | Text | Enforcement |
|---|---|---|
| PY-01 | ruff rule sets E, W, F (pycodestyle, pyflakes), B (bugbear), BLE (blind except), S (bandit security checks), C4 (comprehensions), PIE, PGH (no blanket `noqa` or `type: ignore`), ASYNC, DTZ (naive datetimes), UP (pyupgrade), SIM (simplify), RUF100 (no unused `noqa`) | ruff |
| PY-02 | Tests are linted with E, W, F, PGH and RUF100 only | ruff (`per-file-ignores`) |
| PY-03 | No `# noqa` or `# type: ignore` without a rule code and a reason on the line | ruff (PGH, RUF100); review for the reason |

There is no type checker in the repository's tool set. Type hints are written
on public functions and data models (pydantic validates the models at run
time). Adding mypy or pyright is open item OI-009.

## 2. Rules

| Rule | Text | Enforcement |
|---|---|---|
| PY-04 | Catch specific exceptions where they are known to happen; no bare `except:`. `except Exception` only at a boundary that must keep going (one check, one plugin, one progress callback, one outside service, one background job), and the file is then named in the deviations list | ruff (BLE, E722) |
| PY-05 | A boundary that swallows an exception reports it where the user or the operator sees it: a skipped result with the reason, a parse warning, a "not available" value, or a log line. Never silently | review |
| PY-06 | Outside input (uploads, archives, report files, form fields, webhook addresses) is checked once where it enters, with a size bound | review; tests |
| PY-07 | No `eval`, `exec`, `shell=True`, YAML loading, or `pickle` of data from outside. The one `pickle` use is the parse cache, which reads only files this process wrote (PY-D3) | ruff (S102, S307, S602, S506, S301) |
| PY-08 | Outbound requests go to fixed https hosts, with a timeout, and not at all in offline mode | ruff (S113 for `requests`; S310 flags `urlopen`, PY-D4); tests |
| PY-09 | A threshold is a named module constant with its unit in the name or a comment (design standard DS-05) | review |
| PY-10 | Units: internal values are SI or the PX4 topic's unit as documented in the parsers' LLR; a conversion is written once, in the parser, with the factor visible (`/ 1e7`, `/ 1000.0`) and a comment naming the source unit | review |
| PY-11 | A number that can be NaN or infinite is tested with `math.isfinite` or `np.isfinite` before it decides a severity, and is never put in a report (the report builder cleans what remains) | review; tests |
| PY-12 | No randomness and no wall-clock time in parsers, checks, scoring or explanations (design standard DS-07) | review; corpus |
| PY-13 | Files that matter are written beside the target and `os.replace`d over it | review |
| PY-14 | Secrets (API keys, airframe tokens, the metrics token) are never logged, printed, put in an exception message or stored in clear where a hash will do | ruff (S105 to S107 for literals); review |
| PY-15 | SQL takes every value as a bound parameter | ruff (S608); review |
| PY-16 | A function that implements a low-level requirement carries its tag as the last line of its docstring, `@relation(LLR-INT-003, scope=function)`; pydantic models and FastAPI route handlers are tagged at file scope instead (requirements standard, section 6) | `tools/trace.py --check` |
| PY-17 | Comments say why. Docstrings on public functions and where the use is not obvious | review |

## 3. Tests

Each test names what it covers (`# covers: HLR-...` or `LLR-...` on the line
above); tests do not depend on order, the clock or the network; slow tiers are
marked (`integration`, `corpus`).

## 4. Deviations

Each is an `ignore` or `per-file-ignores` entry in `pyproject.toml`.

| Id | Rule | Where | Why it is accepted |
|---|---|---|---|
| PY-D1 | E501 (line length) | Everywhere | The repository never enforced a line length; lines run to about 120 |
| PY-D2 | BLE001 (blind except) | `flightmd_core/orchestrator.py`, `analysers/base.py`, `analysers/registry.py`, `services/ai_enhancer.py`, `services/weather_lookup.py`, `services/geocoding.py`, `api/analysis.py`, `api/services/report_qa.py`, `scripts/gen_param_tables.py` | The boundaries of PY-04: a failing check becomes a skipped result with the error text, a failing plugin is left out with a warning, a failing outside call becomes "not available", a failing job is recorded as failed. Each is reviewed against PY-05 in the FMEA (`04-safety/fmea.md`). New blind excepts in any other file fail the build |
| PY-D3 | S301 (pickle) | `flightmd_core/cache.py` | The parse cache. Entries are written only by this module into a directory under the data directory, named by SHA-256, and an unreadable entry is dropped. A process that can write that directory can run code in the service: the deployment must keep it private (FMEA IN-05) |
| PY-D4 | S310 (`urlopen`) | `services/weather_lookup.py`, `services/geocoding.py`, `services/dji_parser.py`, `scripts/gen_param_tables.py` | The URLs are built from fixed https hosts; no scheme comes from input |
| PY-D5 | S314 (XML parsing) | `scripts/gen_param_tables.py` | A developer tool that parses the firmware projects' own metadata files, run by hand; not part of the service |
| PY-D6 | S105 | `api/security.py` | A false positive on a header or field name, not a secret |
| PY-D7 | S603 | `tools/trace.py` | Runs the `strictdoc` executable found on PATH with a fixed argument list, on request (`--html`) |
| PY-D8 | B904 (`raise ... from`) | Everywhere (15 places, all in `api/`) | HTTP errors raised inside `except` without `from`; the original error is logged or deliberately not shown to the client. To revisit when those handlers change |
| PY-D9 | B905 (`zip` without `strict=`) | Everywhere (16 places) | Not reviewed one by one yet. A `zip` over two series of different length drops the tail silently, which matters where the series are data; open item OI-010 |
| PY-D10 | B008 | `api/routers/analyse.py` | FastAPI's `File(...)`/`Form(...)` defaults |
| PY-D11 | B007, C401, C408, SIM105, SIM115, UP007, UP011, UP012, UP015, UP017, UP035, UP037, UP038, DTZ011 | The files named in `pyproject.toml`, or everywhere for SIM105, UP007, UP017, UP035, UP038 | Style only (how an `Optional` is spelled, `try/except/pass` against `contextlib.suppress`). Left as written so that this issue changes no code |
| PY-D12 | I (import order), T20 (`print`) | Not enabled | Import order was never enforced and 25 files would change; `print` is the command line's output |
| PY-D13 | B, BLE, S, C4, PIE, DTZ, UP, SIM, ASYNC in `tests/` | `tests/**` | Tests use `assert`, fixed temporary paths and broad excepts on purpose |
