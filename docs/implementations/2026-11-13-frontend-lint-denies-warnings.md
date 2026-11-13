# The frontend lint gate fails on warnings again

- **Date:** 2026-11-13
- **Milestone / tracker IDs:** CI-001 (frontend lint); found in the final full-gate run
- **Status:** done
- **Commits:** PR (number recorded when merged): `fix(frontend): make the lint gate fail on warnings`

## What changed

- `frontend/package.json`: the `lint` script is `oxlint --deny-warnings`.
- `frontend/src/features/setup/SetupPage.test.tsx`: the Windows paths in the test are written with
  escaped backslashes. Before, they had single backslashes, which JavaScript drops in a string
  (a path read as `C:UsersmeDocumentsFaceIdentify`), so the test compared two wrong strings that
  happened to be equal.
- `clock` moved from `VideoPanel.tsx` to `frontend/src/lib/utils.ts` (a component file exports only
  components).
- `SourcePage.tsx`: the video progress estimate takes its "now" from the time the runs were last
  fetched (`runs.dataUpdatedAt`), not `Date.now()` during render; the progress and the time then
  come from the same instant.

## Why

`.agents/rules/testing.md` says lint warnings fail. CI and the guides run
`npm run lint -- --deny-warnings` at the repository root, where the root script is
`npm run lint --workspace frontend`: npm takes `--deny-warnings` as its own unknown option ("Unknown
cli config") and never passes it to `oxlint`. So the gate has not denied warnings, and 14 had
accumulated (12 useless escapes, one mixed export, one impure call in render).

## Decisions

The flag lives in the script itself, so every way of running lint is strict and the existing
commands in CI and the guides keep working unchanged.

## Verification

`npx oxlint --deny-warnings` before: 14 warnings, exit 1. After, at the repository root:
`npm run typecheck` clean; `npm run lint` clean (exit 0); `npm test` 28 files, 245 tests passed;
`npm run build` built. `git diff --check` clean.

## Open issues / follow-ups

None.
