# Face search goes before background processing on the one worker (issue #175)

- **Date:** 2026-10-16
- **Milestone / tracker IDs:** M5 backlog; issue #175 (first part); TST-056 (face search), TST-068
  and TST-069 (M6, the arbitration half)
- **Status:** partial: worker-level priority with starvation protection is built and tested; batch
  yield boundaries for long runs (videos, M6), cancellation of a queued request, the measured fairness
  parameter and the per-class metrics are not
- **Commits:** PR (number recorded when merged): `feat(ml): serve face search before background work`,
  `docs: record the worker priority lease`

## What changed

- `backend/ml/supervisor/lease.py` (new): `WorkerLease`, the turn-taking on one worker. An
  interactive request goes before a background one; within a class, first come first served; after
  `BURST` (3) interactive grants in a row a waiting background request goes first; one request holds
  the worker at a time; the lease is released in `finally`. `interactive()` marks the requests made
  inside it as interactive (a context variable, so it follows the thread that made them);
  `is_interactive()` reads the mark. Each grant logs its wait at debug level.
- `backend/ml/supervisor/supervisor.py`: `MLSupervisor.execute` takes its turn on the lease before
  the existing request lock, so every inference, from any caller, goes through it. Starting,
  stopping, pinging and releasing outputs do not (they are quick and are not inference).
- `backend/app/recognition/face_query.py`: face search runs its detect and represent inside
  `interactive()`. Processing is unchanged and so background.
- Tests: `tests/concurrency/test_worker_lease.py` (8: interactive before waiting background work,
  FIFO within a class, a stream of searches lets background work through after the burst, the streak
  counts from the last background grant, never two holders at once under twelve mixed threads, a
  failing request releases the worker, the mark stays inside `interactive()`, a burst below one is
  refused, and the supervisor waits its turn on the lease before it runs a request);
  `tests/integration/test_api_face_search.py`: a face search's perception is marked interactive and
  processing's is not.

## Why

Issue #175 and the owner's locked decision on it (2026-10-14): one persistent worker shared through
cooperative priority scheduling with starvation protection; interactive before background at the next
safe boundary, never preempting an inference; FIFO within a class; bounded interactive grants so
background work progresses; the lease released on every path; no database transaction or file lock
held across an inference. Before this, the supervisor's request lock was taken in whatever order the
threads arrived, so a face search could wait behind any number of processing requests.

## Decisions

- **The safe boundary is one inference** (one detect or one represent call). For images that is
  already short; a video's frames will be their own inferences, so the same lease serves M6 without a
  new boundary.
- **The burst is a constant (3),** marked `ponytail:`: the decision asks for the fairness parameter
  to be chosen from a benchmark, which needs real long runs (M6). Three means a stream of searches
  delays a processing step by at most three searches.
- **Interactivity is a context variable,** not a new parameter on every client: face search is the
  only interactive caller, and the client factories are shared with processing and with tests.
- **Not built (listed for the M6 work):** batch yield boundaries for long jobs, cancelling a request
  while it waits, per-class wait and queue metrics beyond the debug log, and the latency targets the
  decision says to set after measuring. A waiting request is cancelled when it reaches the worker (the
  executor checks cancellation between inferences, as before).

## Verification

- `uv run pytest -q tests/concurrency/test_worker_lease.py tests/integration/test_api_face_search.py
  tests/integration/test_ml_supervisor.py`: 64 passed. Full backend gate: see the PR.
- The ordering tests hold the worker, line requests up until the lease reports them queued (a polled
  condition with a deadline, not a fixed sleep), then read the order they were served in.

## Open issues / follow-ups

- #175 stays open for the parts listed under *Not built*.
