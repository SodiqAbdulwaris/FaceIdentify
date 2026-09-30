# M2: the IndexCoordinator (IndexOperation replay)

- **Date:** 2026-09-30
- **Milestone / tracker IDs:** M2 (TST-028)
- **Status:** done for replay into the per-space index; the use cases that *create* operations and
  the startup wiring are later work
- **Commits:** PR #23: `feat(memory): replay IndexOperations into the USearch index`,
  `test(memory): add index coordinator tests`, `docs: record the index coordinator`,
  `fix(memory): guarantee an erased vector leaves the index and tighten eligibility`,
  `docs: record the index coordinator review`

## What changed

- `backend/app/memory/index_coordinator.py`:
  - `IndexCoordinator(session_factory, index_root, *, clock, new_id, retry)` and
    `apply_pending(limit=...)`, which claims due `PENDING` operations in `(not_before_at,
    created_at, id)` order, groups them by space, and for each space: opens the index
    (`open_or_rebuild`, so an unusable index is quarantined and rebuilt from SQLite first), applies
    each operation, **persists one new generation if anything changed, and only then marks the
    operations `APPLIED`**.
  - Each operation **re-reads its representation** and applies a desired state (§17). `ADD`: present
    under its `ann_key` if the representation is still `ACTIVE` *and its identity is `ACTIVE`*;
    otherwise left alone (the `REMOVE` queued when it lost eligibility handles it). `REMOVE`: absent,
    even if the representation is still active. For an **erased** representation, which has no
    `ann_key` left, the space's index is **rebuilt from SQLite and the superseded generation's file
    must be gone** (not quarantined, which would keep the vector), else the pass fails and retries.
    Both are idempotent: replaying one changes nothing, and no new generation is
    written for a replay that changed nothing.
  - `RetryPolicy(max_attempts, backoff)`, **required and with no defaults**. A failed operation
    records its attempt, failure code and detail and is retried after `backoff(attempts)`; out of
    attempts it becomes `FAILED`. One failing operation does not stop the others in its batch; a
    failure to persist retries the whole space's batch and leaves the old generation live.
  - `CoordinatorReport`: `applied`, `retrying`, `failed`, `rebuilt_spaces`, and `unindexable`
    (ACTIVE representations a rebuild had to leave out because their stored vector is not a valid
    vector for the space: wrong length, NaN or infinity), and `purged_spaces`.
  - `apply_pending` holds a lock, so two threads cannot load, change and persist one index.
  - Settlement reads the attempt counts in its own transaction first, so no read precedes the
    writes in the transaction that commits them (no `BUSY_SNAPSHOT` from this step).
  - `USEARCH_METRICS` maps the space's `COSINE` to USearch's `cos`.
- Tests: `tests/integration/test_index_coordinator.py` (27), on real SQLite and real USearch files.
- `backend/infrastructure/indexing/representation_index.py`: `stale_files()` (what `remove_leftovers()`
  deletes), so the coordinator can verify that no superseded generation file remains.

## Why

TST-028 ("Index synchronization is idempotent"). PERSISTENCE_IMPLEMENTATION.md §17: "The coordinator
re-reads authoritative representation state before acting, making both operations idempotent and safe
to coalesce... It marks `APPLIED` only after the index mutation succeeds and its durable manifest is
settled." §23: "The coordinator receives the durable operation, rereads the representation, performs
desired-state add/remove idempotently, atomically persists the index/manifest generation, then marks
the operation applied." TESTING_STRATEGY INDEX-01: SQLite precedes index mutation.

## Decisions

- **The two crash windows are reproduced.** *Persisted but not settled* (the process dies after the
  index generation is written and before the operations are marked): the operations are still
  `PENDING`, the replay finds the index already right, persists nothing new (the generation id is
  unchanged) and marks them applied. *Failed to persist* (disk full): nothing is marked, the old
  generation is untouched, the operations back off, and the next pass succeeds.
- **Ordering.** Operations are applied oldest first. Because each re-reads the representation, a
  delayed `ADD` that runs after the `REMOVE` which followed it finds the representation ineligible and
  does nothing, so backoff cannot resurrect a removed entry.
- **An ineligible `ADD` does not remove.** §17 says `ADD` means "present *if* ACTIVE and eligible",
  and a loss of eligibility queues its own `REMOVE`; an `ADD` that also removed would be doing the
  `REMOVE`'s job from the wrong operation.
- **A rebuild skips a corrupt vector and reports it, instead of failing the space.** The first test of
  a bad vector showed one corrupt `ACTIVE` row making every operation in its space fail forever.
  The rebuild leaves the row out (`unindexable`), its own `ADD` fails visibly, and the rest of the space
  works. A recognition search will not find that representation until its data is repaired.
- **Retry limits are the caller's.** `max_attempts` and `backoff` have no default: they are unmeasured
  thresholds (rules/testing.md), and the scheduler/settings work that owns them does not exist yet.
  A `FAILED` operation is not picked up again; what retries a `FAILED` one (a user action, a repair
  pass) is undecided.
- **No new database code path, no new table.** It reads `representations` and `representation_spaces`
  and writes only `index_operations`, in short transactions around (never during) the index work.
- **Assertions instead of dead branches:** a missing space, representation or operation row cannot
  happen (the foreign keys are `RESTRICT`, operations are never deleted), and an `ACTIVE`
  representation always has a key and a vector (`active_eligible`, `erasure` constraints), so those
  are asserted, not handled. The schema allows only the `COSINE` metric, so an unsupported-metric
  path would be untestable; a metric added later without a mapping here fails that space's
  operations through the retry path.
- **One process, one thread** runs the coordinator (§23), and it is the sole writer of the index
  directory; this is stated in the module and inherited from the index.

## Open question found: erasure clears the key a `REMOVE` would need (CONTEXT 25)

Persistence's `erasure` constraint makes an `ERASED` representation have no vector and **no `ann_key`**,
so a `REMOVE` for it has nothing to remove by. The first version of this coordinator marked such an
operation applied and left the vector inside the index file, which the review rightly called a
violation of §17's "ensure absence regardless of stale index contents" for an erased biometric. The
coordinator now guarantees absence itself (rebuild, verify the old file is gone, else retry), with a
test that searches every file of the index directory for the erased vector's bytes. What stays open
is whether the *erase use case* should order things so the rebuild is unnecessary (queue the
`REMOVE`, clear the key and vector only after it is applied), which changes the erase/forget flow and
is decided with TST-031 (CONTEXT 25). Older *quarantined* generations from earlier corruption may
still hold a vector; quarantine retention is part of the same decision.

## Verification

- `uv run ruff format --check .`, `uv run ruff check .`, `uv run mypy` and `uv run mypy --platform
  linux`: clean.
- `HYPOTHESIS_PROFILE=ci uv run pytest --cov -q`: 620 passed (26 new, 0 regressions in the 594
  before); `backend/` coverage 100%. The new file was run 5 times in a row before review and 5 after
  the fixes: 0 failures.
- Mutation checks, each reverted and confirmed byte-identical: 25 on the claim query (state, due
  time, ordering, limit), the different-space check, `REMOVE` and `ADD` eligibility, persisting only
  when changed (both directions), the changed-flag accumulation, the attempt limit, the backoff, the
  settle guard, the rebuilt-space report, the rebuild's `ACTIVE` filter and its skip-and-report, the
  per-operation and whole-batch failure handling, and the `applied_at` stamp. One survived at first
  (the redundant null checks for an `ACTIVE` representation, now assertions justified by the schema).
  All caught or removed.
- Writing the tests found two real bugs in the first version: a retrying operation raised `KeyError`
  when the report read a `state` value that only `FAILED` updates carry, and a corrupt vector blocked a
  whole space (above).
- **Not verified:** very large batches or spaces (the rebuild streams with `yield_per=1000`, unmeasured),
  concurrent use (the design forbids it), and behaviour with `SQLITE_BUSY` (CONTEXT open question 20):
  the settle step reads then writes in one transaction, so a second writer committing in between
  could raise the known `BUSY_SNAPSHOT`.

After the review, 12 more mutations on the new behaviour (the purge trigger, the stale-file check,
the re-application of the batch after a purge, persisting after it, the purge report, finiteness, each
side of the identity rule, and the lock): 11 caught; one survivor, `join` against `outerjoin` under an
`Identity.state == ACTIVE` filter, is equivalent (the filter removes the rows an outer join would
keep). A guard the review did not ask for, on the attempt count in the settle `UPDATE`, was removed
because nothing in a single-coordinator design can exercise it and the `PENDING` guard already stops
a double settle.

## Independent review (Codex CLI, read-only, disposable worktree): request-changes, addressed

| # | Finding | Resolution |
|---|---|---|
| C1 (critical) | An erased representation's `REMOVE` is marked applied without removing anything, leaving its vector in the index file | Fixed in the coordinator: a keyless `REMOVE` rebuilds the space from SQLite (no quarantine), re-applies the batch, and requires the superseded generation's file to be gone or the pass fails and retries. Test: the erased vector's bytes are found in the index file before and in no file of the directory after; a second proves a locked old file keeps the operation `PENDING`. Whether erasure should also be ordered to avoid the rebuild remains CONTEXT 25 |
| H1 | `_claim` does not lock; concurrent passes can lose an update | Fixed in-process: `apply_pending` holds a lock across claim, apply, persist and settle (tested). **Not** an inter-process lock: the coordinator is a single process by design and the index is machine-local state under the shell's single instance; a second process is the library-lock question (CONTEXT 23) |
| H2 | Settlement reads then writes in a deferred transaction and can raise `BUSY_SNAPSHOT` | Fixed for this step: the attempt counts are read in their own transaction, so the writes' transaction starts with a write. A retrying wrapper for `SQLITE_BUSY` generally is open question 20 and is not built here. A real two-session `BUSY_SNAPSHOT` test was not written: with no read in the write transaction there is nothing for it to fail on, and the ordering is visible in the code |
| M1 | A rebuild skips only a wrong-length vector; a NaN blocks the whole space | Fixed: finiteness is checked with the length; such rows are reported as `unindexable`. Test with NaN and infinity |
| M2 | Eligibility is only `state == ACTIVE`; §6.2 needs an active identity | Fixed in `ADD` and in the rebuild; `REMOVE` stays unconditional. Tests for a non-active identity and for a `REMOVE` regardless of identity |
| L | The test commit changes 465 lines with no body rationale | Not split and history not rewritten: it is one new test module (plus nothing else); explained on the PR |

The reviewer found the normal replay, the persist-before-applied ordering and the persist-to-settle
crash window correct, noted that coalescing opposite operations belongs to the producing use cases,
and did not run the tests.

## Open issues / follow-ups

- The use cases that create `IndexOperation`s atomically with eligibility changes (accept run, merge,
  split, forget) and the startup/lifespan wiring that runs the coordinator are not built.
- Coalescing opposite pending operations "in the use case" (§17) belongs to those use cases.
- Open question 25 (above); decide with TST-031.
