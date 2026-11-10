# Worker arbitration: queued cancellation and #175's image-path acceptance tests (M6 step 2)

- **Date:** 2026-11-10
- **Milestone / tracker IDs:** M6 step 2; issue #175; TST-069 (first half, recorded with the
  measurement PR)
- **Status:** done for what it covers. Still open in #175: the measured fairness parameter and the
  stress benchmark (D5, the next PR), and batch yields for long runs, which can only be built and
  tested with the video path (M6 steps 4 and 5)
- **Commits:** PR (number recorded when merged): `feat(ml): cancel a queued worker request before it
  runs`, `test: cover worker arbitration through the pipeline and the pool`, `docs: record the worker
  arbitration acceptance tests`

## What changed

- `backend/ml/supervisor/lease.py`: `cancellable(cancelled)` marks the worker requests made inside it
  as cancellable. When such a request's turn comes, `cancelled()` is asked first (holding the turn,
  never the lease's own lock); if it answers true, the request gives its turn up and raises
  `RequestCancelledError` (an `MLUnavailableError`) without reaching the worker. An inference already
  running is never interrupted. A turn given up does not count towards the burst of interactive
  grants (the streak is updated only once the check has passed: found by the Codex review).
- `backend/app/processing/execute_job.py`, inside `execute()` only (agreed with the step 1 session
  on 2026-11-10): the job's detection and representation are made inside `cancellable`, asking the
  same question as the existing boundary check (the job or its run is `CANCELLING`). A
  `RequestCancelledError` settles the cancellation exactly as the boundary check does (segment closed
  `CANCELLED`, run and job `CANCELLED`, private output kept private) and raises
  `ProcessingCancelledError`, so the runner reports `CANCELLED` as before.
- Tests, `tests/integration/test_worker_arbitration.py` (new) and
  `tests/concurrency/test_worker_lease.py`, covering #175's remaining acceptance tests (owner decision
  2026-10-14, "Acceptance tests"):
  - **queued cancellation**: a job cancelled while it waits for the worker, at its detection or at
    its representation, never reaches the worker and is settled `CANCELLED` (through the real
    pipeline: `open_library`, scheduler, executor, the cancel use case; only perception is planted,
    behind a real lease); the turn is given back and nothing is left in the queue;
  - **no transaction or lock across an inference**: during each inference of a real job another
    connection takes SQLite's write lock at once (`BEGIN IMMEDIATE`, timeout 0) and the index
    coordinator's lock is free;
  - **the next safe boundary**: a search that arrives during a job's detection runs as soon as that
    one inference ends, before the job's representation, which was already waiting (through the real
    client pool);
  - **worker failure during a request**, through the real pipeline: the worker dies under a job's
    representation while a search waits; the search runs, the job and its run end `FAILED` with the
    detection kept private (one `PENDING` observation, no representation), and a retry (a new job
    and run) ends with one active observation, one private one from the failed attempt and one
    identity, so nothing is duplicated; through the client pool, the job's `WorkerFailedError`
    reaches the job and the waiting search still runs both its requests;
  - **a cancellation check that cannot read the database**, through the runner: the error is an
    unexpected one, as from the boundary check (the runner raises it after settling the job and run
    `FAILED` with `UNEXPECTED_ERROR`), the request never reaches the worker and the turn is free;
  - lease units: a cancelled waiting request is asked once, at its turn, and the next request runs;
    a request that is not cancelled runs, and the scope ends with its block; a turn given up does
    not count towards the burst (this test fails without the streak fix); a check that raises frees
    the turn.

What the earlier work already covered (cited, not repeated): interactive first, FIFO within a class,
the bounded burst, one request at a time and release in `finally` (PR #213,
`tests/concurrency/test_worker_lease.py`); shutdown refusing queued requests and draining the active
output (`test_pool_lease.py`, `test_runtime_perception_client.py`); worker crash and restart with a
single live process (PR #235, `test_runtime_perception_client.py`, `test_ml_supervisor.py`).

## Why

The owner's locked decision of 2026-10-14 on #175 (point 5: "queued requests can be cancelled
without entering inference"; point 6: no database transaction or filesystem lock across inference;
the acceptance tests list) and M6 step 2's acceptance in `docs/plans/M6_PLAN.md`.

## Decisions

> **Decision 2026-11-10 (delegated decision; the owner: "accept all 11 and i'll leave the rest of
> the decisions entirely to you"):** the yield unit is one worker request. An image job already
> yields between its detection and its representation, and an import of many images is many jobs,
> each yielding at both; that is the "bounded, checkpointable batch" for images, and each unit
> settles its own private output before the next turn. A video's frames (M6 steps 4 and 5) will take
> one turn per frame batch, with the batch size measured there. Nothing is batched across turns
> today, so there is no batch size to configure yet.

> **Decision 2026-11-10 (delegated decision):** a queued request's cancellation is asked at its
> turn rather than by waking the queue from the cancel route. It costs one short database read per
> processing inference, keeps the cancel route unchanged, and still means a cancelled request never
> enters inference; the wait it gave up is at most the requests ahead of it (each one inference).

> **Decision 2026-11-10 (delegated decision):** face search is not made cancellable: a search
> abandoned by its caller has no cancellation record to ask, and it holds the worker for two
> inferences at most.

## Verification

Run on 2026-11-10 on Windows, on this branch rebased over PR #235 and revision 0011 (main
`0af25a6`):

- `uv run ruff format --check .` (318 files formatted), `uv run ruff check .` (all checks passed),
  `uv run mypy` and `uv run mypy --platform linux` (no issues, 309 files).
- `uv run pytest -q --cov`: **3,270 passed**, 3 deselected, coverage **100%** (10,954 statements,
  2,242 branches). After the review fixes (the streak fix and the new tests), again: **3,274
  passed**, 3 deselected, coverage **100%** (10,955 statements, 2,242 branches); the last commit
  (`test: settle a failing cancellation check through the runner`) changes that one test and this
  verification record, not the backend code; the test file was run on its own twice (7 passed each
  time). (An earlier full run on the branch, before the rebase, had one
  `WinError 183` shared-memory collision with another session's run and was not counted.)
- The new tests were run five times in a row before the gate (5 passed each time). One first draft
  of the "next boundary" test expected the search's representation before the job's; it failed,
  correctly: the job's representation was already waiting when the search's detection ended, and
  the search's representation had not asked yet. The test now asserts what the lease promises (the
  search runs at the next boundary) and does not depend on that race.
- Not verified here: CI on the PR head (checked before merging).

## Open issues / follow-ups

- Per-class wait and execution times, queue depth and the stress benchmark (D5) follow in the next
  PR, which also records TST-069.
