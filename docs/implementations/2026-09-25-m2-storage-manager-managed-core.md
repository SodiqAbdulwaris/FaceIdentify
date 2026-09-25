# M2: Storage Manager, managed core

- **Date:** 2026-09-25
- **Milestone / tracker IDs:** M2 (TST-025 in progress, TST-026)
- **Status:** done (the managed-core slice)
- **Commits:** PR #14: `feat(storage): add the storage layout and crash-safe managed file store`,
  `feat(sources): add the managed artifact lifecycle and startup recovery`,
  `test(storage): add storage manager and artifact lifecycle tests`,
  `docs: align the storage layout to tech-stack §15`, `docs: record m2 storage manager core`

## What changed

- `backend/infrastructure/storage/layout.py`: `StorageRoots` (the user-selected library root and
  machine-local state), `ensure_layout()`, `database_path` (`<Library>/database/library.db`), and
  `path_for(key)`, which turns a storage key into a path only if the key is canonical, relative,
  inside a managed directory (`originals/`, `crops/`, `thumbnails/`, `models/`) and still inside the
  library after resolving links.
- `backend/infrastructure/storage/files.py`: `ManagedFileStore`. `store()` writes to
  `staging/<artifact-id>.part`, hashes (SHA-256) while streaming, fsyncs, then `os.replace`s onto the
  final key; it never overwrites different content, and storing identical content again is a no-op.
  Also `open`, `digest`, idempotent `delete`, `managed_files`, `staging_files`. No database code.
- `backend/app/sources/artifact_storage.py`: the managed artifact lifecycle.
  - Flush-only primitives: `reserve_managed_artifact` (PENDING row owning its final key),
    `mark_artifact_available`, `request_artifact_deletion`, `finalize_artifact_deletion`. Every
    transition is an `UPDATE` guarded by the row's current state and `storage_mode = MANAGED`.
  - Orchestrators that own their commits: `create_managed_artifact` (reserve → commit → write outside
    any transaction → AVAILABLE → commit) and `delete_managed_artifact` (intent → commit → remove
    bytes → DELETED → commit).
  - `recover_artifacts` (startup): finishes a PENDING artifact whose file reached its final key,
    marks one whose write never completed `MISSING`/`WRITE_NOT_COMPLETED`, completes or retries
    `DELETING`/`DELETE_FAILED`, and removes leftover staging files. Idempotent.
  - `verify_artifact` (hash and size) and `scan_storage` (AVAILABLE artifacts with no file, files no
    live artifact owns, stray staging files — reported, never repaired).
- Tests: `tests/integration/test_storage_files.py` (32) and `tests/integration/test_artifact_storage.py`
  (27), plus `storage_roots`/`file_store` fixtures on the existing sandboxed roots.
- Specs: persistence §1 and architecture §16.3 aligned to tech-stack §15, which gains `staging/`
  (owner decision, below).

## Why

TST-025 ("Managed and referenced storage contracts pass") and TST-026 ("Pending and available states
are correct"), and the M2 items that depend on a Storage Manager. PERSISTENCE_IMPLEMENTATION.md §4.1
defines the three-step creation and symmetric deletion protocols, §28 the recovery actions for
`PENDING` and `DELETING` artifacts; API and Contracts §51–§60 define the boundary ("SQLite owns
meaning. The filesystem owns bytes.").

## Decisions

- **Owner decisions (2026-09-25), asked because three specs disagreed:** (1) tech-stack §15's two
  roots are the layout; persistence §1 (a single `data/` folder, given "for example") and
  architecture §16.3 (a `library/` tree with a `recycle/` folder that contradicted "recycling never
  moves bytes") were aligned to it. (2) Managed writes stage in `<Library>/staging/`, not
  `%LOCALAPPDATA%/temp`: an atomic rename cannot cross drives, and the library may live on another
  drive. (3) This PR is the managed core; referenced imports, relinking, workspaces, usage and
  cleanup follow.
- **Two layers.** Bytes (`backend/infrastructure/storage/`) know nothing about the database;
  coordination with `artifacts` lives in the application layer. The primitives flush but never
  commit, so the future source-import use case can commit AVAILABLE and its new Source together
  (API and Contracts §56); a test does exactly that.
- **A file at a final path is complete by construction.** Only a fully written, fsynced staging file
  is ever renamed there, so recovery can safely finish a PENDING artifact whose final file exists (the
  lost step was the AVAILABLE commit) by hashing it.
- **An abandoned reservation becomes `MISSING` with `failure_code = WRITE_NOT_COMPLETED`.** The
  Artifact enum has no `FAILED` state; `MISSING` is §4.1's "verified failure to resolve bytes", and
  nothing references such a row (a Source is only created with AVAILABLE). A write that fails in a
  running process is settled the same way immediately; a crash is settled by recovery.
- **`DELETE_FAILED` is retried by recovery** (§28: "retain retryable failure").
- **Storage keys are canonical and ID-oriented:** `<kind directory>/<artifact id hex>`, no
  extension (the MIME type is on the row). Writing tests found that `PurePosixPath` silently
  normalizes `originals/./x` to `originals/x`, which `path_for` would have accepted; the scan compares
  key strings, so one file could have been reported as both orphaned and present. Non-canonical keys
  are now refused.
- **Links cannot escape the library.** After the lexical checks, the resolved path must still be
  inside the library root; a test plants a directory junction in `originals/` pointing outside.
- **`RUNTIME_PACKAGE` artifacts are refused:** API §54 keeps runtime/model packages in "the
  specialized runtime package layer", and runtime packages are machine-local.
- **Known ceilings (marked `ponytail:` in code):** `os.replace` is atomic on NTFS but not
  write-through, so a power cut immediately after it can lose the rename (never tear the file); one
  flat directory per kind (shard by id prefix if a directory grows past ~100k files).
- **Not decided here:** whether an artifact *should* be deleted (API §51: the caller decides), and
  where the library root itself comes from (CONTEXT open question 17, narrowed: the database path is
  now defined relative to it).

## Verification

- `HYPOTHESIS_PROFILE=ci uv run pytest --cov --cov-report=term-missing -q`: 347 passed (59 new, no
  regressions in the prior 288); `backend/` coverage 100%; strict mypy and ruff clean.
- The new tests were run 10 more times in a row: 0 failures.
- Coverage first showed two unreachable branches (an error path after a transition had already
  proved the row, and a redundant `is_dir` check); they were removed rather than tested.
- Mutation checks, 12 in total, each reverted (byte-identical via `diff`): writing straight to the
  final path (21 tests fail), overwriting different content, skipping the fsync, accepting
  non-canonical keys, accepting `..`, dropping the resolved-path containment check, letting a
  REFERENCED artifact be deleted, allowing AVAILABLE from any state, recovery ignoring a completed
  final file, recovery keeping staging files, not settling a reservation after a write error — all
  caught. The twelfth, "scan reports rows in any state as missing", **survived** at first; the
  clean-scan test now includes a MISSING and a PENDING artifact with no file, and catches it.

## Independent review

Not yet run at the time of writing this entry; see the PR for the outcome.

## Open issues / follow-ups

- TST-025 remaining: referenced imports and missing referenced originals, relinking, temporary
  workspaces, recycle/restore, storage usage, conservative cleanup.
- Wiring `recover_artifacts` into application startup (after migrations, per §28's ordering) belongs
  with the startup/lifespan work, which does not exist yet.
- CONTEXT open question 17 (narrowed).
