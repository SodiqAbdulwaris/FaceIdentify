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
  `path_for(key)`, which turns a storage key into a path only if it is exactly the generated form
  `<originals|crops|thumbnails|models>/<32 lower-case hex>` and, after resolving links, still sits
  in that real managed directory.
- `backend/infrastructure/storage/files.py`: `ManagedFileStore`. `store()` writes to
  `staging/<artifact-id>.part` (the name derived from the key), hashes (SHA-256) while streaming,
  fsyncs, then `os.rename`s onto the final key. On Windows that rename refuses an existing
  destination atomically, so different content is never overwritten, and storing identical content
  again is a no-op.
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
    `DELETING`/`DELETE_FAILED`, and removes a staging file only when it belongs to a managed
    artifact that is no longer PENDING (its write is settled; ids are never reused). Idempotent, and
    tolerant: an unreadable file or unusable key (including a junction loop) is reported (`skipped`)
    and left for the next start; a staging file it does not own, or cannot remove, is reported
    (`staging_left`), never deleted.
  - `verify_artifact` (hash and size) and `scan_storage` (AVAILABLE artifacts with no file, files no
    live artifact owns, stray staging files, rows with an unusable key — reported, never repaired).
- Tests: `tests/integration/test_storage_files.py` (47) and `tests/integration/test_artifact_storage.py`
  (34), plus `storage_roots`/`file_store` fixtures on the existing sandboxed roots.
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
- **A storage key must be exactly the generated form**, `<kind directory>/<artifact id hex>`, no
  extension (the MIME type is on the row). The first version validated keys leniently: writing tests
  found `PurePosixPath` silently normalizing `originals/./x`, and the review then showed Windows
  aliases (`<key>.`, `<key> `, upper case, device names such as `NUL`, `:stream`) passing the check
  while opening another file. An exact pattern leaves no room for any of that.
- **Links cannot escape a managed directory.** After the pattern check, the resolved file must sit in
  the real `<library>/<directory>`; tests plant a junction in place of `crops/` (pointing into
  `database/`) and a junction at a key's own path.
- **Recovery never deletes what it does not own, and never aborts on one bad row.** Per §28 ("clean
  owned temp data") it removes a `.part` file only when its artifact's write is settled (any state
  but PENDING). A file it cannot read is left PENDING for the next start rather than guessed MISSING
  (an antivirus lock would otherwise lose a complete import), and its staging file is kept.
- **`RUNTIME_PACKAGE` artifacts are refused:** API §54 keeps runtime/model packages in "the
  specialized runtime package layer", and runtime packages are machine-local.
- **Known ceilings:** the rename is atomic on NTFS but not write-through, so a power cut immediately
  after it can lose the rename (never tear the file), and that import is then lost; one flat
  directory per kind (shard by id prefix past ~100k files) — both marked `ponytail:` in code. If the
  final AVAILABLE commit *fails* (e.g. "database is locked"), the caller sees an error but recovery
  later finishes the artifact, which may then be referenced by nothing; finding unreferenced
  artifacts belongs with conservative cleanup (a test pins the current behaviour). No retry is made
  when antivirus briefly holds a new file during the rename; a failed rename fails that import.
- **`recover_artifacts` assumes no other process is using the library.** Single-instance per
  machine is the desktop shell's job (tech-stack §2); a library on a shared drive opened from two
  machines is CONTEXT open question 23.
- **Not decided here:** whether an artifact *should* be deleted (API §51: the caller decides), and
  where the library root itself comes from (CONTEXT open question 17, narrowed: the database path is
  now defined relative to it).

## Verification

- `HYPOTHESIS_PROFILE=ci uv run pytest --cov --cov-report=term-missing -q`: 369 passed (81 new, no
  regressions in the prior 288); `backend/` coverage 100%; strict mypy and ruff clean.
- The new tests were run 10 times in a row before review, and 10 after each review round: 0
  failures.
- CI's static job runs mypy on **Linux**, where `_winapi.CreateJunction` is not declared, so a test
  helper branching on `os.name` failed there while passing locally on Windows. It now branches on
  `sys.platform` (which mypy narrows), `uv run mypy --platform linux` passes, and that command was
  added to CONTEXT's local checks. The PR's first push had the same problem and it went unnoticed
  because its CI result was not checked before moving on to review.
- Coverage first showed two unreachable branches (an error path after a transition had already
  proved the row, and a redundant `is_dir` check); they were removed rather than tested.
- Mutation checks. Before review, 12; one ("scan reports rows in any state as missing")
  **survived** at first, and the clean-scan test was strengthened to catch it. After the review
  changes, 15 against the final code, each reverted (byte-identical via `diff`), **all caught**:
  writing straight to the final path (23 tests fail), `os.rename` becoming `os.replace` (caught by
  the write-race test), overwriting different content, skipping the fsync, a lenient key pattern,
  dropping the directory containment check, checking containment against the library root only
  (caught by the junction-into-`database/` test), deleting a REFERENCED artifact, AVAILABLE from any
  state, recovery ignoring a completed final file, recovery deleting unowned staging files, recovery
  keeping its own, recovery aborting on a bad row, not settling a reservation after a write error,
  and the scan reporting rows in any state. After the second review, 6 more, all caught: the old
  check-then-replace code restored (now caught by the corrected race test, which did *not* catch it
  before), `os.replace` again, the cleanup's error hiding the real one, a junction loop escaping
  `path_for`, staging owners including PENDING rows, and owners limited to this run.

## Independent review (subagent, disposable worktree): request-changes, addressed

The reviewer read the code, the specs and the relevant CPython `ntpath`/`pathlib` source, and probed
`resolve()`/`is_file()` read-only; it could not run the tests.

| # | Finding | Resolution |
|---|---|---|
| M1 | Nothing enforces "recovery runs before anything writes", and recovery deleted *every* staging file; a second instance (or a second machine on a shared-drive library) would destroy another writer's in-flight file and mark its row MISSING | Recovery now removes only the staging files of the PENDING artifacts it settles (§28: "owned temp data") and reports the rest. The single-writer assumption is stated on the function. A library lock for shared drives is **CONTEXT open question 23** (a decision, not built here) |
| M2 | A *failed* AVAILABLE commit leaves PENDING bytes that recovery later finalizes, possibly referenced by nothing | Recorded as a ceiling; a test pins the behaviour; detecting unreferenced artifacts goes with conservative cleanup |
| M3 | One locked file or bad key aborted recovery (and the scan) on every start | Per-row tolerance: `skipped` / `staging_left` in the report, `unsafe_keys` in the scan; tests include a real open handle blocking a delete on Windows |
| L1 | `path_for` accepted Windows aliases (trailing dot/space, case, device names, `:stream`); containment was against the library root, not the managed directory | Exact generated-key pattern; containment per managed directory. The reviewer's suggested check (`is_relative_to((root / dir).resolve())`) would itself pass a junctioned directory, since resolving the directory follows the junction, so the resolved file's parent is compared with the *unresolved* directory instead; a test proves it |
| L2 | "Never overwrites" was check-then-act | `os.rename` (atomic refusal on Windows) replaces the pre-check; a test injects a file between write and rename |
| L3 | `staging_name` unvalidated | Parameter removed; derived from the key |
| L4 | No retry when antivirus briefly holds a new file | Recorded as a ceiling / follow-up (unverified on this machine) |
| L5 | Test gaps | Added, as above, plus `DELETE_FAILED` in the not-pending parametrisation |

The reviewer also confirmed by reading: the normal create/delete paths and every state guard are
correct; the monkeypatched orchestrator steps are looked up at call time, so those crash tests are
genuine; "complete by construction" holds under a single writer; recovery is idempotent if it crashes
itself; no filesystem work happens inside a transaction in the orchestrators; and the three spec
edits agree with each other and with the code.

### Re-review of the fixes (subagent, fresh worktree): request-changes (minor), addressed

Scoped to the fix commits only. It verified from CPython's `ntpath`/`pathlib` that the new
containment check cannot falsely refuse legitimate keys (8.3 short names, case, `\\?\` prefixes and
a junctioned library root are normalised the same way on both sides) and confirmed the author's
point that the first reviewer's suggested check would have passed a junctioned directory.

| # | Finding | Resolution |
|---|---|---|
| 1 | Regression from the M1 fix: a staging file whose artifact had already settled (e.g. a failed write left a locked `.part`) could never be removed, so the scan stayed unclean forever | Recovery now owns the staging file of any managed artifact that is not PENDING, looked up by id; the test now shows the next start removing it, and a skipped PENDING artifact keeping its own |
| 2 | `path_for` could raise `RuntimeError("Symlink loop")` or a stray `OSError`, which escape recovery's and the scan's handlers, contradicting the M3 fix | Confirmed on this machine with a mutual junction loop, then translated to `UnsafeStorageKeyError` in `path_for`; a test builds the loop with `mklink /J` |
| 3 | The write-race test injected the file inside `fsync`, which the old check-then-replace code also survived | The file is now injected inside `os.rename`, just before the real rename; restoring the old code now fails the test |
| 4 | A failed cleanup unlink in `finally` replaced the real error | The cleanup's `OSError` is suppressed; a test holds the staging file open and asserts the surfaced error is the rename's (it names both paths) |

## Open issues / follow-ups

- TST-025 remaining: referenced imports and missing referenced originals, relinking, temporary
  workspaces, recycle/restore, storage usage, conservative cleanup.
- Wiring `recover_artifacts` into application startup (after migrations, per §28's ordering) belongs
  with the startup/lifespan work, which does not exist yet.
- CONTEXT open questions 17 (narrowed) and 23 (library lock for shared drives).
- Conservative cleanup must include AVAILABLE managed artifacts that nothing references (review M2).
- Consider a bounded retry of the rename/unlink on a sharing violation (review L4) once measured.
