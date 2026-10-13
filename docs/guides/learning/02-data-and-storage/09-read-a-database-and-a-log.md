# Data 09 Read a database and a log

## 1. What this is and why it exists

When something looks wrong, the two places that tell you the truth are the **database** (what the application
believes) and the **log** (what it said while it ran). This lesson is the practical toolkit: how to open a
library safely, a cheat sheet of questions to ask it, how to ask "*why* did it decide that?" from the stored
Evidence, and what the application does and does not write to a log. It uses `sqlite3` in Python because Python is
already installed; the real `sqlite3` command line works the same way if you have it.

## 2. Where it lives

| Thing | Where |
|---|---|
| The database | `<library root>/database/library.db` (+ `-wal`, `-shm` while running) |
| The decision evidence | tables `evidence`, `evidence_candidates`, `evidence_representations` (`backend/app/identities/models.py`) |
| The one error shape and the diagnostic id | `backend/api/errors.py` |
| What the host prints | `backend/api/host.py` (standard output: the handshake line only; everything else: standard error) |
| The shell relaying the backend's messages | `desktop/src-tauri/src/sidecar.rs` (the backend's standard error is logged at warn level, target `backend`) |
| The `logs/` folder | `<local state root>/logs/` is created by the layout; **nothing in the application writes a log file there yet** (observed empty after a full run) |

## 3. How it works

### Reading a database safely

- **Open read-only**: `sqlite3.connect("file:/path/library.db?mode=ro", uri=True)`. Then nothing you type can
  change it, even while the backend runs (WAL lets readers read while the backend writes).
- **Never copy only `library.db`** while the backend runs; use the backup API ([lesson 02](02-sqlite-and-wal.md)).
- **Never edit by hand** a library you care about. If you must experiment, experiment on a backup-API copy.
- Tools: any SQLite viewer works (for example DB Browser for SQLite, or the `sqlite3` shell if you have it:
  `sqlite3 "file:library.db?mode=ro" "select count(*) from sources;"`). Do not use Python's `python -m sqlite3` shell for a read-only look: it opens the name you give it as a plain file (no `uri=True`), so a
  `file:...?mode=ro` address fails with an `OperationalError`. Use the explicit Python connection above, as every lesson here does, which works everywhere.

### Reading a log

- The backend host writes **exactly one JSON line to standard output**, the handshake, and nothing else there.
- Everything it has to say goes to **standard error**: Python warnings and any logged error. uvicorn is configured
  quiet (`log_level="warning"`, `access_log=False`, `log_config=None`), so ordinary requests are **not** logged.
- An unexpected exception in a route returns only `500 INTERNAL_ERROR` with a **`diagnostic_id`**, no message, no
  traceback, no user data. The same id is logged with the traceback (`logger faceidentify.api`, line
  `unhandled <ErrorName> [diagnostic <id>]`) so a report can be matched to the log, which stays on the machine.
- In the desktop app the shell starts the host with its standard error piped, and logs every line at warn level
  under the target `backend` (in debug builds the Tauri log plugin shows them in the terminal running
  `npm run tauri dev`; its other targets are the plugin's defaults, *unverified here*).
- Therefore: **to keep a log when running by hand, redirect standard error to a file**:
  `uv run python -m backend.api.host ... 2> backend.err`.

## 4. Try it

**Works with no models. Verified 2026-10-12.**

1. **A cheat sheet against your scratch library** (paste into `uv run python -`):

   ```python
   import sqlite3, pathlib
   db = pathlib.Path.home() / "faceidentify-play/lib/database/library.db"
   con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
   q = lambda sql: [tuple(r) for r in con.execute(sql)]

   print("tables      ", len(q("select name from sqlite_master where type='table'")))
   print("migration   ", q("select version_num from alembic_version"))
   print("profile     ", q("select key, value from app_state"))
   for table in ("sources", "identities", "representations", "occurrences", "processing_runs", "jobs"):
       print(f"{table:16}", q(f"select state, count(*) from {table} group by state"))
   print("evidence    ", q("select kind, count(*) from evidence group by kind"))
   print("named       ", q("""select p.display_name, count(distinct o.id)
                              from people p
                              join identity_person_associations a on a.person_id = p.id and a.state = 'ACTIVE'
                              join occurrences o on o.identity_id = a.identity_id and o.state = 'ACTIVE'
                              group by p.display_name"""))
   ```

   Expected for the verified run: `tables 35`, `migration [('0010',)]`, `profile [('library_profile', 'DEVELOPMENT')]`,
   a `(state, count)` list per table, and `named [('Ada Example', 5)]` (the named person and how many faces are
   hers).
2. **Why did it decide that? Read the Evidence.** Every automatic decision stored its reason as JSON:

   ```python
   print(q("""select json_extract(payload_json, '$.outcome'), json_extract(payload_json, '$.reason')
              from evidence where kind in ('IDENTITY_CREATED', 'IDENTITY_MATCHED')"""))
   print(q("select rank, round(raw_similarity, 3), decision from evidence_candidates limit 5"))
   ```

   Observed: `[('CREATE_NEW', 'NO_CANDIDATE'), ('CREATE_NEW', 'NOT_SIMILAR'), ('MATCH_EXISTING', 'MATCHED'), ...]`:
   the first picture was new because there was nobody to compare with; the green one because it was not similar;
   the copies matched. `evidence_candidates` lists the scored candidates considered (`(1, 1.0, 'CONSIDERED')`,
   `(1, 0.208, 'CONSIDERED')`, ...). The full payload also holds the thresholds in force (`$.policy`).
3. **A timeline** of what happened, oldest first:

   ```python
   for row in q("select kind, substr(coalesce(subject_identity_id,''),1,6), created_at from evidence order by created_at"):
       print(row)
   ```

   Observed: `IDENTITY_CREATED`, `IDENTITY_MATCHED`, `IDENTITY_CREATED`, `IDENTITY_ASSIGNED_TO_PERSON` (the naming
   step), more `IDENTITY_MATCHED`, then `IDENTITY_FORGOTTEN`, each with a timestamp.
4. **Read the log, with a made-up failure.** The error handler is exercised in isolation:

   ```python
   from fastapi import FastAPI
   from fastapi.testclient import TestClient
   from backend.api.errors import install_error_handlers

   app = FastAPI(); install_error_handlers(app)

   @app.get("/boom")
   def boom():
       raise RuntimeError("secret path C:\\Users\\x")

   client = TestClient(app, raise_server_exceptions=False)
   print(client.get("/boom").json())
   ```

   Expected (observed): the printed body is `{'error': {'code': 'INTERNAL_ERROR', 'message': 'An unexpected error
   occurred.', 'details': None, 'retryable': False, 'diagnostic_id': '<32 hex characters>'}}`, with **no** mention of
   `secret path`; and on **standard error** a line `unhandled RuntimeError [diagnostic <the same id>]` followed by
   the traceback (which does contain the message; the log is local). Match the id in the body to the id in the log:
   that is how a bug report is traced. (A deprecation warning from `TestClient` may also appear; it is unrelated.)
5. **Capture a real host's standard error**, then look at it:

   ```bash
   uv run python -m backend.api.host --library-root ~/faceidentify-play/lib \
     --local-state-root ~/faceidentify-play/state --development-profile > out.txt 2> err.txt &
   ```

   After a few requests, `cat out.txt` shows the single handshake line and `cat err.txt` is (nearly) empty on a
   healthy run: the quiet uvicorn configuration means silence is the normal sound. (If `uv` warns about its own
   environment variables, that goes to `err.txt` as well.)

## 5. Change it

The change you make is a **habit**, not code: before you report "it looks wrong", write down the library state with
the cheat sheet and, if there was an error, its `diagnostic_id` and the matching log lines. When a new question
comes up that the cheat sheet cannot answer, add the query to this lesson (a documentation change) after you have run
it. To make the application *write* a log file would be a feature (a decision about what may be logged, since logs
must never contain biometric data or paths); it needs a plan, not a quick edit.

## 6. Break it on purpose

Open a **backup-API copy** (never the real library) without `mode=ro` and run `delete from evidence`. Observed
2026-10-12: it runs without complaint and the table is empty; the only database triggers in the schema protect the
processing-configuration snapshots (`trg_processing_configuration_snapshots_no_update`, `..._no_delete_while_used`,
`..._no_replace`). Evidence is append-only because the *application* never rewrites it, not because SQLite forbids
it. That is why you read with `mode=ro` and edit only copies.

## 7. Exercises

1. Write the query that lists the five newest evidence rows with their kind.
2. Where would you find the thresholds that were in force when a face was decided?
3. A user reports `INTERNAL_ERROR` with diagnostic id `b2ff...`. What do you do?
4. Why is the host's standard output almost empty?
5. How do you open a library so you cannot change it by accident?

**Answers**

1. `select kind, created_at from evidence order by created_at desc limit 5`.
2. In the Evidence `payload_json` (`$.policy`: version, `min_detection_score`, `match_threshold`, `margin`,
   `new_identity_ceiling`) and the run's frozen configuration snapshot.
3. Search the backend's standard error (the file you redirected) for `diagnostic b2ff...`; the traceback is there.
4. It carries only the handshake line the shell reads; all else goes to standard error.
5. `sqlite3.connect("file:...library.db?mode=ro", uri=True)`.

## 8. Related files

- Previous: [08 Storage roots and artifacts](08-storage-roots-and-artifacts.md) · [Data index](README.md)
- [`backend/api/errors.py`](../../../../backend/api/errors.py), [`backend/api/host.py`](../../../../backend/api/host.py)
- [Evidence](../03-backend/domain/06-occurrences-and-evidence.md)
