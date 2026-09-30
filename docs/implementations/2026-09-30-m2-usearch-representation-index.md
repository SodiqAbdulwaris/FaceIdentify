# M2: the per-space USearch index

- **Date:** 2026-09-30
- **Milestone / tracker IDs:** M2 (TST-027)
- **Status:** done for the index component; the coordinator that replays `IndexOperation`s into it
  is TST-028
- **Commits:** PR #22: `feat(indexing): add the per-space USearch index`,
  `test(indexing): add representation index tests`, `docs: record the representation index`,
  `fix(indexing): verify the index file, not just its name and size`,
  `docs: record the representation index review`

## What changed

- `backend/infrastructure/indexing/representation_index.py`:
  - `RepresentationIndex`: one USearch index (`f32`) for one RepresentationSpace. `add(key, vector)`
    and `remove(key)` are idempotent desired-state operations (they return whether anything
    changed); `contains`, `len`, and `search(vector, k)` returning `Candidate(key, distance)` values,
    nearest first. Keys are unsigned 64-bit integers; vectors must have exactly the space's
    dimension and be finite.
  - **Persistence as generations.** `persist()` writes `index.<generation id>.usearch`, flushes it
    to disk, hashes it, then atomically replaces `manifest.json` (write, fsync, rename) to name it.
    The manifest is the commit point, so a *process* crash leaves the old generation or the new
    one, never a half-written index that looks valid. After a power cut the new generation may be
    lost or the old one stale (Windows cannot flush a directory); that is acceptable because the
    index is rebuildable and whatever is found is verified against the manifest.
  - `IndexManifest`: `index_format_version`, `representation_space_id`, `generation_id`, `built_at`
    (persistence §23) plus `ndim`, `metric`, `index_file`, `size_bytes`, `sha256` and `count`.
  - `RepresentationIndex.open(...)` is **read-only**. It loads the live generation or raises
    `IndexUnusableError`, saying why: a link where the directory, manifest or index file should be,
    no or unreadable manifest, unsupported format version, another space's index, another
    dimension or metric, a manifest naming any file but its own generation's, a missing or resized
    index file, a SHA-256 that differs from the manifest's, a file USearch cannot load, a file
    *header* with another dimension or metric, or a different entry count than recorded.
  - `remove_leftovers()` (the writer's, run by `persist()` and `open_or_rebuild`) deletes index
    files and staged manifests the live manifest does not name: only this module's own plain files,
    by exact name, and a locked one is skipped and retried.
  - `quarantine(directory)` moves an unusable index's own plain files to `quarantine/<n>/` (never
    overwriting an earlier one, never through a link) and touches nothing else. It is best effort:
    a locked file stays where it is rather than stopping the rebuild.
  - `open_or_rebuild(...)` is the startup path: use the index if it is sound, otherwise quarantine
    it and rebuild from `entries()` (streamed from SQLite by the caller, and only called when a
    rebuild is needed). An absent index is a first build, not a failure.
- `backend/infrastructure/storage/plain.py`: `is_plain_directory` and `is_plain_file` ("a real entry,
  not a link, junction, mount point or other reparse point", by `lstat`), moved out of the workspace
  manager so the index, workspaces and storage usage share one definition.
- Tests: `tests/integration/test_representation_index.py` (76), on real USearch and real files, and
  `tests/integration/test_plain_paths.py` (3).

## Why

TST-027 ("Index operations work with real USearch"). PERSISTENCE_IMPLEMENTATION.md §23: one USearch
index per space, never mixed; a manifest with the four fields; "atomically persists the index/manifest
generation"; "a missing, corrupt, mismatched, or unsupported index is quarantined/discarded and
rebuilt by streaming active eligible representations from SQLite". ANN output is only candidate
keys; SQLite revalidates them, and nothing here decides identity.

## Decisions

- **This module takes keys and vectors; it does not allocate keys or read SQLite.** That keeps it
  independent of the open questions about `ann_key` (CONTEXT 13 and 21): whichever way those are
  decided, this index is unchanged. The coordinator (TST-028) decides what belongs in it.
- **Facts about USearch 2.26.2, found by probing, that shaped the design:** adding an existing key
  raises (so `add` checks `contains` first, making a replayed operation a no-op); `remove` returns a
  boolean; a search on an empty index returns nothing, so no special case is needed; a garbage file
  raises `ValueError` from `Index.metadata` and `load`. **`Index.load` silently adopts the file's
  own dimension, and keeps *computing* the file's own metric while `index.metric` goes on reporting
  the one the object was built with** (an L2 file loaded into a cosine index answered with L2
  distances and said `Cos`). So neither property of a loaded index can be trusted; the file's
  header (`Index.metadata`) is read and checked before the load, and tests substitute a
  4-dimensional file and a same-dimension L2 file.
- **The manifest has more than the four fields §23 lists.** `ndim`, `metric`, `index_file`,
  `size_bytes` and `count` are what make "corrupt" and "mismatched" detectable. §23 says the
  manifest *contains* the four; adding fields does not contradict it, and none is a spec edit.
- **A file the manifest names must be exactly its own generation's file**
  (`index.<generation id>.usearch`), so a corrupt manifest cannot point the loader outside the index
  directory or at another generation's file (tests try `../escape`, a drive path, an empty name and
  a well-formed name of another generation).
- **Only this module's own files are ever deleted or moved**, matched by exact name patterns; a
  foreign file in the directory is left alone (tested).
- **A vector's value is never rewritten.** A present key is left as it is, because a representation's
  vector is immutable; a changed vector is a new representation with a new key.
- **Single process, single writer.** `open`, `persist`, `quarantine` and `remove_leftovers` must not
  run concurrently for one space (the coordinator is the only writer, §23; the index lives in
  machine-local state, where the desktop shell's single instance applies). `open` is read-only
  precisely so a reader can never delete a generation a writer just published; cleanup belongs to
  the writer's own paths.
- **Known ceiling** (`ponytail:` in the module): quarantined indexes are kept and never pruned.
- **Not here:** the metric mapping from `RepresentationSpace.metric` (`COSINE`) to USearch's `cos`
  (the coordinator supplies the name), any thread coordination (the coordinator is the only writer,
  §23), and the run-local pending index.

## Verification

- `uv run ruff format --check .`, `uv run ruff check .`, `uv run mypy` and `uv run mypy --platform
  linux`: clean.
- `HYPOTHESIS_PROFILE=ci uv run pytest --cov -q`: 594 passed (79 new, 0
  regressions in the 515 before); `backend/` coverage 100%. The new files were run 5 times in a row
  before review and 5 after the fixes: 0 failures.
- Mutation checks, each reverted and confirmed byte-identical: 27 on every guard (idempotent add and
  remove, the key and vector checks, each manifest comparison, the file pattern, the size and count
  checks, the atomic manifest replace, leftover removal and its exact patterns, quarantine
  numbering and selection, and the rebuild path). Five survived at first: the tests had missed a
  right-sized-but-wrongly-shaped vector, a metric-only mismatch (a later check gave a similar
  message), and a redundant early return for an empty index, which was deleted since USearch already
  returns nothing. All are now caught or removed.
- A test found a real bug while writing: a non-string `generation_id` made `uuid.UUID` raise
  `AttributeError`, which the manifest parser did not turn into "unusable". Every manifest field is
  now type-checked first.
- **Not verified:** a very large index (memory, save and hash time), concurrent searching while
  the coordinator writes (the design forbids concurrent writers; a search running in the same
  process while it persists is not exercised), and real power-loss durability (the tests interrupt
  the rename and check the order of the flushes, not the disk).

After the review, 24 more mutations on the new guards (the hash, the generation-name binding, the
header's metric and dimension, each link check, both flushes, the writer's cleanup and its exact
patterns, the tolerant quarantine, and the first-build reason): 21 caught at once. Three survived:
the plain-file test in leftover removal (a file symlink cannot be created without privileges, so
the guard is defence in depth that no test can observe), quarantining through a linked directory
(a real gap; a test now does it), and a redundant second clause in the first-build test, which was
simplified.

## Independent review (Codex CLI, read-only, disposable worktree): request-changes, addressed

| # | Finding | Resolution |
|---|---|---|
| H1 | A concurrent `open()` can delete a newly published generation, because it cleans up by the manifest it read | Fixed: `open()` is read-only; cleanup is the writer's (`persist`, `open_or_rebuild`). The single-process, single-writer precondition is stated. A test has stale, foreign and look-alike files and proves opening removes none of them. An interprocess lock was not added: the index is machine-local state under the desktop shell's single instance |
| H2 | The commit point is not durable (the generation is not flushed, no directory flush) | Partly fixed, and the claim narrowed. The generation is now flushed before the manifest names it (a test checks both flushes precede the rename). A directory flush is not possible on Windows, so the documented guarantee is crash-safety against a *process* crash; after a power cut the index may be lost or stale, which is detected against the manifest and rebuilt, never authoritative |
| H3 | A loaded index's metric is never verified | Fixed, and worse than the reviewer knew: `Index.load` keeps computing the file's metric while `index.metric` reports the constructor's, so even a check of `index.metric` would pass. The file header is checked before loading; a test substitutes a same-dimension L2 file |
| H4 | A stale or corrupted generation with matching size and count is accepted | Fixed: the manifest must name its own generation's file and records a SHA-256, checked before the load. A test swaps in a valid index of the same size and count with different vectors |
| M1 | Index and quarantine paths follow reparse points | Fixed: the directory, manifest, index file and quarantine folder must be plain (`lstat`, shared `is_plain_*` helpers); tests use junctions for the directory, the quarantine folder and a directory where the file should be. A file symlink cannot be created here without privileges, so the file case is covered only through the same check |
| M2 | Quarantine is not safe under locks | Fixed: a locked file stays put and does not stop the rebuild; tests hold the old index file, and then both files, open |
| L | The claims overstate coverage | Narrowed (above): "process crash", the read-only `open`, single writer; the not-verified list is explicit |
| L | PR number missing | Fixed |

The reviewer found ID handling, idempotent add and remove, candidate-only search and the filename
checks sound, and did not run the tests.

## Open issues / follow-ups

- TST-028 (replay `IndexOperation`s into this index idempotently) builds on it.
- Where the index directory comes from (`%LOCALAPPDATA%/<App>/indexes/<space id>/`) is the layout's
  `local_state_root / "indexes"`; wiring it into startup belongs with the lifespan work.
