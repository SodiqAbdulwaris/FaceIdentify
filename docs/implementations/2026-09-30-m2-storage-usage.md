# M2: Storage Manager, storage usage

- **Date:** 2026-09-30
- **Milestone / tracker IDs:** M2 (TST-025, now complete)
- **Status:** done (the last TST-025 follow-up)
- **Commits:** PR (number added when opened): `refactor(storage): make the plain-directory check
  public`, `feat(sources): report storage usage`, `test(sources): add storage usage tests`,
  `docs: record storage usage`

## What changed

- `backend/app/sources/storage_usage.py`: `storage_usage(session, roots, workspaces)` returns a
  `StorageUsage`:
  - `managed` (per kind: artifact count and bytes) and `managed_bytes`: `AVAILABLE` managed artifacts,
    from the recorded `size_bytes`, in one query;
  - `recycled_bytes`: the part of that held by Sources in the Recycle Bin (their originals and
    thumbnails, each artifact once), i.e. what purging the bin would free;
  - `referenced_artifacts` / `referenced_bytes`: the user's external originals, reported apart;
  - `workspace_bytes`: the machine-local job workspaces, measured on disk;
  - `volume_total_bytes` / `volume_free_bytes` for the volume the library lives on.
  `directory_bytes(path)` totals regular files without entering any link, junction or other reparse
  point.
- `backend/infrastructure/storage/workspaces.py`: `_is_plain_directory` became the public
  `is_plain_directory`, so the usage walk and the workspace manager share one definition of "a real
  directory" (no behaviour change).
- Tests: `tests/integration/test_storage_usage.py` (9).

## Why

TST-025 lists storage usage; API and Contracts §51 gives it to the Storage Manager;
processing-architecture-v1 §11: "Storage Manager monitors free disk space and managed-storage
usage... The user may free space, manage the Recycle Bin, remove media".

## Decisions

- **It reports; it does not decide.** Pausing storage-producing work when the disk is nearly full is
  the scheduler's job (M6); freeing space is cleanup and permanent deletion. No threshold is chosen
  here (an unmeasured number).
- **Sizes come from the database**, recorded when each artifact became `AVAILABLE`, so a report does
  not walk the library. Only workspaces, which no row describes, are measured on disk. A test
  compares the report with real files.
- **Referenced originals are never counted as ours.** They are the user's files (§52): not space this
  application occupies, and not something purging can free. A recycled Source whose original is
  referenced therefore contributes nothing to `recycled_bytes`.
- **The Recycle Bin share counts each artifact once**, however many binned Sources reference it (a
  shared thumbnail), and counts only `RECYCLED` Sources.
- **`os.walk(followlinks=False)` was not used**: on Windows it still descends into a junction (found
  by the test, which counted 100 kB of a folder the workspace merely pointed at). The walk uses
  `scandir` and only enters plain directories.

## Verification

- `uv run ruff format --check .`, `uv run ruff check .`, `uv run mypy` and `uv run mypy --platform
  linux`: clean.
- `HYPOTHESIS_PROFILE=ci uv run pytest --cov -q`: 508 passed (9 new, 0 regressions in the 499
  before); `backend/` coverage 100%. The new file was run 5 times in a row: 9 passed each time.
- Mutation checks, each reverted and confirmed byte-identical: 14 valid ones on the filters, the
  per-kind sums, the Recycle Bin query, the workspace walk and the volume figures. Five survived at
  first: the workspace-link case (a real bug, above), a source in neither the active nor the recycled
  state, an active source with a thumbnail, and two mutations that were invalid or equivalent
  (`UNION` against `UNION ALL` makes no difference under `IN`, which de-duplicates, so the query now
  uses the cheaper `UNION ALL` and the comment names the real guarantee). The tests were extended for
  the real gaps. All others are caught.
- **Not verified:** a workspace on a network share, and very large workspaces (the walk is
  recursive, sized for a scratch directory, not a library).

## Open issues / follow-ups

- A user-facing "storage" view and the disk-pressure policy are API/scheduler work (M4/M6).
- **TST-025 is now complete.** The remaining Storage Manager contracts are deletion (TST-031) and
  recovery beyond artifacts (TST-030).
