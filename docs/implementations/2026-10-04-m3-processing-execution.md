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
Every private-output settlement reloads the live run, source, original artifact, execution segment,
and claimed Job after compute and before mutation. A cancellation observed after detector output
settles therefore stops before embedding begins.

The executor appends an INTERMEDIATE checkpoint after observations and representations are
durably private, advances `current_checkpoint_id`, and only appends FINAL after all private
decisions are settled. FINAL closes the lifecycle segment and moves the run to FINALIZING; the
Job deliberately remains RUNNING for the separate acceptance transaction. Cooperative
cancellation is observed before loading the run and between external work units, closes the
segment with `CANCELLED`, and retains already-settled PENDING output. Checkpointing and FINAL also
verify that the running segment belongs to the claimed run. Cancellation or known-failure
settlement terminalizes the run and Job only after it has verified the claimed Job's linkage and
state, then closed that claimed run's segment; a stale, ineligible, or unsuccessfully closed
claim leaves the whole lifecycle RUNNING for recovery. The unexpected final Job-transition failure
also rolls the short settlement back rather than committing a partial terminal lifecycle.

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
- The run write-lock serializes the short terminal settlement. The executor re-reads and validates
  the Job's run linkage and permitted state under that lock before it closes the segment. A final
  guarded Job transition that unexpectedly loses still aborts the UnitOfWork, so it cannot leave a
  terminal run/segment behind.
- No fallback segment history was invented. Persistence implementation section 14 says a provider,
  export, or variant change closes/starts a segment, whereas the owner decision of 2026-10-03 says
  segments are not split by detector versus embedder stage. `PerceptionClient` currently exposes
  the actual successful variants but not a fallback event stream. The output provenance is correct,
  but the precise segment treatment of a mid-run provider fallback remains an open specification
  conflict that must be resolved before claiming the fallback matrix complete.

## Verification

- `uv run pytest tests/integration/test_execute_processing_job.py -q -p no:cacheprovider` -- 67 passed.
- `uv run ruff format --check .` -- 200 files already formatted.
- `uv run ruff check .` -- passed.
- `uv run mypy` and `uv run mypy --platform linux` -- passed.
- `$env:HYPOTHESIS_PROFILE='ci'; uv run pytest --cov -q -p no:cacheprovider` -- 2,209 passed in 181.62 seconds after coherent Job/run/segment settlement hardening; total line and branch coverage 100%.
- After rebasing PR #101 onto the current `main` (including the identity-less-candidate readers and
  IndexCoordinator UnitOfWork slice), the exact full gate passed: 2,231 tests in 408.05 seconds,
  100% coverage. Ruff and both mypy targets also passed; a fresh independent read-only review and
  exact-head CI remain required before merge.
- After the independent rebased review fixed cancellation-after-detection and live settlement
  revalidation, the full unmutated gate passed: 2,236 tests in 208.95 seconds, 100% line and
  branch coverage. The focused executor suite then passed 67 tests.
- Mutation proof after that clean baseline: deleting the post-detection cancellation check made
  `test_cancellation_after_detection_settlement_does_not_start_embedding` fail because embedding
  started; deleting detection-settlement revalidation made
  `test_recycled_source_before_settlement_cannot_persist_detection` fail because embedding
  started. `backend/app/processing/execute_job.py` was restored byte-identically after both
  probes; SHA-256 before and after: `47E60DEAE4436FF9C437A1F2C0C8DD7578B592FCE5B190EF7630134625D7C97B`.
- After that clean baseline, mutating the active-image guard from `or` to `and` caused the
  recycled-source parameter of `test_input_revalidates_durable_run_source_and_original` to fail.
  The file SHA-256 before and after restoration was
  `A812CADA6E4CF0F12D3DA7073527966C827CAF6AA2B12839FA79BBAFD3022FA1`.
- After the second clean baseline, changing each new segment-owner comparison from `!=` to `==`
  made its checkpoint/finalization foreign-segment test fail. The source SHA-256 before and after
  both restorations was `5FCC78B0FF8CE7753513FAF30C90CC81A10538C3E978DDC23E2FEA57A3FFF084`.
- After the final corrected baseline (2,209 passed in 181.62 seconds, 100% coverage), mutating
  either Job/run-link guard, either permitted Job-state guard, or either final Job-transition
  rollback guard made its relevant cancellation/failure test fail. The source was restored
  byte-identically after all six probes; SHA-256:
  `955B31B5B53CCF17FD4D445B079EB8F4F23848C1BAD1B46CCBC33DA9E928CFC2`.

## Open issues / follow-ups

- The independent rebased review found and this branch fixed two additional interleavings:
  cancellation after detector settlement now stops before embedding, and every private-output
  mutation revalidates the live source/original and claimed lifecycle under the write lock. The
  later duplicate lifecycle checks were removed because the validated objects are returned by the
  single guard and cannot change in the same write transaction. A fresh independent review remains
  required after this correction.
- Resolve the fallback-segment conflict above; then exercise actual fallback history through the
  executor.
- Step 11 remains the only acceptance/ANN authority boundary. It must validate FINAL idempotently,
  activate output atomically, create occurrences/index operations, and wake the coordinator only
  after commit.
- Step 12 must interpret FINAL during startup recovery and classify earlier private output as
  resumable or not-resumable without rerunning unsafe work.
