# M7 step 3: a live class in the worker lease

- **Date:** 2026-11-12 (work began 2026-11-11)
- **Milestone / tracker IDs:** M7 step 3 · TST-072 (the live queue is bounded), TST-077 (the contention half)
- **Status:** done (camera sessions use the class from step 4)
- **Commits:** PR (number recorded when merged): `feat(ml): give camera sessions a live class in the worker lease`, `docs: record M7 step 3`

## What changed

- `backend/ml/supervisor/lease.py`: `ServiceClass` (`INTERACTIVE`, `LIVE`, `BACKGROUND`, most urgent first), one queue per class, `serving(cls)` and `live()` beside `interactive()`, `service_class()`. The next turn goes to the first non-empty queue in that order, except that after `burst` (3) grants in a row to either higher class the oldest waiting background request goes first. `queued()` takes a class. `TurnRecord` gains `live` and `queued_live` (and a `service` property); the debug line names the class and counts the live queue.
- Callers of `queued(True)` / `queued(False)` in tests now name the class; the expected log line counts the live queue.
- Tests: `tests/concurrency/test_worker_lease_live.py` (order across the three classes; a stream of camera frames still lets a movie through every `burst`; searches and frames share one burst; a live turn is recorded as live; per-class queue counts; the innermost scope names the class, and a new thread starts in the background class).

## Why

[M7 plan](../plans/M7_PLAN.md) step 3 and decision C6: live work outranks batch work at safe boundaries without starving it (processing spec section 7); a face search made from a camera session stays interactive.

## Decisions

> **Decision 2026-11-11 (delegated decision, M7 step 3):** M6 did not split foreground batch from background, so the lease has three classes, not the spec's five; `LIVE` sits between interactive and everything else, as C6 says, and the burst of 3 (D5) counts interactive and live grants together. The class is carried in one context variable, so a scope inside another (a camera search) takes the inner class.

> **Decision 2026-11-11 (delegated decision, M7 step 3):** "the live queue is never longer than one" is a property of the session, not enforced by the lease: a session makes one request at a time and its frame source keeps only the newest frame (step 2), so it never has two waiting.

## Verification

`uv run pytest -q tests/concurrency/test_worker_lease.py tests/concurrency/test_worker_lease_live.py tests/integration/test_pool_lease.py tests/integration/test_worker_arbitration.py tests/integration/test_api_face_search.py`: 63 passed; `lease.py` 100% covered. `ruff`, `mypy`: clean. The full backend gate is in the PR.

## Open issues / follow-ups

The per-class waits under a running camera are measured by the step 7 soak; the burst of 3 changes only on that evidence.
