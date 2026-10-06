# M4 W2.2: the processing runner

- **Date:** 2026-10-07
- **Milestone / tracker IDs:** M4 W2 · TST-060 (the claim and transition rules M4 exercises)
- **Status:** done (the loop and its wiring into the API process are W2.3)
- **Commits:** PR (this change): `feat(processing): run one queued job end to end`

## What changed

- `backend/app/processing/runner.py` (new): `ProcessingRunner.run_once()` claims one queued
  `PROCESS_SOURCE` job (`ProcessingScheduler`), executes it privately (`ExecuteProcessingJob`) and
  accepts it (`AcceptProcessingRunUseCase`), and returns a `RunOutcome`:
  `IDLE`, `ACCEPTED`, `CANCELLED`, `FAILED` (a failure the executor settled), `NOT_ACCEPTABLE` (a
  refused FINAL). A refused FINAL makes the run `NOT_RESUMABLE` and the job `FAILED` in one
  transaction, the same decision startup recovery applies; private output stays private. An error
  after a committed acceptance (the index wake) is reported in the outcome, never an undone run. An
  error before the commit propagates and leaves the run `FINALIZING` for recovery. An unrecognised
  defect settles the claimed work `FAILED` (best effort) and is raised. Errors are reported by class
  name only, never a message (it could carry a path).
- `execute_job.py`: the settled-failure list is now `SETTLED_FAILURES`, and `fail_claimed` settles
  claimed work after a defect the executor did not recognise.
- `startup.py`: `mark_run_not_resumable(session, ...)` and `run_state` are public (shared with the
  runner); behaviour unchanged.
- Tests: `tests/integration/test_processing_runner.py` (8) and shared fixtures (`pipeline`,
  `Pipeline.enqueue/executor/runner`) in `tests/fixtures/pipeline.py`.

## Why

W2 needs the unit a scheduler loop repeats, with every outcome decided and tested before a loop and
the API process depend on it. Recovery-before-scheduling is kept: the loop (W2.3) is created only
after the library is reported open.

## Decisions

None new. The refused-FINAL job state is `FAILED` (observed in process, with a code), where startup
recovery leaves it `INTERRUPTED` (found after a crash); a retry is allowed from either.

## Verification

- Full gate (2026-10-07): ruff format/check and native/Linux mypy pass; `HYPOTHESIS_PROFILE=ci uv run
  pytest --cov -q -p no:cacheprovider` — **2,403 passed in 264.69s, 100% line and branch coverage**.
- Eight runner tests on a real library with planted perception cover each outcome and the durable
  state it leaves; six guard mutations (refusal not settled, any acceptance error treated as accepted,
  a defect not settled, the wake error dropped, the job left running, a cancellation reported as a
  failure) were each caught. 100% line and branch coverage of `runner.py`.

## Open issues / follow-ups

W2.3: the loop (idle wait, wake, stop), started after the library opens, and the readiness `scheduler`
capability. Lease expiry of a job whose runner died mid-flight is still handled only by startup
recovery.
