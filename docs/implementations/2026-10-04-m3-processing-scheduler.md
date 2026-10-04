# M3: processing scheduler claim/start boundary

- **Date:** 2026-10-04
- **Milestone / tracker IDs:** M3 step 10
- **Status:** partial
- **Commits:** pending PR

## What changed

Added `ProcessingScheduler.claim_source_job`. It filters the durable queue to `PROCESS_SOURCE`
jobs, atomically claims one, changes its `PENDING` ProcessingRun to `RUNNING`, and appends the
single running lifecycle ExecutionSegment. A malformed or stale job is recorded as failed without
creating a segment.

## Why

The claim/start boundary is a short SQLite transaction. Media decoding, worker inference, and
recognition remain outside it, as required by API and Contracts §2.4. This is the first execution
half of M3 step 10; it deliberately does not yet perform the pipeline or write a FINAL checkpoint.

## Verification

- `uv run pytest tests/integration/test_processing_scheduler.py tests/integration/test_job_repository.py -q -p no:cacheprovider` — 30 passed.
- Ruff format/check and mypy for the changed scheduler, repository, and tests — passed.
- `$env:HYPOTHESIS_PROFILE='ci'; uv run pytest --cov -q -p no:cacheprovider` — passed with 100% coverage before mutation testing.
- Reversing the nonblank-owner and job-type eligibility guards each made the focused tests fail;
  both files were restored byte-identically.

## Follow-ups

The next execution slice supplies decode, perception, PENDING-output settlement, recognition, and
checkpoint progression; acceptance remains a separate step-11 authority boundary.
