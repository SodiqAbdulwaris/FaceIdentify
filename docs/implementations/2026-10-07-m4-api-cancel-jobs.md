# M4 W3.4: cancelling a run, and reading jobs

- **Date:** 2026-10-07
- **Milestone / tracker IDs:** M4 W3 · TST-045 (endpoint schemas), TST-047 (state-changing commands), TST-060
- **Status:** partial; W3 continues with identities, occurrences, observations, media and system status
- **Commits:** PR (this change): `feat(api): cancel a processing run and read jobs`

## What changed

- `backend/app/processing/cancel.py` (new): `CancelProcessingUseCase` writes the cancellation
  *request* (until now only the executor's observation and recovery's settlement existed). In one
  transaction that takes the run's write lock first:
  - a **queued** job (run `PENDING`) is cancelled outright: job and run `CANCELLED`, no lease, so
    the scheduler never claims it;
  - a **running** job (run `RUNNING`) is asked to stop: job and run `CANCELLING`, lease kept; the
    executor settles `CANCELLED` at its next safe boundary (private output stays private), and
    recovery settles a request a crash left behind;
  - a run already `CANCELLING` or `CANCELLED` is a repeat (`ALREADY`): nothing is written;
  - `FINALIZING` (its FINAL result is being made authoritative), over, paused or interrupted runs
    are refused (`CancelError`); an unknown run is `RunNotFoundError`.
- `POST /processing-runs/{id}/cancel` (202, returns the run with its job): 404 `RUN_NOT_FOUND`, 409
  `RUN_NOT_CANCELLABLE` with the reason.
- `backend/api/routes/jobs.py` (new): `GET /jobs` (filters `state`, `type`; keyset-paginated, newest
  first, cursor bound to the filters), `GET /jobs/{id}` (type, state, priority, attempt, progress,
  run, `previous_job_id` lineage, `failure_code`, timestamps) and `POST /jobs/{id}/cancel`
  (delegates to the job's run, one rule for both; a job with no run is 409 `JOB_NOT_CANCELLABLE`).
  404 `JOB_NOT_FOUND`.

## Why

W3 of the completion plan: a user must be able to stop work they asked for, and the UI needs the
job resource for the processing view.

## Decisions

None new. Pause and resume (spec sections 6 and 13) are not built: pausing is not part of the M4
definition of done, and a `PAUSED` or `PAUSING` run is therefore not cancellable here yet. Cancelling
a `FINALIZING` run is refused, consistent with the 2026-10-06 decision to keep the final guard
(cancellation before FINAL reaches `CANCELLED`; after FINAL the result is accepted).

## Verification

- `tests/integration/test_cancel_processing.py` (8, real library, planted perception): a queued run
  is cancelled and never claimed (no perception calls); a repeat changes nothing (revision
  unchanged); a cancel requested *during* work (job and run `CANCELLING`, lease held, repeat is
  `ALREADY`) ends `CANCELLED` with no identity created; a `FINALIZING` run is refused and still
  accepted; a completed and a failed run are refused; a pending run with no job; an unknown run.
- `tests/integration/test_api_jobs.py` (7): cancel through the run and through the job, repeats,
  over/unknown runs, job without a run, a job read with its lineage, listing newest first with
  filters, ties and paging, validation of filters and cursors.
- `cancel.py`, `jobs.py` and `processing.py` are at 100% line and branch.
- Mutation probes (16: repeat handling, each state guard, each target state, run write, both list
  filters, cursor context and tie-break, ordering, the no-run guard, lineage, both status
  mappings): all killed after tests closed the survivors (cursor context for jobs, job lineage).
  Two guards that were unobservable were deleted instead: the run-state check on the queued branch
  (a queued job's run is always `PENDING`) and the job-type filter (a run has exactly one job). A
  probe of the tie-break caught that a broken cursor makes an unbounded paging loop hang, so the
  paging loops in the tests are now bounded.
- Full gate (2026-10-07): ruff format/check and native/Linux mypy pass; `HYPOTHESIS_PROFILE=ci uv run
  pytest --cov -q -p no:cacheprovider` - **2,495 passed**, 100% coverage.
