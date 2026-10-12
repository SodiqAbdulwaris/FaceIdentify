# 03 Authoritative and derived data

## 1. What this is and why it exists

The most important design idea in the project is one question you ask of every piece of data:
**"If this were lost or damaged, could the program rebuild it?"** The answer sorts everything into
three groups (`docs/research/tech-stack.md`, section 19):

| Group | Meaning | Examples |
|---|---|---|
| **Authoritative** | The truth. Cannot be recomputed. Losing it is a real loss. | the SQLite database; your original photographs (when the library keeps copies); the model files; your corrections; deletion and forget state |
| **Derived** | Can be rebuilt from the authoritative data. | the **USearch vector index**, thumbnails, crops, caches |
| **Operational** | Temporary working state. | lock files, per-job work folders, logs |

So if the search index file is deleted or corrupted, **nothing is lost**: the program rebuilds it from
the database at the next start. If the *database* is lost, that is a real loss, so the database gets
the careful treatment: transactions, a write-ahead log, constraints, migrations. When you read
persistence code, ask of every piece "is this the truth, or can it be rebuilt?" The answer tells you
how careful the code must be.

## 2. Where it lives

There are **two folders** (`docs/research/tech-stack.md` section 15):

- The **library root** (you choose it; it can be on any drive; it is what you back up and move):
  `database/library.db`, `originals/`, `crops/`, `thumbnails/`, `models/`, `derived/`, `backups/`,
  `recovery/`, `staging/`.
- The **machine-local state root** (`%LOCALAPPDATA%\FaceIdentify` by default): things that belong to
  this computer and can be rebuilt: `indexes/` (the USearch files), `cache/`, `temp/` (per-job work
  folders), `logs/`, `runtime/` (installed model packages) and `installation/`.

In code: `backend/infrastructure/storage/layout.py` (`StorageRoots`) defines every path, and
`backend/infrastructure/storage/library_root.py` resolves which folder is the library.

## 3. How it works

- The **vector** of each face is stored *in SQLite* (`representations.vector`). The **index** only
  accelerates searching it. That is why the index is derived.
- Every change to the index is first written to the database as an **`IndexOperation`** row (`ADD` or
  `REMOVE`) in the same transaction as the change it describes; a coordinator applies it afterwards.
  If the program dies in between, startup replays what is pending. (The *outbox pattern*, explained in
  [the vector index](../02-data-and-storage/06-vector-index-and-outbox.md).)
- At every start, **startup recovery** validates each space's index and rebuilds a missing, corrupt or
  stale one from SQLite (`backend/app/recovery/startup.py`).

## 4. Try it

**Works with no models. Verified 2026-10-12.** This experiment proves the index is derived.

1. Follow [lesson 07](07-run-it-and-see-it-work.md) steps 1 to 6 so that your scratch library
   (`~/faceidentify-play`) holds at least one processed image. Then **stop the backend**.
2. Look at the derived folder:

   ```bash
   ls ~/faceidentify-play/state/indexes/*/
   ```

   Expected: one folder named by the representation space's id, holding `manifest.json` and one
   `index.<generation>.usearch` file. The manifest records the format version, dimension (`64` for the
   development profile), metric `cos`, a SHA-256 of the file and the vector `count`.
3. **Delete the whole derived folder** while the backend is stopped:

   ```bash
   rm -rf ~/faceidentify-play/state/indexes
   ```

   PowerShell: `Remove-Item -Recurse -Force $HOME\faceidentify-play\state\indexes` (*unverified here*).
4. Start the backend again with the same two folders (lesson 02, step 2) and check
   `/readiness`. Expected: `"state":"READY"`, with `"index":"READY"` and `"recovery":"READY"`.
5. Look again: `ls ~/faceidentify-play/state/indexes/*/` shows a **freshly built** folder and manifest.
6. Prove search still works: run the face search from [lesson 07](07-run-it-and-see-it-work.md)
   step 8 with the same photograph. Expected: `IDENTITY_ANSWER` with reason `MATCHED`. (In the verified
   run it did.)

You deleted derived data and lost nothing.

## 5. Change it

The contrasting experiment is the one you must **not** do on anything you care about: the database
and `originals/` are authoritative. The safe version of the lesson is to read the rules that guard
them, then run the tests that prove an index can be rebuilt:

```bash
uv run pytest tests/integration/test_representation_index.py tests/integration/test_index_coordinator.py -q
```

Expected: all pass. They include "quarantine and rebuild a missing, corrupt, mismatched or unsupported
index". If you break `open_or_rebuild` in `backend/infrastructure/indexing/representation_index.py`
so that it no longer rebuilds, those tests fail.

## 6. Break it on purpose

Stop the backend, and corrupt (do not delete) the index file:

```bash
echo garbage > ~/faceidentify-play/state/indexes/*/index.*.usearch
```

Start the backend. Expected: it still reaches `READY`: the manifest's SHA-256 no longer matches, so
the damaged generation is **quarantined** (moved aside, never trusted) and a new index is built from
the database. (Verified by test: `tests/integration/test_representation_index.py` covers a corrupt
file; the by-hand run above was not repeated for the corrupt case.)

## 7. Exercises

1. Classify each as authoritative, derived or operational: `library.db`; `index.<id>.usearch`;
   a per-job work folder in `temp/jobs/`; an imported original in `originals/`; a thumbnail.
2. Why does the vector live in SQLite and not only in the index?
3. What would you lose if you deleted `state/runtime/` (installed model packages)? Is it
   rebuildable?
4. Which of the two roots would you back up?

**Answers**

1. Authoritative; derived; operational; authoritative (for a `MANAGED` copy; a `REFERENCED` original
   stays where you left it); derived.
2. The index can be lost or damaged; if the vectors lived only there, the memory would be lost with it.
3. Nothing about your people; the packages are machine-local copies you install again (and a library
   whose vectors need a package that is missing opens `DEGRADED` and says so rather than comparing with
   another model). Rebuildable by installing again.
4. The library root.

## 8. Related files

- Previous: [02 The four programs](02-the-four-programs.md) · Next: [04 Layers and the repository map](04-layers-and-repository-map.md)
- [Storage roots and artifacts](../02-data-and-storage/08-storage-roots-and-artifacts.md)
- [The vector index and the outbox](../02-data-and-storage/06-vector-index-and-outbox.md)
- [Recovery](../03-backend/architecture/06-recovery.md)
- [`docs/research/tech-stack.md`](../../research/tech-stack.md) sections 15 and 19
