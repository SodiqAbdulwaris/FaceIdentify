# Test: the scheduler-degrade test no longer races its own retry

- **Date:** 2026-10-07
- **Milestone / tracker IDs:** M4 W2.3 test hardening; no tracker row changes
- **Status:** done
- **Commits:** PR #144: `test: stop the scheduler-degrade test racing its own retry`

## What changed

`tests/integration/test_api_processing.py::test_a_failing_look_degrades_the_scheduler_capability_until_a_success`
now builds the app with the default long idle wait (`LONG`, 60 s) instead of `idle_seconds=0.01`.
No production code and no assertion changed.

## Why

The test timed out once on the Windows CI runner (PR #139, run attempt 1: `until(...)` raised
`TimeoutError` waiting for `scheduler.last_error`) and passed on a rerun of the identical head and
locally. Cause: after the failed look the scheduler waits `idle_seconds` and looks again
(`backend/api/scheduler.py`, `_run`). The defect was a single failure, so that second look found an
empty queue and succeeded, setting `last_error = None`. With a 0.01 s interval, `last_error` was
set for only about 10 ms plus a thread hop, while `until` polls every 20 ms. A poll that missed the
window never saw the error and waited out its 30 s bound. The later `DEGRADED` and `FAILED`
assertions were exposed to the same race. The scheduler behaves as designed; the test's interval
was the defect.

## Decisions

- With the long wait the loop looks again only when woken, so the failed state persists until the
  test's explicit `backend.wake_scheduler()` after queueing a job. A wake cannot be lost: the loop
  clears its event before each call, and the test wakes only after it has seen the error.
- No sleeps, no weaker assertions, no scheduler change. A comment in the test records why the
  interval must stay long.
- Branch `test/stabilise-scheduler-degrade-test` (the repo's `<type>/<kebab>` rule).

## Verification

- Before: the race follows from reading the loop and the poll interval; it was **not reproduced**
  locally (it needs the slower runner), so this is a reasoned diagnosis, not an observed one.
- After: the test passed in 16 consecutive local runs; `ruff format --check`, `ruff check` and
  `mypy` are clean; `pytest -k api` gave 173 passed.
- Full `uv run pytest` in the Linux, root-user cloud sandbox: 2520 passed, 37 failed, 15 errors
  (storage, shared memory, ML supervisor, index and permission tests). The **identical** 37 failures
  and 15 errors occur on unmodified `main` in the same sandbox, so they are environmental and not
  caused by this change; the Windows CI job is the authority. The frontend gate was not run (no
  frontend change).

## Open issues / follow-ups

None. If the Windows job fails on this test again, the cause is something other than this race.
