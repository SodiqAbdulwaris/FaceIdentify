# M2: Storage Manager, referenced artifacts

- **Date:** 2026-09-30
- **Milestone / tracker IDs:** M2 (TST-025 in progress)
- **Status:** partial (referenced imports and missing-original detection; relinking, workspaces,
  recycle/restore, usage and cleanup follow in their own PRs)
- **Commits:** PR #15: `refactor(sources): let artifact transitions name a
  storage mode`, `feat(storage): inspect external files for referenced imports`,
  `feat(sources): record referenced artifacts and track their availability`,
  `test(sources): add referenced artifact tests`, `docs: record referenced artifacts`,
  `fix(sources): treat only a vanished file as missing`, `docs: record the referenced artifact review`

## What changed

- `backend/infrastructure/storage/referenced.py`: `inspect_referenced_file(path, roots)` validates
  an external file and fingerprints it (SHA-256 and size) *before* any transaction, as API and
  Contracts §57 describes. It refuses a relative path, a missing file, a directory, an unreadable
  file, and any file inside the library root or the machine-local root (after resolving links, so a
  junction cannot smuggle one in). It records the resolved path. It only reads.
- `backend/infrastructure/storage/files.py`: `digest_path(path)`, the streamed hash that
  `ManagedFileStore.digest` already used, made public so external files reuse it.
- `backend/app/sources/referenced_artifacts.py`:
  - `add_referenced_artifact(session, inspected, ...)`: a flush-only primitive that records
    `Artifact(SOURCE_ORIGINAL, REFERENCED, AVAILABLE)` with the fingerprint, so the future import use
    case can commit it together with the Source (§57).
  - `reverify_referenced_artifact(session_factory, artifact_id, ...)`: compares the file with the
    recorded fingerprint and records the result. Missing file → `MISSING` /
    `REFERENCED_FILE_MISSING`; size or hash differs → `MISSING` / `REFERENCED_CONTENT_CHANGED`; a
    `MISSING` artifact whose file matches again → `AVAILABLE`. The file is read outside any
    transaction, the write is guarded by the state that was read, and an unchanged result writes
    nothing. The Source row is never touched.
- `backend/app/sources/artifact_storage.py`: `_transition` became `transition_artifact` with a
  `storage_mode` keyword (default `MANAGED`), so referenced transitions share the same guarded
  `UPDATE`. No behaviour change for managed artifacts.
- Tests: `tests/integration/test_referenced_artifacts.py` (32). The directory-link helper moved from
  `test_storage_files.py` to `tests/fixtures/links.py` so both files share it.

## Why

TST-025 lists "referenced imports" and "missing referenced files" (tracker;
IMPLEMENTATION_ARCHITECTURE §23.5: "keep the Source record, mark availability `MISSING`"; API and
Contracts §52, §57, §58).

## Decisions

- **Two steps, like the managed protocol.** Inspection is filesystem work and happens outside a
  transaction; the primitive only flushes. Hashing a multi-gigabyte video therefore never holds a
  database transaction open.
- **A changed file is not the original.** Content that no longer matches the fingerprint makes the
  artifact `MISSING` (with its own code), not `AVAILABLE`: a different file is replacement, not the
  original (§59). The application never rewrites or "repairs" the file.
- **A file that is present but cannot be read changes nothing.** `reverify` raises the `OSError`
  rather than recording `MISSING`, because a locked file (an antivirus scan, an editor) is not
  evidence that the media is gone. The same reasoning as recovery's `skipped`.
- **Size is compared before hashing**, so a changed large file is not read to learn it differs.
- **An artifact with no fingerprint is checked for existence only.** §16.2 allows hashing very large
  media asynchronously, and the schema does not require a hash for `REFERENCED` rows. This
  implementation always records one, so today this only covers rows written by something else.
- **Files inside the application's own roots are refused as references.** They would be reported as
  managed orphans, and `cache/` and `temp/` are disposable. This is a guard this task added, not a
  spec rule.
- **The resolved path is recorded**, not the path as typed, so a link or 8.3 alias does not change
  meaning later. A user who later repoints a symlink is treated like any other change.
- **`RELOCATED` is not used.** §58 allows it "only if it proves useful as an explicit recovery
  state"; relinking (next PR) returns a moved file to `AVAILABLE` directly.

## Verification

- `uv run ruff format --check .`, `uv run ruff check .`, `uv run mypy` and `uv run mypy --platform
  linux`: clean.
- `HYPOTHESIS_PROFILE=ci uv run pytest --cov -q`: 401 passed (32 new, 0 regressions in the 369
  before); `backend/` coverage 100%.
- The new file was run 5 times in a row before review and 3 after the fix: 0 failures.
- Mutation checks, each reverted and confirmed byte-identical with a diff: 16 mutations (dropping
  the absolute-path check, either root of the storage-root refusal, `resolve(strict=True)`,
  recording the unresolved path, not catching link loops, the size shortcut, the no-fingerprint
  branch, the no-op early return, the state guard on the write, the AVAILABLE/MISSING state guard,
  the REFERENCED mode guard, not clearing the failure code, conflating the two failure codes, the
  `available_at` stamp, and the storage-mode parameter). One survived at first (the no-op early
  return: writing the same values again is invisible to state assertions), so a test now counts the
  writes a re-check issues. All 16 are caught. After the review, 4 more on the stat-based
  classification (below), all caught, one only after the test was made to raise winerror 21.
- **Not verified:** behaviour of a UNC or network path, or a removable drive that is unplugged. A
  missing drive looks like a missing file, which is the intended outcome, but no test uses one.

## Independent review (Codex CLI, read-only, disposable worktree): request-changes, addressed

| # | Finding | Resolution |
|---|---|---|
| M1 | `Path.is_file()` suppresses some `OSError`s, so a file that is denied or on an unreachable drive could be recorded `MISSING`, contradicting the "unreadable changes nothing" contract; also a race between the existence check and the hash | `reverify` now classifies with an explicit `stat`: only `FileNotFoundError`, `NotADirectoryError` or a non-regular file mean missing (including a file that vanishes while being hashed); every other `OSError` propagates and changes nothing. New tests: access denied, winerror 21 (device not ready; `is_file` returns False for exactly this one, so the first version of the test did *not* catch the regression), a file deleted mid-read, and a directory in the file's place |
| L1 | The module docstring named a `relink_referenced_artifact` that does not exist yet | Removed |
| L2 | The test commit is 444 changed lines with no explanation in its body | Not split: it is one new test module (426 lines) plus a 14-line shared helper it needs and the 18-line move of that helper; a separate helper-move commit would add a module nothing imports yet. Published history is not rewritten; explained on the PR |

The reviewer also confirmed: the state-guarded update prevents stale overwrites, link and junction
resolution and the in-root rejection are sound, and it found no spec deviation in API §§51-60,
architecture §§16 and 23.5 or persistence §4.1. It did not run the tests.

## Open issues / follow-ups

- Relinking, temporary workspaces, recycle/restore, storage usage and conservative cleanup remain
  for TST-025.
- A batch pass over every referenced artifact (for startup or a "verify library" action) is not
  built; it belongs with startup recovery (TST-030) and the lifespan work. `reverify` is the unit it
  will call.
- **New open question (CONTEXT 24):** nothing in the specs says when a `Source` becomes
  `UNAVAILABLE`. This work leaves the Source untouched when its original goes missing, following
  §23.5 and API §57, and the artifact's state is the record.
