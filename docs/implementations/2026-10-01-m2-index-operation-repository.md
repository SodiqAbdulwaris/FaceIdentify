# M2: IndexOperation repository

- **Date:** 2026-10-01
- **Milestone / tracker IDs:** M2 (TST-022, partly: the fourth repository)
- **Status:** partial: done for `index_operations`; TST-022 continues
- **Commits:** [PR 28](https://github.com/SodiqAbdulwaris/FaceIdentify/pull/28): `feat(memory): add the
  index operation repository`, `refactor(memory): run the coordinator's operation statements through
  it`, `test(memory): add the index operation repository contract tests`, `docs: record the index
  operation repository` (review fixes are folded in; see Review)

## What changed

- `backend/app/memory/index_operation_repository.py`: `IndexOperationRepository(session)` with
  `append_batch`, `due`, `failed_ids`, `attempt_counts`, `requeue` and `settle`, and the values
  `NewOperation` and `DueOperation`.
- `backend/app/memory/index_coordinator.py` now uses it for every statement it ran against
  `index_operations` (claiming what is due, listing and requeueing failed operations, reading
  attempt counts and settling outcomes). Behaviour is unchanged: its 100%-covered test suite and the
  recovery suite pass without a single edit (141 tests). Its private `_Claimed` value became the
  repository's `DueOperation`.
- `tests/integration/test_index_operation_repository.py` (22 tests) against real SQLite.

## Why

TST-022, continued. Persistence §26 lists the IndexOperation repository as "append batch,
pending/failed batch, attempt/applied/failed transition". Two callers need it: a use case that
makes a representation ANN-eligible must append operations in the same transaction as that change
(INDEX-01), and the coordinator reads and settles them. Before this, the second existed only as
statements inside the coordinator and the first did not exist, so the first use case would have
written its own, and the two could drift. Moving the statements, not rewriting them, keeps one
source of truth.

## Decisions

- **`append_batch` skips an operation that is already pending instead of failing.** The schema allows
  one `PENDING` operation per `(representation, operation)` because two would say the same thing
  (§17), so a second request is satisfied by the first. It is `INSERT ... ON CONFLICT DO NOTHING`
  on that partial index, with no read first, and the same operation twice in one batch is recorded
  once. It returns the ids actually recorded, in input order; skipped ones are omitted, so the
  result cannot be matched to the input by position, and `new_id` is called for skipped ones too.
  Two threads appending the same operation at the same moment record it once (tested).
- **An opposite pending operation is superseded by deleting it** (CONTEXT open question 27, which
  the user can overrule). §17 says "creating an opposite operation must supersede/coalesce the
  obsolete desired state in the use case" and names no mechanism. My first version left it alone
  and claimed the coordinator would resolve both to what is true. **That was wrong**, and the
  review caught it: the coordinator re-reads authoritative state only for `ADD`; `REMOVE` removes
  unconditionally (§17: "regardless of stale index contents"). So ADD, REMOVE, ADD left the
  queue as ADD, REMOVE (the last ADD skipped as a duplicate of the first) and the coordinator
  would run them in that order, leaving an active representation out of the index. Now each
  operation first deletes a pending operation of the opposite kind for the same representation,
  so that sequence ends with a single pending ADD (tested), and a later operation in one batch
  supersedes an earlier one. Only `PENDING` rows for that representation are deleted (an
  `APPLIED`, a `FAILED` or another representation's are untouched; tested). Deleting, not a
  state: there is no `SUPERSEDED` state, `APPLIED` would claim something that never happened,
  and `FAILED` is requeued at startup, so the row of an operation that was never applied is
  removed. A `SUPERSEDED` state is the alternative and would be a schema change.
- **Same rules as the other repositories:** join the caller's transaction, never commit, one
  statement per change, decided by the database. The coordinator keeps opening its own sessions and
  committing (it has no caller transaction), and keeps reading attempt counts in a separate
  transaction before it writes, because of CONTEXT open question 20.
- **`new_id` is a required argument of `append_batch`**, with no default, so callers inject ids and
  tests stay deterministic.
- **Two statements per operation, not one multi-row `VALUES`:** a single statement binds nine
  variables per row, so a large import (more than about 110 operations on SQLite before 3.32)
  would hit the bound-variable ceiling. Each statement now binds a fixed few.
- **Not validated:** that a `NewOperation`'s `space_id` is its representation's own. The coordinator
  refuses an operation whose space differs when it applies it. **Not built:** any change to how the
  coordinator decides outcomes (retry, backoff and purge stay in the coordinator).

## Verification

- `uv run ruff format --check .`, `uv run ruff check .`, `uv run mypy` and `uv run mypy --platform
  linux`: clean.
- `HYPOTHESIS_PROFILE=ci uv run pytest --cov -q`: 799 passed (22 new, 0 regressions in the 777
  before); `backend/` coverage 100%. The new file and the coordinator's were run 5 times in a row:
  48 passed each time.
- Mutation checks, each reverted and confirmed byte-identical: 25 (the recorded state, attempt count
  and due time; the superseding delete and each of its three conditions; the unknown-kind refusal and
  the opposite mapping; the conflict clause and the use of its result; the due-time and pending
  filters; each part of the due ordering and the limit; the failed filter and its newest-first order;
  the failed guard, the pending-duplicate check and each of its three conditions in requeue; the
  attempt reset; the pending guard, the attempt time and the attempt count in settle). Four survived
  at first, all real test gaps (a requeue of an `APPLIED` operation was shadowed by the duplicate
  check; no test had a pending operation of the opposite kind, or of another representation), and
  tests now cover them.
- **Not verified:** a use case that calls `append_batch` (none exists yet).

## Review

Codex was still over its usage limit, so the independent review was a read-only subagent (an
approved reviewer) in a disposable worktree: request changes.

| Finding | Resolution |
|---|---|
| 1: leaving an opposite pending operation was justified by a claim the code contradicts (`REMOVE` is unconditional), and ADD, REMOVE, ADD could leave the index wrong | Confirmed and fixed: superseding by deletion, with the ADD, REMOVE, ADD test, and CONTEXT open question 27 so the mechanism can be overruled |
| 2: the tracker row named `IndexOperationCoordinator` | Fixed: `IndexCoordinator` |
| 3: the entry cited a commit that did not exist, and the first commit mixed a new repository with the coordinator refactor | Fixed: the branch was rebuilt as `feat`, `refactor`, `test`, `docs`, with the fixes folded in |
| 4: one multi-row `VALUES` binds nine variables per row | Fixed: two statements per operation |
| 5: "in order" and positional matching of returned ids were unstated and untested | Fixed: docstring states it, and a test asserts the input order and that ids identify the recorded rows |
| 6: weak tests (which row was skipped, space recorded, concurrency claimed but untested) | Fixed: the skip tests identify the row, the space is asserted, and two threads appending one operation at the same moment record it once, held together with `rendezvous_before_write` at the first write |
| 7: the coordinator refactor | The reviewer compared it line by line and found behaviour preserved |

## Open issues / follow-ups

- TST-022 continues with Source, ProcessingRun and the rest of §26, each when a use case needs it.
  Representation's ann-key allocation waits for the user's decision on CONTEXT open question 21.
