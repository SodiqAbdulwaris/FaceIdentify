# Data 06 The vector index and the outbox pattern

## 1. What this is and why it exists

The face vectors themselves are stored **in SQLite** (`representations.vector`, as bytes). The **USearch** index
is a separate, derived structure that makes "find the faces most like this one" fast
([nearest-neighbour search](../01-basics/recognition-ideas/06-nearest-neighbour-and-video-vocabulary.md)). Two
problems follow. First, the database and the index are two things, and a crash can happen between updating one
and the other. Second, the index must never decide anything: it can be stale or wrong. The project's answer to
the first is the **outbox pattern**: write the *intent* in the database in the same transaction as the change it
describes, and perform the side effect afterwards. The answer to the second is that SQLite revalidates every
index answer.

## 2. Where it lives

| Thing | Where |
|---|---|
| The per-space index, manifest, generations, quarantine, rebuild | `backend/infrastructure/indexing/representation_index.py` |
| The intent rows | `IndexOperation` in `backend/app/memory/models.py` (`ADD` / `REMOVE`; `PENDING` / `APPLIED` / `FAILED`) |
| Writing intents | `IndexOperationRepository` in `backend/app/memory/index_operation_repository.py` |
| Applying them | `IndexCoordinator` in `backend/app/memory/index_coordinator.py` |
| Key allocation | the `ann_key_sequences` table; `ann_key` is unique **within a representation space** (revision `0003`) |
| Recovery | `backend/app/recovery/startup.py` replays pending operations and validates each index |
| Tests | `tests/integration/test_index_coordinator.py`, `test_index_operation_repository.py`, `test_representation_index.py`, `tests/recovery/test_cross_storage_failures.py` |

## 3. How it works

1. When a representation becomes searchable (acceptance activates it), the use case sets its `ann_key` and, **in the
   same transaction**, appends an `ADD` `IndexOperation` for it. Nothing touches USearch yet ("no code is allowed
   to mutate USearch first and hope that SQLite catches up").
2. After the commit, the **IndexCoordinator** wakes. For each pending operation it **re-reads the representation**
   (the operation only says what was wanted; the row says what is true) and applies the operation as a *desired
   state*: `ADD` means "ensure the vector is present under its key", `REMOVE` means "ensure the key is absent". So
   replaying one is harmless.
3. It saves one new **index generation** first and only then marks the operations `APPLIED`. A crash between the
   two leaves them `PENDING`; replay finds the index already right and only marks them applied.
4. A failed operation is retried with a caller-supplied backoff until a caller-supplied limit, then marked `FAILED`;
   startup recovery gives `FAILED` ones one fresh set of attempts. Neither number has a default.
5. If a pending operation of the opposite kind exists for the same representation, appending a new one **deletes the
   obsolete pending one** (an `ADD`, `REMOVE`, `ADD` sequence must not end with the vector missing). An `APPLIED` or
   otherwise historical operation is never rewritten.
6. **The index on disk**: one folder per representation space in machine-local state,
   `indexes/<space id>/manifest.json` plus `index.<generation>.usearch`. The manifest is the commit point: the file
   is written, flushed and hashed first, and invisible until `manifest.json` is atomically replaced. On open the
   manifest's size, hash, count, dimension and metric are checked; a missing, corrupt, mismatched or unsupported
   index is **quarantined** (moved aside, never trusted) and **rebuilt from SQLite**.
7. **Eligibility**: an `ACTIVE` representation with an `ACTIVE` identity, or with no identity at all (an accepted
   abstention), is indexed; an erased or forgotten one is not.
8. **One process, one writer.** The coordinator is the only writer of the index directory (the library lock
   guarantees one backend per library).

## 4. Try it

**Works with no models. Verified 2026-10-12.** On the library from start-here lesson 07 (reading it read-only):

```python
import sqlite3, json, glob, pathlib
home = pathlib.Path.home() / "faceidentify-play"
con = sqlite3.connect(f"file:{home}/lib/database/library.db?mode=ro", uri=True)
print("next key:", [tuple(r) for r in con.execute("select next_ann_key from ann_key_sequences")])
print("keys:", [tuple(r) for r in con.execute("select ann_key, state from representations order by ann_key")])
print("outbox:", [tuple(r) for r in con.execute("select operation, state, attempt_count from index_operations")])
for m in glob.glob(str(home / "state/indexes/*/manifest.json")):
    print("index count:", json.load(open(m))["count"])
```

Expected for the verified run (6 faces processed): `next key: [(7,)]`, `keys: [(1, 'ACTIVE'), ... (6, 'ACTIVE')]`,
`outbox:` six rows `('ADD', 'APPLIED', 1)` and `index count: 6`. Every face has a key; every key had an `ADD`
that was `APPLIED` on its first attempt; the index holds the same six vectors. Your numbers follow how many faces
you processed. Then:

1. Run the coordinator's tests (the three that need Windows file locks are skipped here):

   ```bash
   uv run pytest tests/integration/test_index_coordinator.py -q \
     --deselect tests/integration/test_index_coordinator.py::test_a_purge_that_cannot_delete_the_old_file_fails_instead_of_reporting_it_gone \
     --deselect tests/integration/test_index_coordinator.py::test_a_remove_is_not_applied_while_a_superseded_generation_remains \
     --deselect tests/integration/test_index_coordinator.py::test_a_remove_for_a_key_already_absent_still_waits_for_the_old_generation_to_go
   ```

   Expected on Linux: `37 passed, 3 deselected`. (On Windows run the whole file.) Read the test names: they are the
   guarantees listed above.
2. Re-run [start-here lesson 03's experiment](../00-start-here/03-authoritative-and-derived.md): stop the backend,
   delete `state/indexes`, start it again. The folder comes back and `count` matches the number of active faces.
3. The crash story is tested with real processes: `tests/recovery/test_cross_storage_failures.py` and
   `tests/recovery/test_process_kill.py` kill the program between steps and show recovery finishing the work.

## 5. Change it

You do not change the order *database intent, then index*; it is the invariant (INDEX-01). The safe changes are to the
policy knobs, which are the host's, not the module's: `PROVISIONAL_INDEX_RETRY` (3 attempts, backoff in minutes),
`PROVISIONAL_INDEX_BATCH = 100` and `PROVISIONAL_INDEX_PASSES = 10` in `backend/api/host.py`. They are named
"provisional" because no measurement has chosen them. If you change one in a scratch edit, the tests do not care
(they pass their own policy); the host's behaviour under a flaky index changes. Revert it. For a new behaviour of
the coordinator, add the test first in `tests/integration/test_index_coordinator.py`.

## 6. Break it on purpose

Stop the backend, **corrupt the index file** (do not delete it) and start again:

```bash
echo garbage > ~/faceidentify-play/state/indexes/*/index.*.usearch
```

Expected (observed 2026-10-12): the backend reaches `READY`, and `state/indexes/<space>/` now holds a **new**
`index.<other generation>.usearch`, a new `manifest.json` and a `quarantine/1/` folder containing the damaged file
and the old manifest, kept for diagnosis. The manifest's hash no longer matched, so the old generation was never
trusted, and a fresh one was built from SQLite. Quarantined indexes are kept and never pruned (they are rare and
small). The same behaviour is proved by `test_representation_index.py`.

## 7. Exercises

1. What is an `IndexOperation` and which transaction writes it?
2. Why does the coordinator re-read the representation instead of trusting the operation?
3. Why is the generation saved before the operations are marked `APPLIED`?
4. What happens to a corrupt index at startup?
5. Why are `next key` and the `keys` list in the Try-it equal to 7 and 1 to 6, not 0 to 5?

**Answers**

1. A durable note "add or remove this representation's vector"; the same transaction that changes the
   representation (for example acceptance).
2. The operation only says what was wanted; the row says what is true now (it may have been erased since).
3. A crash in between then leaves the operations `PENDING` and replay is harmless, whereas the reverse order could
   claim something was indexed that was not.
4. It is quarantined and the index is rebuilt from SQLite.
5. Keys start at 1 and `next_ann_key` is the next one to hand out; keys are never reused within a space.

## 8. Related files

- Previous: [05 SQLAlchemy and repositories](05-sqlalchemy-and-repositories.md) · Next: [07 Erasure](07-erasure.md)
- [`backend/app/memory/index_coordinator.py`](../../../backend/app/memory/index_coordinator.py)
- [`docs/specs/PERSISTENCE_IMPLEMENTATION.md`](../../specs/PERSISTENCE_IMPLEMENTATION.md) sections 17 and 23
- [Recovery](../03-backend/architecture/06-recovery.md)
- Further reading: Kleppmann, *Designing Data-Intensive Applications* (the outbox pattern)
