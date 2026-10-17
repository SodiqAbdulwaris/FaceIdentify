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
- `backend/api/real.py` and `backend/app/runtime/perception_client.py`: `ClientPool` owns the one
  `WorkerLease` and gives it to every `PerceptionClient` it hands out; the client takes its turn
  around each `supervisor.execute`. The pool keeps a supervisor per plan, so the lease sits above the
  supervisors: a job on a frozen CPU-only plan and a search on a DirectML plan queue in the same
  line, each still running its own plan's variants. Starting a plan's worker happens inside
  `execute`, so it is serialized under the lease too. Stopping, pinging and releasing outputs do not
  take a turn (quick, not inference). A lease whose wait is interrupted removes its own ticket and
  wakes the others, and the post-grant logging is inside the release `finally`.
- `WorkerLease.close()` (called first by `ClientPool.close()`): every waiting request and every later
  one is refused with `WorkerClosedError` (an `MLUnavailableError`), so a queued request is never
  granted a worker that shutdown has stopped and restarted. A request already running finishes.
- `backend/api/routes/face_search.py`, `backend/api/startup.py`: the `face_search_gate` lock is
  removed. It held searches outside the lease queue, so a queued background inference could be
  chosen before a waiting search. Memory stays bounded by `face_search_slots` (3 in flight); the
  lease serializes the inferences.
- `backend/app/recognition/face_query.py`: face search runs its detect and represent inside
  `interactive()`. Processing is unchanged and so background.
- Tests: `tests/concurrency/test_worker_lease.py` (ordering, FIFO, burst, mutual exclusion gated by
  events and the lease's queue state, release after a failing body or a failure right after the
  grant, an interrupted wait leaves no ticket, the mark on one thread through nested and
  exceptional exits, a burst below one refused); `tests/integration/test_pool_lease.py`: requests
  on two plans share one line and a search on one plan goes before background work on another;
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
- **The burst is a constant (3),** confirmed by the owner on 2026-10-16, marked `ponytail:`: the decision asks for the fairness parameter
  to be chosen from a benchmark, which needs real long runs (M6). Three means a stream of searches
  delays a processing step by at most three searches.
- **One lease, not yet one process:** the pool still keeps a supervisor, and so a worker process,
  per plan, because a worker is started with its plan's configuration. The locked decision's
  contract (one inference at a time, one queue, interactive first) is met by the pool-level lease.
  Merging the processes would mean one worker whose configuration covers every plan, or restarting
  it on a plan change, which touches the worker config, the supervisor and the pool's tests. Cost
  until then: more than one model process may be resident.

  > **Decision 2026-10-17:** the owner accepted the deferral: "Accept the deferral: merge #213 once
  > green, and open a follow-up on #175 to make the pool own exactly one worker process across
  > plans (restart on plan change), with tests proving only one worker is spawned." The follow-up
  > is [#221](https://github.com/SodiqAbdulwaris/FaceIdentify/issues/221).
- **Interactivity is a context variable,** not a new parameter on every client: face search is the
  only interactive caller, and the client factories are shared with processing and with tests.
- **Not built (listed for the M6 work):** batch yield boundaries for long jobs, cancelling a request
  while it waits, per-class wait and queue metrics beyond the debug log, and the latency targets the
  decision says to set after measuring. A cancelled request that is already waiting still gets its turn
  and runs its one inference; the executor checks cancellation after it, between inferences, as
  before.

## Verification

- `uv run pytest -q tests/concurrency/test_worker_lease.py tests/integration/test_pool_lease.py
  tests/integration/test_api_face_search.py tests/integration/test_real_profile.py`: passed; full
  backend suite: 3229 passed, ruff and mypy clean (2026-10-17).
- The tests hold the worker, line requests up until an instrumented condition reports each parked, and gate each
  step on events; every wait is asserted to have succeeded and every thread to have ended.

## Open issues / follow-ups

- #175 stays open for the parts listed under *Not built* and for the single worker process above (#221).
