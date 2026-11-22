# Software quality assurance plan

FMD-SQAP, issue 1, 2026-11-20. How the project checks that it follows its own
plans and standards.

## 1. What is checked, and by what

| Check | When | By |
|---|---|---|
| Tests, trace check, linters, type check, dependency audit, build | Every push to `main` or `dev` and every pull request to `main` | CI (`.github/workflows/ci.yml`) |
| Real-log corpus | Weekly and on demand | CI (`corpus.yml`) |
| Review checklist for what the change touched | Every pull request | The reviewer (`09-reviews/review-checklists.md`) |
| Golden-result review | Whenever a corpus result changes | A person, recorded in `09-reviews/review-records.md` |
| Problem reports classed S open at a release | Every release tag | Whoever tags |
| Lifecycle index against the tree | Every release | `docs/lifecycle/README.md` read against the folders |
| Deviations from the coding standards | When a linter rule set changes | Deviation lists in `02-standards/` |

## 2. Records

`09-reviews/review-records.md` (reviews and golden-result reviews),
`10-configuration/problem-reports.md`, CI results on GitHub, the pull
requests themselves.

## 3. Independence and authority

There is one developer, so every review today is a self-check and quality
assurance has no independent authority (open item OI-003). The automated
checks are the part that does not depend on the author. The checklists are
written so a second person can use them without the author present.

## 4. Non-conformances

A departure from a plan or standard found in review is either fixed in the
pull request, entered as a problem report (class P), or added to the
deviation list of the standard with its reason. A linter is never switched off
to get a build through; a rule that cannot be met is listed as a deviation.

## 5. Suppliers

Third-party packages are checked by version pin and vulnerability audit only
(`sdp.md` section 5).
