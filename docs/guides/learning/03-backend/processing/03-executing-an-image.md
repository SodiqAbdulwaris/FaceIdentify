# Processing 03 Executing an image

## 1. What this is and why it exists

`ExecuteProcessingJob` does the expensive part: it reads the stored original, finds faces, computes vectors, asks the
reasoner what each face is, and writes everything as **private** output. Its single most important design rule: **no
expensive operation runs inside a database write transaction**, and **nothing it writes is visible to the user** until
acceptance ([next lesson](04-checkpoints-and-acceptance.md)). A slow model must not block SQLite's one writer, and a crash must not show half a result.

## 2. Where it lives

| Thing | Where |
|---|---|
| The executor (`execute`, `_cancel_if_requested`, `_settle_detections`, `_settle_representations`, `_decide`, `_finalize`, `_fail`) | `ExecuteProcessingJob` in `backend/app/processing/execute_job.py` |
| Writing private rows | `backend/app/processing/pending_output.py` |
| The perception client (detect, represent, fallbacks) | `backend/app/runtime/perception_client.py` ([lesson](../runtime-and-worker/03-perception-client-and-providers.md)) |
| Decoding | `backend/infrastructure/media/image.py` |
| Tests | `tests/integration/test_execute_processing_job.py` (46 tests), `test_pending_output.py` |

## 3. How it works

`execute` is a straight line (read it once top to bottom; it is about 50 lines):

```text
cancel check
read the run's input and frozen snapshot            (short read transaction)
plan = catalog selections from the snapshot
decode the original (bounded pixel count)           (no transaction)
client.detect(pixels)                               (the worker; seconds)
cancel check
write PENDING observations                          (short write)
client.represent(pixels, detections)               (the worker)
write PENDING representations                       (short write)
write an INTERMEDIATE checkpoint                    (short write)
decide each face (retrieval + assessment + reasoner, read-only)
persist the decisions as candidate snapshots        (short write)
cancel check
write the FINAL checkpoint, run -> FINALIZING       (short write)
```

- **Cancellation is cooperative**: the executor looks for a request *between* external work units, never in the middle of one.
- **Provider fallbacks** are recorded: the client may fall back to a second provider when allowed; the executor ends the
  current segment and starts the next so provenance stays true.
- **Failures it knows** (`SETTLED_FAILURES`: missing bytes, unreadable image, a bad private-output write, a perception error,
  an unavailable runtime, a crashed worker, an OS error) are settled `FAILED` (run and job) *then re-raised*; the output
  stays private. Anything else is a defect handled by the runner ([scheduler lesson](../architecture/05-scheduler-and-runner.md)).
- **It never makes anything authoritative**: no `ACTIVE` rows, no index operations. A valid FINAL checkpoint is only a hand-off.
- The write functions re-check the claimed context (`_revalidate_settlement_context`): if the run changed under it, nothing is written.

## 4. Try it

**Works with no models. Verified 2026-10-12.**

```bash
uv run pytest tests/integration/test_execute_processing_job.py tests/integration/test_pending_output.py -q
```

Expected: pass (the four processing test files together: `209 passed`). Read three tests by name:
`test_execute_processing_job.py` has one per failure kind and one for cancellation at each boundary. Then see the
sequence in a real run from the practice library:

```bash
uv run python q.py ~/faceidentify-play/lib "select ordinal, kind, state, length(payload_json) from processing_checkpoints order by processing_run_id, ordinal"
```

Observed: for each run an `INTERMEDIATE` checkpoint (ordinal 0, 140 bytes: the observation and representation ids) and a `FINAL`
one (ordinal 1, 900 to 1100 bytes: the decisions).

## 5. Change it

A new stage (for example a quality filter between detect and represent) is a new step in the straight line plus: a
checkpoint decision (does a crash here need a resumable boundary?), a cancel check, a settled-failure mapping, and a test per
branch in `test_execute_processing_job.py` first. Do not add a loop that retries a model call inside the executor; retries
are user-driven ([cancel and retry](05-cancel-and-retry.md)).

## 6. Break it on purpose

In a scratch edit, move the `detect` call inside a `self._uow.write(...)` lambda and run the integration tests with a
slow fake: other writers wait for seconds. The architecture check is by reading: grep `execute_job.py` for `client.detect` and
confirm it is not within a `write(` block. Restore with `git restore`.

## 7. Exercises

1. Why does `execute` never call the model inside a write transaction?
2. What happens to a face already written when embedding fails?
3. Where is a cancellation noticed?
4. Does a successful `execute` make anything visible?

**Answers**

1. A slow call would hold SQLite's only write lock and stall every other request.
2. Its `PENDING` observation stays private; the run is settled `FAILED`.
3. Between external work units (`_cancel_if_requested`).
4. No; it ends with the run `FINALIZING` and a FINAL checkpoint; acceptance makes it visible.

## 8. Related files

- Previous: [02](02-configuration-snapshots.md) · Next: [04 Checkpoints and acceptance](04-checkpoints-and-acceptance.md)
- [`backend/app/processing/execute_job.py`](../../../../../backend/app/processing/execute_job.py)
