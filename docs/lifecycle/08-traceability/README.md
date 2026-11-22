# Traceability

How requirements trace up to needs and safety requirements and down to
low-level requirements, code and tests, and how that is checked.

## Sources

| Level | File |
|---|---|
| STK | `docs/lifecycle/03-system/stakeholder-needs.sdoc` |
| SAF | `docs/lifecycle/04-safety/safety-requirements.sdoc` |
| SYS | `docs/lifecycle/03-system/system-requirements.sdoc` |
| HLR | `docs/lifecycle/05-requirements/hlr-<item>.sdoc`, one per software item |
| LLR | `docs/lifecycle/05-requirements/llr-<item>.sdoc`, one per software item |
| Code | `@relation(LLR-..., scope=function\|class\|file)` tags in `flightmd_core/`, `api/`, `scripts/`, `frontend/lib`, `frontend/components`, `frontend/app`, `frontend/i18n` |
| Tests | `covers: HLR-..., LLR-...` comments in `tests/`, `frontend/test`, `frontend/e2e` |
| Grammar | `docs/lifecycle/02-standards/requirements.sgra` |
| StrictDoc config | `strictdoc_config.py` (this folder) |

How to write requirements and tags: the requirements standard
(`docs/lifecycle/02-standards/requirements-standard.md`).

## The check

```bash
python tools/trace.py --check     # exits 1 on any problem; writes matrix.md
python tools/trace.py --html      # also StrictDoc's HTML in .local/strictdoc/html (not tracked)
```

It needs only the Python standard library. It is hooked in twice:

- `tests/test_trace.py` runs the same check inside `pytest`, and fails when
  the committed `matrix.md` is not what the check would write.
- `.github/workflows/ci.yml`, job "Python lint", step "Requirement trace":
  `python tools/trace.py --check`, then `git diff --exit-code` on `matrix.md`.

`trace.py` reads the `.sdoc` files itself, without importing StrictDoc, and
reports a problem when:

- an active HLR or LLR says Test and no test names it, or does not say Test
  and has no `VERIFICATION_NOTE` giving the reason;
- a test names an id that is not an active requirement;
- a parent does not exist, is deleted, or is at the wrong level (SYS to STK
  or SAF, HLR to SYS, LLR to HLR), or a SYS, HLR or LLR has no parent;
- a UID is used twice;
- a requirement's fields are not in the grammar, are out of grammar order,
  miss a required field, or use a choice value the grammar does not list;
- an STK or SAF has no SOURCE, or a SYS, HLR or LLR no VERIFICATION;
- an active HLR has no active LLR child and no `VERIFICATION_NOTE` saying why
  HLR level is enough;
- an active LLR is tagged nowhere in the code (unless allocated to
  `procedure`), a tag names an id that is not an active LLR, or a tag is
  malformed;
- an HLR or LLR id does not carry its file's item.

It writes `matrix.md` either way: counts per level and per document, the open
list (Proposed requirements, SYS with no HLR, needs nothing traces to, and
every HLR and LLR that has no test, with its reason), needs and safety
requirements to SYS, SYS to HLR, HLR to LLR and tests, and each LLR to the code
lines tagged with it and the tests that verify it. The matrix holds file and
line numbers, so it changes whenever tagged code or tests move; regenerate it
in the same commit.

## What the check does not show

- That a test named by `covers:` really exercises the requirement. That is a
  review item (`09-reviews/review-checklists.md`).
- That an LLR says what the code does. The LLR were written from the code in
  one pass and have not been reviewed by a second person.
- Structural coverage. See `07-verification/README.md`.

## Why two readers

StrictDoc is the authoring and browsing tool; `trace.py` is the check. Keeping
the check in one short script that does not import StrictDoc means a StrictDoc
upgrade cannot quietly change what passes, and the script can be reviewed in
one sitting. `tests/test_trace.py` feeds it a missing parent, an untested LLR,
an untagged LLR and a malformed tag and checks that each is reported.
