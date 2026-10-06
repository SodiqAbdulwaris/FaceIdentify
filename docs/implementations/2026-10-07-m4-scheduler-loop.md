# M4 W2.3: the scheduler loop and fail-closed recognition index

- **Date:** 2026-10-07
- **Milestone / tracker IDs:** M4 W2 · TST-048 (readiness), TST-060 (claim rules M4 exercises)
- **Status:** done for W2 with a fake perception provider; the real ML worker waits for issue #69
- **Commits:** PR (this change): `feat(api): run the scheduler loop after the library opens`

## What changed

- `backend/api/scheduler.py` (new): `SchedulerService` repeats `ProcessingRunner.run_once` in a
  worker thread. Work found means another look at once; `IDLE` waits for `wake()` or the poll
  interval; a wake that arrives during a call is kept (the event is cleared before each call); an
  error is recorded by class name and the loop waits one interval, never spinning; `stop()` lets the
  call in flight finish and claims nothing more. `last_outcome` and `last_error` are exposed.
- `backend/api/startup.py`: `ProcessingSettings` (no defaults; `client_for` is the perception
  boundary) turns the scheduler on. `Backend._boot` opens the library and **only then** creates and
  starts the scheduler, and never when the state is `FAILED`, so recovery and normal scheduling
  cannot race over a job or run (the 2026-10-06 constraint). Shutdown stops the scheduler before
  the library closes. `/readiness` reports `scheduler`: `NOT_CONFIGURED` without settings, `READY`
  while looping, `DEGRADED` while its last look failed, `STOPPED` after shutdown (`ml_worker` stays
  `NOT_CONFIGURED`). `Backend.wake_scheduler()` is what a route that queues a job will call.
- `IndexCoordinator.open_for_recognition(space_id)` (new): a read-only index handle that **fails
  closed** (API section 65). A space that never persisted an index is a valid empty one only while
  SQLite holds no eligible vector for it; a missing index over existing memory, or any unusable
  index, raises `IndexUnusableError` (the job then fails) instead of answering "nobody here" and
  creating duplicate identities. The scheduler and the shared test pipeline both use it, replacing
  an open-or-empty helper in the test fixture that would have hidden that case.

## Why

W2 of the completion plan: the scheduler loop, started after startup recovery, with readiness that
tells the truth.

## Decisions

None new. Capability names changed from `NOT_STARTED` to `NOT_CONFIGURED` (nothing is "not yet
started"; it is not wired), and the overall `DEGRADED` state is still decided at open time; the
scheduler capability is live.

## Verification

- Full gate (2026-10-07): ruff format/check and native/Linux mypy pass; `HYPOTHESIS_PROFILE=ci uv run
  pytest --cov -q -p no:cacheprovider` — **2,424 passed in 267.34s, 100% line and branch coverage**.
- `tests/integration/test_api_scheduler.py` (8): idle wakes, found work repeats, a wake during a call
  is kept, an error is recorded and survived, the recorded error is a class name, stop waits for the
  call in flight, wake before start and after the loop closed. `test_api_processing.py` (8) on a real
  library with planted perception: a queued job is processed after the library opens; no scheduler
  exists while startup is still running; recovery finishes a crashed run first (the new job matches
  the identity the crashed run created); a wake picks up a job queued while idle; a failing look
  degrades the capability until a success; no scheduler for a library that cannot open, one reported
  failed, or without settings. Four coordinator tests cover `open_for_recognition`.
- Mutations (restored byte-identically): starting the scheduler despite `FAILED`, not stopping it,
  a no-op wake, swapped degraded/ready, a lost wake, work-found waiting for the interval, an error
  ending the loop; two survived at first (a test race and a mutation that was not the property) and
  were closed by an explicit idle signal (`last_outcome`) and a properly aimed mutation.

## Open issues / follow-ups

- W3: routes call `wake_scheduler()` after queuing a job; library routes answer 503 until the state
  is `READY` or `DEGRADED`.
- The host (`backend.api.host`) does not pass `ProcessingSettings` yet: no real worker or weights
  (issue #69), so a launched sidecar reports `scheduler: NOT_CONFIGURED`.
- A job whose runner dies mid-flight stays leased until the next start's recovery.
