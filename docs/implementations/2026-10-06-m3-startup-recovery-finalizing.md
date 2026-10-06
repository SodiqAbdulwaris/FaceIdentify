# M3 step 12: startup recovery of FINALIZING and pre-FINAL runs

- **Date:** 2026-10-06
- **Milestone / tracker IDs:** M3 step 12 · TST-030 · issue #34
- **Status:** done (pending merge; see PR)
- **Commits:** PR (this change): `feat(recovery): accept FINALIZING runs on startup`

## What changed

- `recover_on_startup` takes an `AcceptProcessingRunUseCase` and, before interrupting in-flight
  work, calls `accept_finalizing_runs`: every `FINALIZING` run is accepted from its valid FINAL
  checkpoint with no ML. The run's job is still `RUNNING` and stays so until acceptance, because
  acceptance requires it (`interrupt_in_flight_work` now skips the `RUNNING` job of a run that is
  still `FINALIZING`); its stale lease is cleared by acceptance itself or the lease sweep.
- A FINAL that acceptance refuses (`AcceptanceError`, including a missing FINAL) leaves the run
  `NOT_RESUMABLE` (`failure_code=FINAL_NOT_ACCEPTABLE`) and its job `INTERRUPTED`; the private
  output is never activated.
- An error after the acceptance transaction committed (the index wake) is classified by reading the
  run back: `COMPLETED` means accepted, the error is reported in `StartupReport.finalizing`
  (`wake_failures`) and the same recovery's index passes apply the durable `ADD` operations. Any
  other error propagates and leaves the run `FINALIZING` for the next start.
- A run that crashed before FINAL is only `INTERRUPTED` (existing step), its PENDING output kept
  private, nothing discarded or requeued.
- `RetryProcessingUseCase` (`backend/app/processing/retry.py`): a retry is a new Job
  (`previous_job_id`, `attempt_number` + 1) and a new PENDING Run (`parent_run_id`) on a copy of
  the frozen snapshot, once per job. Recovery never calls it. `require_processable_image` was
  extracted from `ProcessSourceUseCase` so both share the source check.
- `open_library` builds the acceptance use case (no live index wake yet).
- A test for cancellation immediately before FINAL (the guard that survived the cross-check
  mutation): a job cancelled after the decisions are private reaches `CANCELLED` in-process.
- The FINAL-run test builders moved to `tests/fixtures/final_checkpoint.py` so acceptance and
  recovery tests share them.

## Why

Persistence §16 and §28: a FINAL checkpoint lets startup finish acceptance without rerunning ML.

## Decisions

> **Decision 2026-10-06:** the owner approved following the existing persistence decisions: a
> `FINALIZING`/valid-FINAL run keeps its `RUNNING` job until acceptance runs, stale leases are
> cleared, post-commit wake failures are caught, pre-FINAL crashes become `INTERRUPTED` with PENDING
> output kept private, and a retry is a new Job/Run linked through `previous_job_id`, never a
> discard-and-requeue. Recorded in Persistence §15 and §28 and CONTEXT Q26.

Implementation choices not separately decided (flag if you disagree): a refused FINAL becomes
`NOT_RESUMABLE` (the spec's "safely fail/not-resumable"); a retry copies the old run's snapshot
rather than re-resolving settings.

## Verification

- Full gate (2026-10-06): `ruff format --check`, `ruff check`, `mypy` and `mypy --platform linux`
  pass; `HYPOTHESIS_PROFILE=ci uv run pytest --cov -q -p no:cacheprovider` — **2,348 passed in
  222.39s, 100% line and branch coverage**.
- New matrix `tests/recovery/test_finalizing_recovery.py` (19): acceptance of FINALIZING runs for
  CREATE_NEW, MATCH_EXISTING, ABSTAIN and no-face with ML entry points patched to fail; stale lease
  cleared; interruption alone leaves a FINALIZING job running; corrupted and missing FINAL
  -> `NOT_RESUMABLE`, output private; pre-FINAL crash interrupted and not requeued; mixed start;
  wake failure after commit; failure before commit propagates; repeated recovery and a crash after
  commit are no-ops; retry lineage, once-only, finished/unrelated/live-run refusals, lost scheduler
  wake.
- Mutations (14 Step 12 guards, restored byte-identically): 13 caught. Survivor N12 (retry also
  allowing a `COMPLETED` job) is defensive: the run-state guard already refuses it in every
  consistent state, and no artificial test was added (owner direction).
- The cross-check survivor "cancel check before FINAL" is now caught by the new test.

## Open issues / follow-ups

- The FastAPI lifespan, a live index wake and the scheduler loop are not built, so recovery is
  exercised through `open_library`/`recover_on_startup` only.
- Issue #66 still covers moving the eraser and the remaining recovery writes onto `UnitOfWork`.
