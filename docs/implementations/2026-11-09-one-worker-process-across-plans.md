# One ML worker process across plans (issue #221, M6 step 2)

- **Date:** 2026-11-09
- **Milestone / tracker IDs:** M6 step 2 (D11); issue #221; TST-069 (first half, the arbitration
  half: not changed by this PR alone)
- **Status:** done
- **Commits:** PR (number recorded when merged): `feat(ml): keep one worker process across plans`

## What changed

- `backend/api/real.py`: `ClientPool` still keeps a supervisor per perception plan (a worker is
  started with its plan's configuration, and a supervisor keeps its plan's crash-loop record), but
  only the **active** one may have a worker process. Every client the pool hands out takes its turns
  through `_PlanTurn`: the shared `WorkerLease` first, then `ClientPool.activate(supervisor)`, which
  stops every other plan's supervisor (a SHUTDOWN, killed if it does not acknowledge) before this
  plan's supervisor is allowed to start or use its worker. A supervisor only starts a worker inside
  `execute`, and `execute` is only called inside a turn, so two worker processes are never alive at
  once. A request on the same plan as the running worker stops nothing. A worker that cannot be
  stopped refuses the new plan's request with `MLUnavailableError` (no second process is started
  beside it); the turn is released and stopping is tried again at the next turn.
- Readiness `ml_worker` now reports the state of the active supervisor (the one that last had the
  worker), not a combination of every plan's supervisor: a stopped supervisor of another plan is not
  the worker's state. `NOT_STARTED` until a request has had a turn.
- `backend/app/runtime/perception_client.py`: the client's `lease` parameter is typed by a small
  `Turn` protocol (anything with `held()`), so it accepts the `WorkerLease` or the pool's per-plan
  turn. Behaviour unchanged.

## Why

The locked architecture is one persistent ML worker. PR #213 made every plan's worker share one lease
(one inference at a time) but left one worker *process* per plan alive, each holding its own models in
memory. The owner accepted that deferral on 2026-10-17 and moved it into M6 step 2 (D11, 2026-10-21).
Issue #221 asked for exactly this: restart the worker on a plan change, under the lease, keeping each
request's frozen variant selection, with tests that only one worker process is ever spawned.

## Decisions

> **Decision 2026-11-09 (delegated decision; the owner: "accept all 11 and i'll leave the rest of
> the decisions entirely to you"):** keep a supervisor per plan and stop the others at a plan change,
> rather than one supervisor whose spawn configuration is swapped. A per-plan supervisor keeps that
> plan's crash-loop record (a plan whose worker keeps dying still becomes `FAILED` instead of being
> retried afresh at every plan change), and the existing supervisor, lease and client code is
> unchanged. The cost: requests alternating between two different plans restart the worker at each
> change (seconds each). In practice every job and every search runs the one installed package's plan;
> plans differ only when the providers changed between a job being queued and a search. Marked in the
> code with a `ponytail:` comment.

> **Decision 2026-11-09 (delegated decision):** readiness reports the active supervisor's state only.
> A past failure of another plan's worker is not the state of the worker that runs now.

## Verification

Filled in from the actual runs before the PR is reported ready (see below).

## Open issues / follow-ups

- #175's remaining acceptance tests and the measurement (D5) follow in their own PRs.
