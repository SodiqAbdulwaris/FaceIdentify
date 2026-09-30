# M2: the per-space USearch index

- **Date:** 2026-09-30
- **Milestone / tracker IDs:** M2 (TST-027)
- **Status:** done for the index component; the coordinator that replays `IndexOperation`s into it
  is TST-028
- **Commits:** PR (number added when opened): `feat(indexing): add the per-space USearch index`,
  `test(indexing): add representation index tests`, `docs: record the representation index`

## What changed

- `backend/infrastructure/indexing/representation_index.py`:
  - `RepresentationIndex`: one USearch index (`f32`) for one RepresentationSpace. `add(key, vector)`
    and `remove(key)` are idempotent desired-state operations (they return whether anything
    changed); `contains`, `len`, and `search(vector, k)` returning `Candidate(key, distance)` values,
    nearest first. Keys are unsigned 64-bit integers; vectors must have exactly the space's
    dimension and be finite.
  - **Persistence as generations.** `persist()` writes `index.<generation id>.usearch`, then
    atomically replaces `manifest.json` (write, fsync, rename) to name it. The manifest is the
    commit point, so a crash leaves the old generation or the new one, never a half-written index
    that looks valid. Index files no manifest names are leftovers and are removed on open.
  - `IndexManifest`: `index_format_version`, `representation_space_id`, `generation_id`, `built_at`
    (persistence §23) plus `ndim`, `metric`, `index_file`, `size_bytes` and `count`.
  - `RepresentationIndex.open(...)` loads the live generation or raises `IndexUnusableError`, saying
    why: no or unreadable manifest, unsupported format version, another space's index, another
    dimension or metric, a manifest naming an unexpected file, a missing, resized or unloadable index
    file, or a different entry count than the manifest recorded.
  - `quarantine(directory)` moves an unusable index's own files to `quarantine/<n>/` (never
    overwriting an earlier one) and touches nothing else.
  - `open_or_rebuild(...)` is the startup path: use the index if it is sound, otherwise quarantine
    it and rebuild from `entries()` (streamed from SQLite by the caller, and only called when a
    rebuild is needed). An absent index is a first build, not a failure.
- Tests: `tests/integration/test_representation_index.py` (58), on real USearch and real files.

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
  boolean; `Index.load` silently adopts the file's own dimension (so the dimension is checked after
  loading, and a test substitutes a 4-dimensional file); a garbage file raises `ValueError` or
  `RuntimeError`; a search on an empty index returns nothing, so no special case is needed.
- **The manifest has more than the four fields §23 lists.** `ndim`, `metric`, `index_file`,
  `size_bytes` and `count` are what make "corrupt" and "mismatched" detectable. §23 says the
  manifest *contains* the four; adding fields does not contradict it, and none is a spec edit.
- **A file the manifest names must match the exact generation-file pattern**, so a corrupt manifest
  cannot point the loader outside the index directory (tests try `../escape`, a drive path and an
  empty name).
- **Only this module's own files are ever deleted or moved**, matched by exact name patterns; a
  foreign file in the directory is left alone (tested).
- **A vector's value is never rewritten.** A present key is left as it is, because a representation's
  vector is immutable; a changed vector is a new representation with a new key.
- **Known ceilings** (`ponytail:` in the module): quarantined indexes are kept and never pruned; the
  manifest records size and count, not a hash, so a same-size corruption that still loads is not
  detected. Both have a stated upgrade.
- **Not here:** the metric mapping from `RepresentationSpace.metric` (`COSINE`) to USearch's `cos`
  (the coordinator supplies the name), any thread coordination (the coordinator is the only writer,
  §23), and the run-local pending index.

## Verification

- `uv run ruff format --check .`, `uv run ruff check .`, `uv run mypy` and `uv run mypy --platform
  linux`: clean.
- `HYPOTHESIS_PROFILE=ci uv run pytest --cov -q`: 573 passed (58 new, 0
  regressions in the 515 before); `backend/` coverage 100%. The new file was run 5 times in a row: 58
  passed each time.
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
- **Not verified:** a very large index (memory and save time), concurrent searching while the
  coordinator writes, and a power cut mid-`fsync` (the crash tests interrupt the rename, not the
  disk).

## Open issues / follow-ups

- TST-028 (replay `IndexOperation`s into this index idempotently) builds on it.
- Where the index directory comes from (`%LOCALAPPDATA%/<App>/indexes/<space id>/`) is the layout's
  `local_state_root / "indexes"`; wiring it into startup belongs with the lifespan work.
