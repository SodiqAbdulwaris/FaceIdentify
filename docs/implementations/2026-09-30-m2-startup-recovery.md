# M2: startup recovery

- **Date:** 2026-09-30
- **Milestone / tracker IDs:** M2 (TST-030, in progress)
- **Status:** partial (the specified recovery actions; what is left is listed below and in CONTEXT 26)
- **Commits:** PR #24: `feat(sources): mark missing referenced originals without hashing`,
  `feat(memory): validate every space's index`, `feat(recovery): reconcile interrupted state at
  startup`, `test(recovery): add startup recovery tests`, `docs: record startup recovery`,
  `fix(recovery): clear stale leases, requeue failures, keep live work`,
  `docs: record the startup recovery review`

## What changed

- `backend/app/recovery/startup.py`: `recover_on_startup(session_factory, store, workspaces,
  coordinator, *, clock, index_batch, max_index_passes)` runs the recovery and index steps of the
  startup order (architecture §22, persistence §28) once, in this order, and returns a
  `StartupReport`:
  1. **Artifacts**: `recover_artifacts` (interrupted managed writes and deletions), then
     `mark_missing_referenced_originals`.
  2. **In-flight work**: `interrupt_in_flight_work` marks every `RUNNING` job, processing run and
     execution segment `INTERRUPTED` in one transaction, each a guarded `UPDATE ... RETURNING`. A job
     loses its lease (owner and expiry; the heartbeat is kept as evidence); a run's revision is
     bumped; a segment ends at recovery time with no `ended_reason`.
  3. **Workspaces**: `WorkspaceManager.remove_orphans` with `jobs_that_may_resume` (every job that is
     not `COMPLETED`, `FAILED` or `CANCELLED`).
  4. **Indexes**: `IndexCoordinator.validate_indexes` (new) opens every `ACTIVE` space's index and
     rebuilds one that is missing or unusable; a sound one is untouched; a deprecated space is not
     indexed. `IndexCoordinator.requeue_failed_operations` (new) gives every `FAILED`
     `IndexOperation` one fresh set of attempts (persistence §28: "pending/failed").
  5. **Pending `IndexOperation`s**: up to `max_index_passes` passes of `apply_pending(index_batch)`,
     stopping early when a pass did nothing.
- `backend/app/sources/referenced_artifacts.py`: `mark_missing_referenced_originals` marks an
  `AVAILABLE` referenced original whose file is gone `MISSING` by existence alone (one `stat`, no
  hashing), leaving the Source alone.
- `StartupReport.repaired_nothing` (no repair was made: the state a second run must reach),
  `unresolved` (what was tried and could not be finished, or is left for later, by name) and `clean`
  (neither).
- Tests: `tests/recovery/test_startup_recovery.py` (72). The `recovery` marker comes from the
  directory, as the suite's convention says.

## Why

TST-030 ("Interrupted state is reconciled"). PERSISTENCE_IMPLEMENTATION.md §28's table, the
architecture's recovery scope (§23.2: "Interrupted active runs/segments become `INTERRUPTED`") and
its list of states the recovery tests must construct (§25.13): a RUNNING Job with a dead worker, a
RUNNING ProcessingRun, an active ExecutionSegment, a PENDING Artifact, an abandoned workspace, a
pending IndexOperation and a missing referenced Source. Recovery must be idempotent and "safe to
repeat after another crash" (§28, §23.8).

## Decisions

- **Every state in §25.13 that has defined semantics is built and reconciled in one test**, with its
  outcome checked; a second test proves states recovery does not own (a paused job, a `FINALIZING`
  or `PAUSING` run, finished work) are left exactly as found, revision included.
- **Idempotence is checked against the whole database and both storage roots.** After one run, a
  second run reports `repaired_nothing` and leaves every row of every table, and every file and its
  size under the library and machine-local roots, identical.
- **A crash after any step is survivable.** Five tests make the process die right after each step
  finishes (artifacts, in-flight work, workspaces, index validation, index catch-up); a further run
  converges to the same end state and is itself then a no-op.
- **Existence-only check for referenced originals.** Hashing every referenced video at every start
  would make startup scale with the user's media. A file that is gone is marked `MISSING`; a file that
  returned is *not* marked `AVAILABLE` without its content being checked (that is
  `reverify_referenced_artifact` or a relink); a file that cannot be examined is left alone.
- **A segment's `ended_reason` is left `NULL`.** The reasons the schema offers (`WORKER_CRASH`,
  `SHUTDOWN`, ...) each claim a cause; nothing recorded why this one stopped.
- **The startup limits are required and have no defaults** (`index_batch`, `max_index_passes`): they
  bound how much index catch-up startup does before handing over to readiness, an unmeasured
  threshold. Operations not reached stay `PENDING` for the scheduler. A failing operation cannot keep
  startup spinning: once it is backing off, a pass finds nothing due and the loop stops.
- **`validate_indexes` exists because `apply_pending` only opens a space's index when that space has
  pending operations**, so an index that went missing or corrupt while nothing was pending would have
  been noticed only when recognition found it empty.
- **Jobs are interrupted, not requeued.** §28 allows "requeue only when safe", and no spec defines
  safe; `INTERRUPTED` is always correct (resuming creates new work) and loses nothing.

## Verification

- `uv run ruff format --check .`, `uv run ruff check .`, `uv run mypy` and `uv run mypy --platform
  linux`: clean.
- `HYPOTHESIS_PROFILE=ci uv run pytest --cov -q`: 692 passed (72 new, 0 regressions in the 620
  before); `backend/` coverage 100%. The new file was run 5 times in a row before review and 5 after
  the fixes: 0 failures.
- Mutation checks, each reverted and confirmed byte-identical: 27 valid ones (each state filter and
  each value the interrupt writes, the lease fields, the revision bump, the finished-job states, the
  workspace live set, index validation and its active-space filter, each clause of the pass loop and
  its bound, and each branch of the missing-original scan), plus a parametrized test that makes every
  term of `repaired_nothing` matter. 26 were caught; one is equivalent (the `AVAILABLE` filter in the
  missing-original scan: the guarded transition refuses any other state). Two more attempts matched
  formatted text that did not exist and were redone.
- Writing the tests found that the representation factories create their own `RUNNING` runs and
  segments, which recovery correctly interrupts too; the expectations now compare with whatever is
  `RUNNING` in the database beforehand, not just the rows the test named.

After the review, 18 more mutations on the new behaviour (each half of the lease predicate and of
the lease values, both clauses of the workspace live set, the requeue's wiring, state guard,
duplicate guard, attempt reset, due time and ordering, and the unresolved/clean terms). 13 were caught
at once; the survivors were real gaps (a lease held with only an owner or only an expiry, an operation
settled between choosing and writing the requeue) and are now covered. All caught.

## Independent review (Codex CLI, read-only, disposable worktree): request-changes, addressed

| # | Finding | Resolution |
|---|---|---|
| H1 | Recovery's "one process, before workers" is only documented; a second process could interrupt live work | **Not built; it is CONTEXT open question 23** (an exclusive library lock for the backend's lifetime) with its recommendation already recorded, and "invoke only through the startup coordinator before workers start" is the lifespan work, which does not exist yet. Answered on the PR, not decided here |
| H2 | An expired lease on a job that is not `RUNNING` is never touched (§28: "expired/running Job... clear lease") | Fixed: any job still holding a lease has it cleared in the same transaction, its state left alone (what `PAUSING`/`CANCELLING` become is CONTEXT 26). Tests for each state and for an owner-only and an expiry-only lease |
| H3 | `FAILED` index operations have no recovery path (§28: "pending/failed IndexOperation") | Fixed: `requeue_failed_operations` gives each one fresh attempts once per startup (bounded), keeps the diagnostics until the next outcome, skips one that would duplicate a pending twin, and requeues only the newest of failed twins. Tests for each |
| H4 | A workspace of a finished job is deleted even if its linked run is live | Fixed: a job's workspace is also kept while its linked run is in a non-terminal state (contradictory state is recoverable inconsistency, not permission to delete). Test |
| M1 | `SQLITE_BUSY` is not retried around the interrupt transaction | **Not built; CONTEXT open question 20** (`BEGIN IMMEDIATE` plus a whole-transaction retry). The transaction's first statement is already a write, so it queues for the busy timeout instead of failing at once on a stale snapshot. A test injects a fault at the second statement and proves the first is rolled back too |
| M2 | `repaired_nothing` can be true while work is unresolved | Fixed: the predicate keeps its meaning (documented), and `unresolved` and `clean` are added, naming skipped artifacts, left staging files, failed deletions, workspaces that could not be removed, unindexable representations, and operations backing off or out of attempts (foreign entries under `temp/jobs/` are not recovery's work and are not listed). Tests for each field |
| M3 | Tests do not cover linked Job/Run/Segment combinations, failures inside a step, expired leases or failed operations | Added: a test of contradictory combinations (each row judged by its own state), the rollback test above, a crash inside the workspace removal, expired leases and failed operations. The process-level kill-and-restart tests need a backend process and remain open |
| Rule | The 644-line test commit has no rationale | Not split, history not rewritten: one new test module; explained on the PR |

The reviewer confirmed the step order, the single guarded transaction and the existence-only
handling of referenced originals, and did not run the tests.

## Open issues / follow-ups

- **CONTEXT 26 (new):** what startup should do with a run or job that was `PAUSING`, `CANCELLING` or
  `FINALIZING` (left exactly as found today), and the recovery of an interrupted runtime
  installation. The acceptance of a run with a final checkpoint ("revalidate and run acceptance
  without redoing ML") needs `AcceptProcessingRunUseCase`, which is M3.
- `recover_on_startup` is not called by anything: there is no application lifespan yet. It is the
  unit the Startup Coordinator will call, after migrations and before the ML worker.
- The process-level tests that kill a real subprocess (architecture §25.13) need the backend process
  to exist.
