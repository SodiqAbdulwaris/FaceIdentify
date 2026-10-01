# M2: ExecutionSegment and Checkpoint repositories

- **Date:** 2026-10-01
- **Milestone / tracker IDs:** M2 (TST-022, partly: the second and third repositories)
- **Status:** done for `execution_segments` and `processing_checkpoints`
- **Commits:** PR (number added when opened): `feat(processing): add segment and checkpoint
  repositories`, `test(processing): add the segment and checkpoint contract tests`, `docs: record
  the segment and checkpoint repositories`

## What changed

- `backend/app/processing/repository.py`: `SegmentRepository` (`append`, `get`, `list_for_run`,
  `close`) and `CheckpointRepository` (`append`, `get`, `latest_valid`, `final_valid`,
  `invalidate`), the "ExecutionSegment/Checkpoint" row of persistence §26.
- `tests/integration/test_processing_repositories.py` (19 tests), against real SQLite with separate
  sessions and threads.

## Why

TST-022, continued after [the Job repository](2026-10-01-m2-job-repository.md). These two tables
carry the constraints recovery and acceptance rely on (§14, §16): unique ordinals per run, one
`RUNNING` segment per run, one `VALID` `FINAL` checkpoint per run. A repository's contract here is
that those hold under concurrent writers, which only real SQLite can show.

## Decisions

- **Same rules as `JobRepository`:** join the caller's transaction, never commit, every change one
  guarded statement. The same limit applies and is stated in the module: a caller that read earlier
  in the transaction can meet `SQLITE_BUSY_SNAPSHOT` (CONTEXT open question 20, the user's).
- **Ordinals are allocated inside the `INSERT`** (`coalesce(max(ordinal), -1) + 1` as a scalar
  subquery), so allocating and inserting cannot be separated by another writer. Sixteen checkpoint
  writers on four threads got ordinals 0 to 15, none repeated or skipped. The unique index stays as
  the backstop.
- **The partial unique indexes are relied on, not re-checked in Python.** A second running segment
  or a second valid final checkpoint is the database's `IntegrityError`; deciding what it means (for
  example "invalidate the old final first") belongs to the use case. Two threads starting a segment
  for one run at once get one segment and one refusal.
- **Segments are closed, never reopened** (§14): `close` only moves a `RUNNING` segment, to
  `COMPLETED`, `FAILED`, `INTERRUPTED` or `ABANDONED`; any other target is a `ValueError`, and a
  closed segment is left exactly as it is.
- **`latest_valid(run, before_ordinal=...)` is how recovery moves backward** (§16): when a payload
  cannot be read, ask again below that checkpoint's ordinal. `invalidate` is one-way.
- **`close` and `invalidate` change the database, not the object a caller holds**; `get` and the
  list refresh, and the module says to re-read. (My first test of this read the held object and
  failed; the test, not the code, was wrong.)
- **Not built:** updating `processing_runs.current_checkpoint_id` (that is the use case's decision
  with the run's revision), and acceptance logic.

## Verification

- `uv run ruff format --check .`, `uv run ruff check .`, `uv run mypy` and `uv run mypy --platform
  linux`: clean.
- `HYPOTHESIS_PROFILE=ci uv run pytest --cov -q`: 777 passed (19 new, 0 regressions in the 758
  before); `backend/` coverage 100%. The new file was run 5 times in a row: 19 passed each time.
- Mutation checks, each reverted and confirmed byte-identical: 18 (the ordinal seed, increment and
  per-run filter; the running-only guard, the closing-state guard, reason and end time on close;
  newest-first, the valid filter and `before_ordinal`; the final-kind and valid filters; the
  invalidate guard and reason; the initial `VALID`; both `get` refreshes). Three survived at first
  and were fixed in the tests: both `get` refreshes (a test now holds a row in a session that does
  not expire on commit and shows it is refreshed) and the list ordering (a test now gives the first
  row inserted the highest ordinal). One remains, equivalent and kept on purpose: removing the
  `ORDER BY` from `list_for_run` changes nothing, because SQLite reads the `(run, ordinal)` unique
  index in order, but the contract should not depend on the query plan.
- **Not verified:** anything outside these two tables; `current_checkpoint_id` maintenance.

## Open issues / follow-ups

- TST-022 continues with IndexOperation (the coordinator builds its own statements today), Source,
  ProcessingRun and the rest of §26, each when a use case needs it.
