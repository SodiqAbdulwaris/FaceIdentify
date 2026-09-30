# M2: Storage Manager, storage usage

- **Date:** 2026-09-30
- **Milestone / tracker IDs:** M2 (TST-025, now complete)
- **Status:** done (the last TST-025 follow-up)
- **Commits:** PR #21: `refactor(storage): make the plain-directory check public`,
  `feat(sources): report storage usage`, `test(sources): add storage usage tests`,
  `docs: record storage usage`, `fix(sources): count only owned workspaces and report what is
  unknown`, `docs: record the storage usage review`

## What changed

- `backend/app/sources/storage_usage.py`: `storage_usage(session, roots, workspaces)` returns a
  `StorageUsage`:
  - `managed` (per kind: artifact count and bytes) and `managed_bytes`: `AVAILABLE` managed artifacts,
    from the recorded `size_bytes`, in one query;
  - `recycled_bytes`: the part of that associated with Sources in the Recycle Bin (their originals
    and thumbnails, each artifact once). An artifact another row also references is included, so
    this is an *upper bound* on what purging the bin frees;
  - `referenced_artifacts` / `referenced_bytes` / `referenced_size_unknown`: the user's external
    originals, reported apart; only known sizes are summed and the rest are counted as unknown;
  - `workspace_bytes` / `workspace_unreadable`: the job workspaces this manager made, measured on
    disk, and how many of their directories could not be listed (so the figure is an undercount);
  - `volume_total_bytes` / `volume_free_bytes` for the volume the library lives on.
  `measure_directory(path)` totals regular files iteratively, without entering any link, junction or
  other reparse point.
- `backend/infrastructure/storage/workspaces.py`: `_is_plain_directory` became the public
  `is_plain_directory`, so the usage walk and the workspace manager share one definition of "a real
  directory" (no behaviour change).
- Tests: `tests/integration/test_storage_usage.py` (16).

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
  referenced therefore contributes nothing to `recycled_bytes`. A referenced artifact with no
  recorded size is counted as *unknown*, never as zero bytes.
- **The Recycle Bin share counts each artifact once**, however many binned Sources reference it (a
  shared thumbnail), and counts only `RECYCLED` Sources. It is *associated with* the bin, not
  "what purging frees": an artifact an active Source also uses stays in use, and which bytes permanent
  deletion frees is that use case's rule (TST-031), so the report does not claim to know.
- **`os.walk(followlinks=False)` was not used**: on Windows it still descends into a junction (found
  by the test, which counted 100 kB of a folder the workspace merely pointed at). The walk uses
  `scandir` and only enters plain directories. It is iterative (depth cannot exhaust the stack),
  treats a directory that vanishes mid-walk as absent, and counts one it cannot list in
  `workspace_unreadable` instead of crashing or silently undercounting.
- **Only workspaces the manager made are measured** (`WorkspaceManager.existing()`: marked, real
  directories), never whatever else is under `temp/jobs/`.

## Verification

- `uv run ruff format --check .`, `uv run ruff check .`, `uv run mypy` and `uv run mypy --platform
  linux`: clean.
- `HYPOTHESIS_PROFILE=ci uv run pytest --cov -q`: 515 passed (16 new, 0 regressions in the 499
  before); `backend/` coverage 100%. The new file was run 5 times in a row before review and 5 after
  the fixes: 0 failures.
- Mutation checks, each reverted and confirmed byte-identical: 14 valid ones on the filters, the
  per-kind sums, the Recycle Bin query, the workspace walk and the volume figures. Five survived at
  first: the workspace-link case (a real bug, above), a source in neither the active nor the recycled
  state, an active source with a thumbnail, and two mutations that were invalid or equivalent
  (`UNION` against `UNION ALL` makes no difference under `IN`, which de-duplicates, so the query now
  uses the cheaper `UNION ALL` and the comment names the real guarantee). The tests were extended for
  the real gaps. All others are caught.
- **Not verified:** a workspace on a network share, and very large workspaces (the walk is
  recursive, sized for a scratch directory, not a library).

After the review, 9 more mutations on the rewritten module (measuring the whole jobs directory,
each of the two error handlers, dropping the unreadable count, the unknown-size arithmetic and its
query, and the plain-directory check): 8 caught. One survived, visiting directories in a different
order, which cannot change a sum and is equivalent. An inner `FileNotFoundError` handler the review
asked for around each file was deleted instead: on Windows a file's size comes from the directory
listing itself, so it cannot fail there and no test can reach it.

## Independent review (Codex CLI, read-only, disposable worktree): request-changes, addressed

| # | Finding | Resolution |
|---|---|---|
| H1 | Workspace bytes count everything under `temp/jobs`, including entries the workspace manager does not consider its own | Fixed: only `WorkspaceManager.existing()` (marked, real directories) is measured. A test has an unmarked same-named directory, a file and another directory, all excluded |
| H2 | The walk fails on `PermissionError` or a directory vanishing, and is recursive | Fixed: iterative; a vanished directory is absent, an unlistable one is counted in `workspace_unreadable`. Tests for both, through a `scandir` that fails for one path, and a 40-level tree. A deliberately recursion-limited test was not kept: the implementation cannot recurse, and the depth a Windows path allows does not reach Python's limit |
| M1 | `recycled_bytes` says "what purging would free" but includes an artifact an active Source also uses | Fixed in the claim, not the number: it is documented and named as associated with the bin and an upper bound, and a test pins the shared case. Reclaimable bytes are permanent deletion's rule (TST-031) |
| M2 | Referenced sizes are nullable; `coalesce(sum, 0)` reports unknown as zero | Fixed: `referenced_size_unknown` counts them and only known sizes are summed. Test with two unknown sizes |
| M3 | TST-025 `PASSING` is not justified | The gaps it names (unowned entries, traversal failures, the recycled-versus-shared distinction) are now defined and tested, so the status stands; the tracker states the verified scope. Root reparse points are not separately tested (the walk's root is a workspace the manager verified as a plain directory) |

The reviewer found the `UNION ALL` + `IN` de-duplication, `NULL` thumbnails and `SUM` over the
integer column correct, and did not run the tests.

## Open issues / follow-ups

- A user-facing "storage" view and the disk-pressure policy are API/scheduler work (M4/M6).
- **TST-025 is now complete.** The remaining Storage Manager contracts are deletion (TST-031) and
  recovery beyond artifacts (TST-030).
