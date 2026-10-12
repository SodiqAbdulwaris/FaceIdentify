# 05 One request, end to end

## 1. What this is and why it exists

This is the short version of the most important story in the product: **you give it a photograph and
a name appears**. Reading the stages once, with the vocabulary still light, makes every later lesson
easier to place. The long version, naming the exact file at each step, is
[one photograph, end to end](../07-walkthrough-and-glossary/01-one-photograph.md).

## 2. Where it lives

The story crosses all four programs. The key files, in order:

`frontend/src/features/library/LibraryPage.tsx` → `backend/api/routes/sources.py` →
`backend/app/sources/import_source.py` → `backend/api/routes/processing.py` →
`backend/app/processing/process_source.py` → `backend/api/scheduler.py` →
`backend/app/processing/runner.py` → `execute_job.py` → `backend/app/recognition/reasoner.py` →
`backend/app/processing/accept_run.py` → `backend/api/events.py` → the screen refetches.

## 3. How it works

You drop a photograph into the library screen and press **Process**. In outline:

1. **Import.** The front end sends `POST /api/v1/sources/import` with a path (the shell's native file
   picker supplies it). The backend either copies the file into the library (`MANAGED`) or records a
   verified reference to it (`REFERENCED`), computes its SHA-256 fingerprint, and creates a **Source**
   row and an **Artifact** row in one transaction. Nothing is recognised yet.
2. **Request.** You press process: `POST /api/v1/sources/{id}/process`. The backend writes a **Job**
   (scheduling) and a **ProcessingRun** (history) with a frozen copy of all the settings, the
   **snapshot**, in one transaction, and answers `202 Accepted`. Still nothing has been recognised.
3. **Claim and execute.** The **scheduler** loop, a background task inside the backend, claims the job,
   and the **ProcessingRunner** executes it: decode the image, ask the ML worker to detect faces,
   write each face as a *pending* **Observation**, ask the worker for each face's embedding, write
   *pending* **Representations**, search the memory for similar ones, and let the **reasoner** decide.
   (In the development profile the "worker" is a fake that finds one face in the middle of every image.)
4. **Accept.** A final checkpoint is written. Then **acceptance** runs in **one transaction**: pending
   data becomes active, **Occurrences** and **Evidence** are written, new **Identities** are created,
   vectors are queued for the index, and the run is marked completed.
5. **Tell the screen.** The backend publishes an event over the WebSocket; the front end re-fetches the
   affected data and shows the faces and the people found.

Two ideas to hold on to:

- **Private until accepted.** Everything written before step 4 is `PENDING` and invisible to every
  read route. If the program dies anywhere, nothing half-done is ever shown.
- **The request returns before the work is done.** `202` means "I wrote down that this must happen".
  That is why the screen watches events and refetches.

## 4. Try it

**Works with no models. Verified 2026-10-12.** Do [lesson 07](07-run-it-and-see-it-work.md) first; this
section then reads back what one run left in the database. Replace `LIB` with your library folder
(`~/faceidentify-play/lib`) and stop the backend if you want the database free of the write-ahead
files (you can also read while it runs; the connection below is read-only).

```bash
uv run python - <<'EOF'
import sqlite3, pathlib
db = pathlib.Path.home() / "faceidentify-play/lib/database/library.db"
con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
for title, sql in [
    ("sources",     "select display_name, state, kind from sources order by created_at"),
    ("jobs",        "select type, state, priority, priority_rank from jobs"),
    ("runs",        "select state from processing_runs"),
    ("checkpoints", "select kind, state, count(*) from processing_checkpoints group by 1, 2"),
    ("observations","select state, count(*) from observations group by state"),
    ("vectors",     "select state, count(*) from representations group by state"),
    ("identities",  "select state, count(*) from identities group by state"),
    ("evidence",    "select kind, count(*) from evidence group by kind"),
    ("index queue", "select operation, state, count(*) from index_operations group by 1, 2"),
]:
    print(title, [tuple(r) for r in con.execute(sql)])
EOF
```

Expected for the three-picture run in lesson 07 (two identical pictures and one different one):

```text
sources [('red', 'ACTIVE', 'IMAGE'), ('red-copy', 'ACTIVE', 'IMAGE'), ('green', 'ACTIVE', 'IMAGE')]
jobs [('PROCESS_SOURCE', 'COMPLETED', 'INTERACTIVE', 0), ... three rows]
runs [('COMPLETED',), ('COMPLETED',), ('COMPLETED',)]
checkpoints [('FINAL', 'VALID', 3), ('INTERMEDIATE', 'VALID', 3)]
observations [('ACTIVE', 3)]
vectors [('ACTIVE', 3)]
identities [('ACTIVE', 2)]
evidence [('IDENTITY_CREATED', 2), ('IDENTITY_MATCHED', 1)]
index queue [('ADD', 'APPLIED', 3)]
```

Read it as the story: three sources, three jobs and runs, each run left an intermediate and a final
checkpoint, three faces became three active vectors, **two identities** exist (the copy matched the
first picture's identity: `IDENTITY_MATCHED`; the green picture started a new one:
`IDENTITY_CREATED`), and three `ADD` operations were queued for the index and applied.

## 5. Change it

Re-run the same experiment with a different second picture and predict the evidence before you look:
import only `red.png` and `green.png`, process both, then count identities. Prediction: two
`IDENTITY_CREATED`, no `IDENTITY_MATCHED`. The behaviour is pinned by the integration tests:

```bash
uv run pytest tests/integration/test_m3_end_to_end.py -q
```

Expected: pass. It runs recognise, restart, rebuilt index, recognise again, with planted perception.

## 6. Break it on purpose

Ask to process a source that does not exist:

```bash
curl -s -X POST -H "Authorization: Bearer $FACEIDENTIFY_LAUNCH_TOKEN" \
  http://127.0.0.1:PORT/api/v1/sources/00000000-0000-0000-0000-000000000000/process
```

Expected: `404` with `{"error":{"code":"SOURCE_NOT_FOUND",...}}` (this is the first check in
`process_source` in `backend/api/routes/processing.py`; verified by reading, and the not-found path is
covered in `tests/integration/test_api_processing_routes.py`).

## 7. Exercises

1. Why does `POST .../process` answer `202` and not `200`?
2. In the run above, why are there three `ADD` index operations but only two identities?
3. What would the screen show if the program were killed after step 3 but before step 4?
4. Which table says *why* the copy was matched?

**Answers**

1. The work has been recorded, not done; `202 Accepted` means "will be done later".
2. An index entry is per *face* (representation), not per identity: three faces, three vectors; two of
   them belong to the same identity.
3. Nothing from that run: its pending observations and representations are private; at the next start
   recovery marks the interrupted run `INTERRUPTED`, keeps its output private, and a retry is an
   explicit new job.
4. `evidence` (with `evidence_candidates` holding the scored candidates), kind `IDENTITY_MATCHED`.

## 8. Related files

- Previous: [04 Layers and the repository map](04-layers-and-repository-map.md) · Next: [06 Set up your machine](06-set-up-your-machine.md)
- [One photograph, end to end](../07-walkthrough-and-glossary/01-one-photograph.md)
- [Jobs and runs](../03-backend/processing/01-jobs-and-runs.md), [acceptance](../03-backend/processing/04-checkpoints-and-acceptance.md)
