# Domain 02 Sources and artifacts

## 1. What this is and why it exists

A **Source** is the user's entry in the library ("this photograph"). An **Artifact** is a stored file behind it. They are two
tables on purpose: a source owns its *library lifecycle* (active, recycled, deleting, deleted), an artifact owns the *bytes*
(where they are, their hash, whether the file is present). One source may have several artifacts (the original, a thumbnail),
and the front end never sees a file path, only ids.

## 2. Where it lives

| Thing | Where |
|---|---|
| Models and enums (`Artifact`, `Source`, `ArtifactKind`, `StorageMode`, `ArtifactState`, `SourceState`) | `backend/app/sources/models.py` |
| Import | `ImportSourceUseCase` in `backend/app/sources/import_source.py` |
| Managed files, referenced files | `artifact_storage.py`, `referenced_artifacts.py`; bytes in `backend/infrastructure/storage/` |
| Tests | `tests/integration/test_import_source.py`, `test_artifact_storage.py`, `test_referenced_artifacts.py` |
| Spec | `PERSISTENCE_IMPLEMENTATION.md` section 4 |

## 3. How it works

- **Artifact kinds**: `SOURCE_ORIGINAL`, `FACE_CROP`, `THUMBNAIL`, `MODEL_EXPORT`, `RUNTIME_PACKAGE`.
- **Storage mode**: `MANAGED` (the library copied the bytes to `originals/<id>`; a logical `storage_key`, never a path) or
  `REFERENCED` (the file stays where the user keeps it; only its path is recorded and the file is never touched).
  A database check allows exactly one location form per artifact.
- **Artifact states**: `PENDING` (reserved, not yet written) → `AVAILABLE`; `MISSING` (the file is gone); `DELETING`,
  `DELETE_FAILED`, `DELETED`. An `AVAILABLE` managed artifact must carry its `sha256` and size (a check).
- **Source states**: `ACTIVE`, `RECYCLED` (in the bin), `DELETING`, `DELETED`, `UNAVAILABLE`.
- **Import is a three-step protocol** so a crash leaves nothing half-made: reserve a `PENDING` artifact (its final key exists
  before any byte), write the bytes, then in *one* transaction mark the artifact `AVAILABLE` and add the Source. The image is
  decoded in memory first, so what is validated is exactly what is stored. A crash leaves a reservation with no file
  (`MISSING`, `WRITE_NOT_COMPLETED`) or a stored file with no source, which recovery settles ([recovery](../architecture/06-recovery.md)).
- **No deduplication**: importing the same file twice makes two sources. A source is the user's own entry, not a unique file.

## 4. Try it

**Works with no models. Verified 2026-10-12.** On the practice library ([README](README.md)):

```bash
uv run python q.py ~/faceidentify-play/lib "select kind, storage_mode, storage_key, hex(substr(sha256,1,4)), size_bytes, mime_type, original_filename from artifacts where kind='SOURCE_ORIGINAL'"
```

Observed (three rows): `('SOURCE_ORIGINAL', 'MANAGED', 'originals/90e0df41...', '06B205DA', 14989, 'image/png', 'red.png')`,
the green picture with a different hash, and `red-copy.png` with the **same hash `06B205DA` and size 14989 but its own key**:
two sources, two artifacts, identical bytes. Then:

```bash
ls ~/faceidentify-play/lib/originals
uv run python q.py ~/faceidentify-play/lib "select display_name, width, height, state, revision, thumbnail_artifact_id is not null from sources"
```

The folder holds three files named by key (no file extension, no original name). Observed: each source is `320 x 240`,
`ACTIVE`, **revision 2** (import made revision 1; accepting the processing run bumped it), and has no thumbnail (the
development profile makes none).

## 5. Change it

Add a new artifact kind only with a migration (the kind is a database check list: `enum_check("kind", ArtifactKind)`), the
enum, and a test; the add-a-column walk-through is in [migrations](../../02-data-and-storage/04-migrations-alembic.md). The
safe code-reading exercise: follow `import_managed` and write down which transaction each of the three steps uses.

## 6. Break it on purpose

On a **copy** of the practice library (never the only copy), move one file out of `originals/` to another folder while the backend is stopped, then start the
backend on the copy: recovery marks that artifact `MISSING` (existence only; nothing is hashed at startup) and the source reports its original unavailable.
To undo the experiment, discard the copy. **Limitation:** putting the file back and restarting does *not* bring the artifact back to `AVAILABLE`. The functions that
do (`reverify_managed_artifact`, `reverify_referenced_artifact`, `relink_referenced_artifact` in `backend/app/sources/`) exist, but nothing calls them yet, so today the
artifact stays `MISSING` until such a step is wired in (verified by `grep`, 2026-10-12; reviewer finding on PR #170).

## 7. Exercises

1. Why is the artifact reserved before the bytes are written?
2. What do `red.png` and `red-copy.png` share, and what do they not?
3. Why does a `REFERENCED` artifact never get deleted from disk?
4. Which table owns "in the bin"?

**Answers**

1. So the final key exists before any byte, and a crash is recoverable by looking for reservations.
2. The bytes (hash, size); not the source id, the artifact id or the storage key.
3. The file belongs to the user; the library only forgets the path.
4. `sources` (`RECYCLED`), not `artifacts`.

## 8. Related files

- Previous: [01 Vocabulary](01-vocabulary.md) · Next: [03 Observations and representations](03-observations-and-representations.md)
- [`backend/app/sources/models.py`](../../../../backend/app/sources/models.py), [storage lesson](../../02-data-and-storage/08-storage-roots-and-artifacts.md)
