# Lifecycle: what "delete" really means

The application has **four different ways to remove something**, with four different consequences. Mixing them up is the most
dangerous misunderstanding in a face-memory product.

| Action | What goes | What stays | Reversible? | Lesson |
|---|---|---|---|---|
| **Recycle** a source | nothing: it leaves the library views | everything (files, faces, evidence) | yes (restore) | [01](01-recycle-and-restore.md) |
| **Restore** a source | n/a | n/a | n/a | [01](01-recycle-and-restore.md) |
| **Permanently delete** a source | the picture's bytes, its faces' vectors, observations, runs | a tombstone, names, other photos' memory, evidence without biometric payload | **no** | [02](02-permanent-delete.md) |
| **Forget** an identity | its face vectors (the "memory of what the face looked like") | the photographs, the person's name | **no** | [03](03-forget.md) |

**Works with no models. Verified 2026-10-12.** Tests for the whole folder:

```bash
uv run pytest tests/integration/test_source_recycle.py tests/integration/test_api_source_lifecycle.py \
  tests/integration/test_permanent_source_delete.py tests/integration/test_api_source_permanent_delete.py \
  tests/integration/test_forget_identity.py tests/integration/test_api_forget.py tests/integration/test_storage_cleanup.py -q
```

Observed per pair: `39 passed`, `51 passed`, `32 passed` and `33 passed` for the cleanup file (about a minute in total).

All three irreversible steps follow one rule: **authoritative change first, physical cleanup after, and an interrupted cleanup
is finished at the next start** ([recovery](../architecture/06-recovery.md), [erasure](../../02-data-and-storage/07-erasure.md)).
Back to [the backend](../README.md).
