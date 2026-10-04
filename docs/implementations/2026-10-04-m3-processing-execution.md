# M3: private single-image processing execution

- **Date:** 2026-10-04
- **Milestone / tracker IDs:** M3 step 10 · TST-038, TST-039, TST-040, TST-041, TST-042
- **Status:** partial
- **Commits:** pending PR

## What changed

Added `ExecuteProcessingJob`, the post-claim executor for one image ProcessingRun. It reloads the
run/source/artifact and frozen configuration, plans exactly the frozen detector/export/embedder
selection, loads and decodes the original, runs detection and representation, and settles each
result in short UnitOfWork transactions as private PENDING output. It then rebuilds the run-local
pool, reads the injected global derived index, assesses/reasons each face, and records private
CREATE_NEW, MATCH_EXISTING, or ABSTAIN decisions. CREATE_NEW creates only a PENDING identity;
nothing here activates SQLite rows, creates occurrences, allocates ANN keys, or wakes the index.

The executor appends an INTERMEDIATE checkpoint after observations and representations are
durably private, advances `current_checkpoint_id`, and only appends FINAL after all private
decisions are settled. FINAL closes the lifecycle segment and moves the run to FINALIZING; the
Job deliberately remains RUNNING for the separate acceptance transaction. Cooperative
cancellation is observed before loading the run and between external work units, closes the
segment with `CANCELLED`, and retains already-settled PENDING output. Checkpointing and FINAL also
verify that the running segment belongs to the claimed run. Cancellation or known-failure
settlement terminalizes the run and Job only after it has verified and closed that claimed run's
segment; a stale or unsuccessfully closed segment leaves the whole claim RUNNING for recovery.

## Why

Persistence implementation sections 14--16, 25, and 28 require bounded execution intervals and
durable checkpoint boundaries, while section 28 requires SQLite authority to begin only in the
later acceptance transaction. The executor also follows the approved output-provenance decision:
the observation and representation writers record the actual detector/embedder runtime variants,
rather than treating the frozen request or compatibility space as execution provenance.

## Decisions

- The first durable private boundary is after perception, before recognition. It can support the
  M3 recovery rule that output without FINAL remains private and is only resumed when a later
  supported recovery path exists.
- Cancellation is cooperative: no code claims to interrupt an in-flight worker request. It is
  checked before decode and after each external operation/short settlement boundary.
- A terminal Job may never be written while its claimed run remains RUNNING because a segment was
  stale or could not close. The executor therefore leaves an unsettled claim intact for startup
  recovery rather than creating a terminal lifecycle mismatch.
- No fallback segment history was invented. Persistence implementation section 14 says a provider,
  export, or variant change closes/starts a segment, whereas the owner decision of 2026-10-03 says
  segments are not split by detector versus embedder stage. `PerceptionClient` currently exposes
  the actual successful variants but not a fallback event stream. The output provenance is correct,
  but the precise segment treatment of a mid-run provider fallback remains an open specification
  conflict that must be resolved before claiming the fallback matrix complete.

## Verification

- `uv run pytest tests/integration/test_execute_processing_job.py -q -p no:cacheprovider --cov=backend.app.processing.execute_job --cov-branch --cov-report=term-missing` -- 56 passed; executor 100% line and branch coverage.
- `uv run ruff format --check .` -- 200 files already formatted.
- `uv run ruff check .` -- passed.
- `uv run mypy` and `uv run mypy --platform linux` -- passed.
- `$env:HYPOTHESIS_PROFILE='ci'; uv run pytest --cov -q -p no:cacheprovider` -- 2,203 passed in 191.44 seconds after the final lifecycle hardening; total line and branch coverage 100%.
- After that clean baseline, mutating the active-image guard from `or` to `and` caused the
  recycled-source parameter of `test_input_revalidates_durable_run_source_and_original` to fail.
  The file SHA-256 before and after restoration was
  `A812CADA6E4CF0F12D3DA7073527966C827CAF6AA2B12839FA79BBAFD3022FA1`.
- After the second clean baseline, changing each new segment-owner comparison from `!=` to `==`
  made its checkpoint/finalization foreign-segment test fail. The source SHA-256 before and after
  both restorations was `5FCC78B0FF8CE7753513FAF30C90CC81A10538C3E978DDC23E2FEA57A3FFF084`.
- After the final corrected baseline (2,203 passed in 191.44 seconds, 100% coverage), mutating
  either `closed` guard to terminalize after a failed close, or either `settled` guard to write a
  Job at the wrong lifecycle point, made the relevant cancellation/failure tests fail. The source
  was restored byte-identically after all four probes; SHA-256:
  `31FB43644EFDDC98C66C45EF70A11FBC42D5A359FCE7EE5CF20D2E0F99A2ED39`.

## Open issues / follow-ups

- Independent review of PR #101 found and this branch fixed the pre-load cancellation ordering,
  segment ownership checks, and a second lifecycle finding: the initial hardening still allowed a
  foreign or unclosable segment to leave its claimed segment RUNNING while terminalizing the
  run/Job. Its fallback finding is the specification conflict below, not a dismissed review
  comment.
- Resolve the fallback-segment conflict above; then exercise actual fallback history through the
  executor.
- Step 11 remains the only acceptance/ANN authority boundary. It must validate FINAL idempotently,
  activate output atomically, create occurrences/index operations, and wake the coordinator only
  after commit.
- Step 12 must interpret FINAL during startup recovery and classify earlier private output as
  resumable or not-resumable without rerunning unsafe work.
