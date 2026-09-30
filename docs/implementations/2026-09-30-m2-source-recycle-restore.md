# M2: Source recycle and restore

- **Date:** 2026-09-30
- **Milestone / tracker IDs:** M2 (TST-025 in progress)
- **Status:** partial (recycle/restore; storage usage and conservative cleanup follow)
- **Commits:** PR (number added when opened): `feat(sources): recycle and restore a Source`,
  `test(sources): add recycle and restore tests`, `docs: record source recycle and restore`

## What changed

- `backend/app/sources/lifecycle.py`:
  - `recycle_source(session, source_id, *, expected_revision, clock)`: `ACTIVE` → `RECYCLED`, sets
    `recycled_at` and `updated_at`, bumps the revision.
  - `restore_source(...)`: `RECYCLED` → `ACTIVE`, clears `recycled_at`, bumps the revision. Refused
    when the Source's original artifact is `DELETING`, `DELETE_FAILED` or `DELETED` (its bytes are
    gone or going).
  - `SourceLifecycleError` and `StaleSourceRevisionError`.
  - Both use the shared `optimistic_locked_update` with the required current state in the `WHERE`,
    flush but never commit (the caller owns the transaction, persistence §26), and touch only the
    `sources` row.
- Tests: `tests/integration/test_source_recycle.py` (21).

## Why

TST-025 lists recycle/restore (IMPLEMENTATION_ARCHITECTURE §23's Storage Manager tests: "managed/
referenced imports, hashing, workspaces, atomic finalization, recycle/restore, permanent deletion,
missing references, relinking, and orphan recovery"). API and Contracts §5.5-§5.6 and §60: "Logical
recycle is primarily database state. Files are not normally physically moved merely because a Source
was recycled." processing-architecture-v1 §30: a recycled Source's "original media and associated
evidence remain recoverable... restoration should normally avoid reprocessing".

## Decisions

- **Recycle is the Source row only.** A test commits a managed original with real bytes, a
  processing run and the Source's `current_processing_run_id`, recycles and restores, and proves
  every other table is row-for-row identical, the bytes are unchanged (content and modification
  time), nothing is left in staging, and the processing link is kept. That is what "no reprocessing
  on restore" requires.
- **Only `ACTIVE` can be recycled and only `RECYCLED` restored.** Recycling an already-recycled
  Source, or one that is `DELETING`, `DELETED` or `UNAVAILABLE`, is an error rather than a silent
  no-op: the caller acts on a stale view. (`UNAVAILABLE` is unassigned today: CONTEXT open question
  24.) An idempotent `DELETE` route, if the API wants one, is that layer's decision.
- **A stale revision is reported ahead of a wrong state**, since an out-of-date view of the row is
  the more useful thing to tell the caller.
- **"Restores... where possible" (§5.6) is read as:** not possible only if the original's bytes are
  gone or being removed. A `MISSING` original does *not* block a restore: a missing referenced
  original keeps its Source (architecture §23.5) and the user can still "Locate File". This reading
  is this task's interpretation of an unspecified phrase; recorded here rather than as a conflict
  because no spec says otherwise.
- **Permanent deletion is not part of this.** It is a separate use case that first creates durable
  deletion intent (persistence §4.2) and is TST-031.
- The errors are the Source feature's own (`SourceLifecycleError`), not the Identity Manager's, to
  keep the feature modules from depending on each other.

## Verification

- `uv run ruff format --check .`, `uv run ruff check .`, `uv run mypy` and `uv run mypy --platform
  linux`: clean.
- `HYPOTHESIS_PROFILE=ci uv run pytest --cov -q`: 462 passed (21 new, 0 regressions in the 441
  before); `backend/` coverage 100%. The new file was run 5 times in a row: 21 passed each time.
- Mutation checks, each reverted and confirmed byte-identical: 16 (the state guard, the revision
  and missing-row branches, each of the timestamps and `recycled_at` for both operations, swapping a
  state, the bytes-gone check, removing each state from `BYTES_GONE` and adding `MISSING` to it, and
  committing instead of flushing). One survived at first (checking the original for a Source that
  is not recycled, which only changes the error message), and a test now asserts the state is
  reported first. All 16 caught.
- The first test run failed because the frozen clock never advances, so `updated_at` could not move:
  the tests now advance it.

## Open issues / follow-ups

- Storage usage and conservative cleanup remain for TST-025.
- No API route or UI calls these yet (M4+).
