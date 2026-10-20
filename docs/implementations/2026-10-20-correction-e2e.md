# TST-054: the correction end-to-end test

- **Date:** 2026-10-20
- **Milestone / tracker IDs:** M5 close-out step 3; TST-054
- **Status:** done
- **Commits:** PR to be recorded when merged (`test(e2e): keep corrections across a restart`)

## Why

TST-054 asks for a "Correction E2E" proving user corrections persist. The API and component tests
existed; the desktop workflow test named nobody and corrected nothing.

## What changed

- `frontend/e2e/workflow.e2e.tsx`: a second test on its own library. It imports and processes three
  images (two of the same face, one different), then through the visible app moves the different
  face to the person seen twice ("This is someone already in the library"), marks the second
  matching face "This is someone new", and confirms the first. It quits the real backend, starts it
  again, and checks the People list and each image: every face is under the person it was placed
  with and says "Checked by you.".
- The harness gained a library name for `launch`, and the `WebSocket` stub moved to `beforeEach`
  because the config restores globals after every test.

## Decisions

An identity emptied by a move stays in the library with no appearances, so the test expects it
(0, 1 and 2 appearances). No wall-clock waits, no new dependency; existing tests unchanged.

## Verification

`npm run typecheck`, `npm run lint -- --deny-warnings`, `npm test` (206 passed), `npm run build` and
`npm run test:e2e` (2 passed) all pass locally. CI result is recorded on the PR.

## Open issues / follow-ups

None.
