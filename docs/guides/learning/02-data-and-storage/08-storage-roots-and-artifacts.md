# Data 08 Storage roots, artifacts and the library lock

## 1. What this is and why it exists

Besides the database, the application keeps **files**: your originals, crops, thumbnails and model files. Two
questions arise: *where do they live* (two folders, called roots, with different jobs) and *how does the database
know about them* (a row per file, called an **Artifact**, with a hash and a state). A third protects all of it: a
**lock** so two copies of the program can never open the same library at once. This lesson walks through all three.

## 2. Where it lives

| Thing | Where |
|---|---|
| The layout and safe keys | `backend/infrastructure/storage/layout.py` (`StorageRoots`, `LIBRARY_DIRECTORIES`, `path_for`) |
| Crash-safe writes, hashing | `backend/infrastructure/storage/files.py` (`ManagedFileStore`) |
| Which folder is the library | `backend/infrastructure/storage/library_root.py` |
| The lock | `backend/infrastructure/storage/library_lock.py` (`LibraryLock`) |
| The artifact protocol | `backend/app/sources/artifact_storage.py`, `referenced_artifacts.py` |
| Referenced originals, relinking | `backend/infrastructure/storage/referenced.py` |
| Cleanup, usage | `backend/app/sources/storage_cleanup.py`, `storage_usage.py`; per-job work folders: `backend/infrastructure/storage/workspaces.py` |
| The decision | `docs/research/tech-stack.md` section 15 |

## 3. How it works

### The two roots

- **Library root** (you choose it; any drive; the thing you back up and move): `database/library.db`, `originals/`,
  `crops/`, `thumbnails/`, `models/`, `derived/`, `backups/`, `recovery/`, `staging/`. Managed writes stage in
  `staging/` *inside* the library root because the final rename must stay on one volume to be atomic.
- **Machine-local state root** (`%LOCALAPPDATA%\FaceIdentify`; `FACEIDENTIFY_LOCAL_STATE_ROOT` overrides it in
  development): rebuildable data tied to this computer: `indexes/`, `cache/`, `temp/` (per-job work folders), `logs/`,
  `runtime/` (installed model packages) and `installation/`.
- The two roots must not be the same folder or nested in each other (`validate_distinct_roots`). The backend receives
  **exactly one resolved library root at startup** and it never changes during the process; the desktop shell owns
  which folder is used. A root that is given but unusable is refused, never replaced by a lower-precedence one.

### Artifacts

An **Artifact** row describes a file: its kind (`SOURCE_ORIGINAL`, `FACE_CROP`, `THUMBNAIL`, `MODEL_EXPORT`,
`RUNTIME_PACKAGE`), its **storage mode**, its SHA-256 and size, and its **state**.

- **`MANAGED`**: a copy the application owns, at `originals/<artifact id as 32 hex characters>`. It is named by id,
  never by person or file name. Created by a three-step protocol: commit a `PENDING` row; write to a temporary
  file in `staging/`, hash it while streaming, `fsync`, then atomically rename; commit `AVAILABLE` with the key, hash
  and size. A crash at any step is recoverable and no half file is ever visible. Deletion is symmetrical: record
  the intent, remove the bytes, finalise the row.
- **`REFERENCED`**: an original left where you keep it (`external_path` is recorded). It is inspected and
  fingerprinted before the transaction; it is **never modified or deleted by the application**. If it disappears
  or changes, the artifact becomes `MISSING`; the Source is not touched. The use case `relink_referenced_artifact`
  would point a `MISSING` one at a file you choose, **only if its size and SHA-256 equal the recorded ones**, and
  `reverify_referenced_artifact` would bring one back when the file reappears. Both are built and tested **as use
  cases**; no route, screen or startup step calls them yet (observed below).
- **States**: `PENDING` → `AVAILABLE` → maybe `MISSING` (or `DELETED`, which may have no location since revision `0010`).
- **Safe keys**: a storage key is exactly `<managed directory>/<32 lowercase hex>`. `path_for` refuses anything
  else, which leaves no room for `..`, drive prefixes, Windows device names or alternate data streams, and resolves
  the path to confirm it still sits in the real managed directory (a junction or symlink cannot redirect it).
  The key is read back from the database, so it is validated every time, not trusted.
- **Cleanup is conservative**: only `AVAILABLE` managed artifacts that no row references, past a cutoff, are
  deleted; stray files are reported, never deleted.

### The library lock

`database/.lock` is held with an **operating-system lock** (`msvcrt.locking` on Windows, `flock` elsewhere) for as
long as the backend runs, taken right after the root is validated and before migrations or recovery. A second
backend (or another computer on a shared drive) fails to start for that library (`LibraryLockedError`), never
falling back to another. The OS frees the lock if the program crashes. It protects against a second *backend*, not
against someone editing the files, and a network share that ignores byte-range locks gives no protection.

## 4. Try it

**Works with no models. Verified 2026-10-12.**

1. Look at the two roots after the lesson-07 run:

   ```bash
   find ~/faceidentify-play/lib -type f | sed "s|$HOME/faceidentify-play/||" | sort
   find ~/faceidentify-play/state -type f | sed "s|$HOME/faceidentify-play/||" | sort
   ```

   Expected: under `lib/`, `database/.lock`, `database/library.db` (and `-wal`, `-shm` while running) and one
   file per imported picture in `lib/originals/` named by a 32-character hex id; under `state/`, the index
   (`state/indexes/<space>/manifest.json` and `index.<generation>.usearch`).
2. Import a picture **by reference** (backend running; `$B`, `$H` as in start-here 07):

   ```bash
   curl -s -X POST -H "$H" -H "Content-Type: application/json" \
     -d "{\"path\":\"$HOME/faceidentify-play/pics/green.png\",\"storage_mode\":\"REFERENCED\",\"display_name\":\"green by reference\"}" \
     $B/api/v1/sources/import
   ```

   Expected: a source with `"storage_mode":"REFERENCED"` and `"availability":"AVAILABLE"`; **no new file** in `lib/originals/`.
3. Read the artifacts table (read-only):

   ```python
   import sqlite3, pathlib
   con = sqlite3.connect(f"file:{pathlib.Path.home()}/faceidentify-play/lib/database/library.db?mode=ro", uri=True)
   for r in con.execute("select kind, storage_mode, state, storage_key, external_path is not null, hex(substr(sha256,1,4)), size_bytes "
                        "from artifacts where kind='SOURCE_ORIGINAL'"):
       print(tuple(r))
   ```

   Observed: managed rows like `('SOURCE_ORIGINAL', 'MANAGED', 'AVAILABLE', 'originals/135aa9fc...', 0, '06B205DA', 14989)`
   and one `('SOURCE_ORIGINAL', 'REFERENCED', 'AVAILABLE', None, 1, '42310C40', 15310)`: a referenced artifact has
   an external path and no storage key. The same picture imported twice has the same hash prefix (`06B205DA`) but
   two rows: identical files make two sources.
4. Safe keys, in `uv run python`:

   ```python
   >>> from pathlib import Path
   >>> from backend.infrastructure.storage.layout import StorageRoots, UnsafeStorageKeyError
   >>> roots = StorageRoots(Path.home() / "faceidentify-play/lib", Path.home() / "faceidentify-play/state")
   >>> roots.path_for("originals/" + "a" * 32).name
   'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
   >>> roots.path_for("originals/../database/library.db")
   UnsafeStorageKeyError: not a managed storage key: 'originals/../database/library.db'
   ```

   `../x`, `originals/ABC` (uppercase, wrong length) and a key with a trailing `.` are refused the same way.
5. The lock: with the backend running, start a second backend on the same folders; its `/readiness` says
   `{"state":"FAILED","failure":"LibraryLockedError"}` (start-here lesson 07, "Break it"). Tests:
   `uv run pytest tests/integration/test_library_lock.py tests/integration/test_library_root.py tests/integration/test_referenced_artifacts.py -q`
   (one test in `test_referenced_artifacts.py` depends on Windows behaviour and fails on Linux).

## 5. Change it

The two safe levers are documentation and a test. To understand referenced originals, read
`tests/integration/test_referenced_artifacts.py` and note the relink test: it shows a `MISSING` original that is
relinked only to a file with the same size and hash. If you needed a new managed folder (say, `exports/`), that is
a layout and spec change (tech-stack section 15, persistence section 1, an owner decision, `LIBRARY_DIRECTORIES`,
`KIND_DIRECTORIES`, safe-key regex, tests for each); it is not a quick edit and should be a plan.

## 6. Break it on purpose

Move a referenced original away and restart the backend (observed 2026-10-12, the "green by reference" import
above): `/readiness` stays `READY` and `GET /api/v1/sources` shows that source with `"availability":"MISSING"` while the
other sources stay `AVAILABLE`; nothing else is touched. Now put the file back and restart the backend again: **the
source is still `MISSING`**. Nothing re-verifies it yet, because `reverify_referenced_artifact` and
`relink_referenced_artifact` are not wired to a route or a startup scan (the code says "never a startup scan"). This is
a gap you now know about, not something you did wrong; it is recorded in the implementation entry for this guide as a
finding for the owner. The tests of the use cases are in `tests/integration/test_referenced_artifacts.py`.

## 7. Exercises

1. What are the two roots, and which one would you back up?
2. Why is a managed original named by an id and not by its file name?
3. What happens to a referenced original the application can no longer find?
4. Why does `path_for` re-validate a key it read from the database?
5. What does the library lock protect against, and what does it not?

**Answers**

1. The library root and the machine-local state root; the library root.
2. Names can collide, leak personal information, and have aliases on Windows; an id is a safe, unique, boring key.
3. The artifact becomes `MISSING` and the source reports `availability: MISSING`; the Source and any file are never
   touched. The relink use case accepts only a file with the same size and SHA-256, but nothing calls it yet.
4. The database could have been edited or damaged; a stored key must never be allowed to escape the managed folders.
5. A second backend opening the same library; not edits by other programs, and not shares without lock support.

## 8. Related files

- Previous: [07 Erasure](07-erasure.md) · Next: [09 Read a database and a log](09-read-a-database-and-a-log.md)
- [`backend/infrastructure/storage/layout.py`](../../../../backend/infrastructure/storage/layout.py), [`library_lock.py`](../../../../backend/infrastructure/storage/library_lock.py)
- [`docs/research/tech-stack.md`](../../../research/tech-stack.md) section 15
- [Sources and artifacts](../03-backend/domain/02-sources-and-artifacts.md)
