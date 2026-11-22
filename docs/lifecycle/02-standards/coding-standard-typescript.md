# TypeScript coding standard

FMD-CS-TS, issue 1, 2026-11-20. For `frontend/` (Next.js 14, React 18,
TypeScript 5). Rules marked **eslint** or **tsc** are enforced by
`npm run typecheck` in CI and by `npm run lint` when a developer runs it (`frontend/.eslintrc.json`,
`frontend/tsconfig.json`); the others are review items. The configuration is
the repository's own, unchanged by this issue.

## 1. Tools in force

| Rule | Text | Enforcement |
|---|---|---|
| TS-01 | `strict: true`; no `allowJs` code of our own in `app`, `components`, `lib` | tsc (CI step "Type check") |
| TS-02 | ESLint with `next/core-web-vitals`, `jsx-a11y/recommended`, `tailwindcss/recommended`; `@typescript-eslint/no-explicit-any` is an error; only the listed custom class names are allowed | eslint (`npm run lint`) |
| TS-03 | No `any`, `as any`, `@ts-ignore`, `@ts-expect-error` or `eslint-disable` without a reason on the line | eslint for `any`; review for the rest. Count at this issue: none of the first four; one `eslint-disable-next-line` (TS-D1) |

## 2. Rules

| Rule | Text | Enforcement |
|---|---|---|
| TS-04 | Report data is read-only in the browser. A value is converted for display in `lib/units.ts` or `lib/format.ts` and shown with its unit; a converted value is never written back to report data, to an export or to a parameter file (design standard DS-11) | review; `frontend/test/units.test.tsx`, `format.test.ts` |
| TS-05 | A parameter file offered for download holds the report's values, formatted so the ground station reads the same number back | review; `frontend/test/paramFile.test.ts` |
| TS-06 | A module that was not assessed, and a report with nothing assessed, are shown as not assessed: no score colour, no pass mark | review |
| TS-07 | All calls to the API go through `lib/api.ts` (browser) or `lib/serverApi.ts` (Next server); errors are mapped in `lib/errors.ts` and shown, not swallowed | review |
| TS-08 | Types of API data live in `lib/types.ts` and follow the published report schema (`docs/schema/`) | review |
| TS-09 | User-facing text is in `messages/en.json`, not in components | review |
| TS-10 | Colours come from the generated tokens (`design/tokens.json` to `app/tokens.css`); the generated file is not edited | `frontend/test/tokens.test.ts`; review |
| TS-11 | Secrets kept in the browser (airframe tokens) stay in browser storage and are sent in a header, never in a URL | review |
| TS-12 | No `dangerouslySetInnerHTML` with data from the API or the user | review (TS-D2) |
| TS-13 | A file that implements low-level requirements carries one tag near its top: `// @relation(LLR-WEB-001, scope=file)` | `tools/trace.py --check` |

## 3. Tests

Vitest for `lib/` and tested components (`frontend/test/`), Playwright for
the smoke path (`frontend/e2e/`). Each test names what it covers on the line
above it (`// covers: HLR-WEB-..., LLR-WEB-...`).

## 4. Deviations

| Id | Rule | Where | Why it is accepted |
|---|---|---|---|
| TS-D1 | `react/no-array-index-key` disabled for one line | `components/airframe/MaintenancePanel.tsx` | A list with no stable key of its own |
| TS-D2 | `dangerouslySetInnerHTML` | `app/layout.tsx` | A constant script from `lib/themeScript.ts` that sets the theme before first paint; no outside data |
| TS-D3 | Flags beyond `strict` (`noUncheckedIndexedAccess`, `exactOptionalPropertyTypes`, `noImplicitOverride`) are off | `tsconfig.json` | Never enabled; not tried in this issue |
| TS-D4 | `tailwindcss/classnames-order` and `enforces-shorthand` off; `react/no-array-index-key` is a warning | `.eslintrc.json` | The repository's choice |
| TS-D5 | Tags are file scope only | All tagged files | A React component file is one unit; function-level markers add noise for no gain |
| TS-D6 | `npm run lint` was not part of CI before this issue (CI ran `tsc`, Vitest and the build) | `.github/workflows/ci.yml` | Lint ran clean locally in issue 1; the CI step is ready but not yet pushed (OI-019, PR-026) |
