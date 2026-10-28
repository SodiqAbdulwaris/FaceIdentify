# M6 step 1: reprocessing images (implementation outline)

Status: **proposal, 2026-10-22.** Serves issue 180 and `docs/plans/M6_PLAN.md` step 1. The spec text this
outline implements is proposed in the same PR (persistence 12.1, identity model 60.1, API 5.4) and needs the
owner's approval before any code (decision D1). Tracker: TST-061, TST-064, TST-067 (their image halves).

## Schema: Alembic `0011_reprocessing_generations`

- `processing_runs.supersedes_run_id` (nullable self-FK `RESTRICT`, `CHECK != id`); partial unique index on it
  `WHERE state = 'COMPLETED'`.
- `observations`, `representations`, `occurrences`: nullable `superseded_at`; `CHECK (state != 'SUPERSEDED' OR
  superseded_at IS NOT NULL)` (observations also require `superseded_by_run_id`).
- `evidence.kind` CHECK gains `REPROCESS_DECISION_CARRIED_OVER` and `REPROCESS_REVIEW_REQUIRED`.
- No new table and no change to any `state` set. Batch-mode revision following 0002/0005/0010; tests: upgrade of a
  populated 0010 database, downgrade-free `foreign_key_check`, each CHECK rejects a violating row, the unique
  index rejects a second completed superseder.

## Use cases (all in `backend/app/processing/` unless noted)

1. `ReprocessSourceUseCase` (beside `ProcessSourceUseCase`): the checks of persistence 12.1 item 2, one snapshot,
   run with `supersedes_run_id`, `REPROCESS_SOURCE` job. Route `POST /sources/{id}/reprocess` is thin.
2. Process route refuses a source with a current run (`SOURCE_ALREADY_PROCESSED`).
3. Recognition pool excludes the predecessor's representations for a run with `supersedes_run_id`
   (`recognition/retrieval.py` candidate filter; no threshold or policy change).
4. `AcceptProcessingRunUseCase` gains the supersession branch: compare-and-swap on the pointer, `SUPERSEDED`
   updates, REMOVE/ADD operations, carry-over, `_validate_completed` for the repeat case.
5. `correspondence.py` (pure): human-decided test, IoU/cosine/mutual-unique pairing with the D3 constants.
6. Candidate revalidation (`recognition`/coordinator) also requires `processing_run_id == source.current_processing_run_id`.
7. Forget/erasure interaction: suppression of V2 faces over erased V1 faces (item 9a).
8. Job-type-aware acceptance and retry: acceptance today selects only the `PROCESS_SOURCE` job and retry always creates one, so both accept `REPROCESS_SOURCE` for a run with `supersedes_run_id`; retry preserves the job type and copies `supersedes_run_id`; recovery routes a `FINALIZING` reprocess run through the same acceptance. Tests: a reprocess run is accepted; its retry keeps `REPROCESS_SOURCE` and `supersedes_run_id`.
9. Permanent deletion clears `supersedes_run_id` as it clears `parent_run_id` (test: delete a reprocessed source).
10. Carry-over disposes of the pending identity a carried face's `CREATE_NEW` created (kept if another uncarried face uses it, else `DELETED`); test: no extra identity survives. Validation of a completed run accepts the suppressed-face shape of persistence 12.1 item 9a.

## Acceptance tests (issue 180) mapped to tracker rows

| # | Test (real SQLite, USearch, filesystem; clock and id fixtures; no sleep) | Row |
|---|---|---|
| 1 | V1 stays current and queryable while V2 runs; on success V2 is current, V1 `SUPERSEDED` with link and time | TST-061 |
| 2 | V2 failed/cancelled/interrupted before activation leaves every V1 row and the pointer unchanged | TST-064, TST-061 |
| 3 | Real child process killed immediately before, during (inside the transaction) and after activation; restart converges to one generation, no duplicate occurrence or representation | TST-067 |
| 4 | Search, people views, counts, vector results never double-count or show superseded evidence, including during an index rebuild and with a stale index file | TST-061 |
| 5 | Human-decided faces survive only through the D3 correspondence; space change, missing vector and ambiguity produce review evidence and no assignment | TST-061 |
| 6 | Forget and erasure persist across reprocessing and a restart; no forbidden face reappears | TST-067 |
| 7 | Concurrent and repeated reprocess requests and activations are idempotent with one authoritative generation | TST-064 |

Plus unit tests for the correspondence rule (boundaries 0.7/0.9, ties, mutual uniqueness) and migration tests as above.
Coverage stays at 100%.

## Order of work (phase 2, after approval)

migration and tests; domain and `ReprocessSourceUseCase`; pool exclusion and revalidation filter; activation
branch; correspondence and carry-over; forget interaction; route; crash tests; docs (implementation entry, README
row, tracker rows, CONTEXT, PROJECT_STATUS, M6 plan progress).
