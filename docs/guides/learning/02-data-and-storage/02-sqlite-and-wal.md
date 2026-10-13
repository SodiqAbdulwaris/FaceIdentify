# Data 02 SQLite, WAL and the pragmas

## 1. What this is and why it exists

**SQLite** is a database in a single file with no server: your program calls it as a library. That suits a
single-user desktop app: nothing to install, nothing to administer, one file to back up. The trade-off is that
it allows **one writer at a time**. This lesson explains **WAL mode** (how SQLite stays safe and fast under that
rule), the settings the project applies to every connection, and the one mistake that can silently lose your
data when you copy a database.

## 2. Where it lives

| Thing | Where |
|---|---|
| The engine and the per-connection settings | `backend/infrastructure/db/engine.py` (`create_sqlite_engine`, `SQLITE_PRAGMAS`) |
| WAL behaviour tests | `tests/integration/test_sqlite_wal_behaviour.py` |
| The WAL-truncation helper used by erasure | `truncate_wal` in `engine.py` |
| The decision to use SQLite (and when to leave it) | `docs/research/tech-stack.md`; PostgreSQL is only adopted if measured write contention demands it |

## 3. How it works

- **WAL mode (write-ahead log).** Changes are appended to a side file (`library.db-wal`) and merged into the
  main file later (a *checkpoint*). Readers keep reading the last committed state while a writer writes, so
  **reading never blocks writing**. A third file, `library.db-shm`, is shared memory used to coordinate
  connections.
- **Pragmas** are SQLite settings. The project applies these to **every new connection**
  (`SQLITE_PRAGMAS`), because `foreign_keys` is per-connection:

  | Pragma | Meaning here |
  |---|---|
  | `foreign_keys = ON` | enforce foreign keys (SQLite ignores them otherwise) |
  | `journal_mode = WAL` | the write-ahead log described above |
  | `synchronous = NORMAL` | a balance of safety and speed in WAL mode |
  | `busy_timeout = 5000` | wait up to 5 seconds for the write lock before failing |
  | `temp_store = MEMORY` | temporary tables in memory |
  | `secure_delete = ON` | overwrite deleted content with zeros, so erased data is not left lying in the file |

- **Why WAL has a catch.** While the application is running, the *latest committed data may live only in
  `library.db-wal`*, not in `library.db`. The three files are one database. Copying just `library.db` copies a
  stale picture, and may copy an empty one.
- **A clean close checkpoints**: when the last connection closes, SQLite merges the log into the main file and
  deletes `-wal` and `-shm`. That is why a stopped library shows only `library.db` and `.lock`.

## 4. Try it

**Works with no models. Verified 2026-10-12.** Needs a library in `~/faceidentify-play` (lesson 07) or any
processed library.

1. **See the three files.** With the backend running:

   ```bash
   ls -la ~/faceidentify-play/lib/database
   ```

   Expected: `.lock` (0 bytes), `library.db`, `library.db-shm` (32768 bytes) and `library.db-wal` (can be megabytes;
   in the verified run the main file was 528 KB while the log was 2.8 MB). Stop the backend and list again:
   the `-wal` and `-shm` files are gone, and `library.db` has grown.
2. **See the settings a project connection gets:**

   ```python
   >>> from pathlib import Path
   >>> from backend.infrastructure.db.engine import create_sqlite_engine
   >>> engine = create_sqlite_engine(Path.home() / "faceidentify-play/copy.db")   # a copy, see lesson 01
   >>> with engine.connect() as con:
   ...     for p in ["foreign_keys", "journal_mode", "synchronous", "busy_timeout", "temp_store", "secure_delete"]:
   ...         print(p, con.exec_driver_sql(f"PRAGMA {p}").fetchone()[0])
   foreign_keys 1
   journal_mode wal
   synchronous 1
   busy_timeout 5000
   temp_store 2
   secure_delete 1
   ```

   (`synchronous 1` is NORMAL; `temp_store 2` is MEMORY.) A plain `sqlite3.connect(...)` gives `foreign_keys 0`
   unless you set it.
3. **Prove the copy hazard** (read-only, safe):

   ```python
   import shutil, sqlite3, pathlib
   home = pathlib.Path.home() / "faceidentify-play"
   shutil.copy(home / "lib/database/library.db", home / "naive-copy.db")      # the WRONG way, while the backend runs
   print(sqlite3.connect(home / "naive-copy.db").execute("select count(*) from sources").fetchone())
   src = sqlite3.connect(f"file:{home}/lib/database/library.db?mode=ro", uri=True)
   print(src.execute("select count(*) from sources").fetchone())
   ```

   Observed: the naive copy had `(0,)` sources while the real library had `(5,)`: all the data was in the log.
4. **The right way to copy a running database** is SQLite's backup API (it understands the log):

   ```python
   dst = sqlite3.connect(home / "good-copy.db")
   src.backup(dst); src.close()
   print(dst.execute("select count(*) from sources").fetchone())
   ```

   Expected: the real count. Or stop the backend first and copy the whole `database` folder. Delete the copies
   you made.
5. Run the WAL behaviour tests: `uv run pytest tests/integration/test_sqlite_wal_behaviour.py -q`. Expected: pass.
   They document how readers, writers and snapshots behave, with real files.

## 5. Change it

You do not change the pragma list casually: each line is a recorded decision (`secure_delete` for erasure,
`foreign_keys` for integrity). The tests that guard them are `tests/integration/test_sqlite_wal_behaviour.py`,
`tests/integration/test_sqlite_erasure_policy.py` and `tests/integration/test_engine_transactions.py`. To see a
pragma matter, in a scratch Python session open a plain connection to your copy and compare `secure_delete`:
`sqlite3.connect(...).execute("pragma secure_delete").fetchone()` is `(0,)`, the project engine's is `1`. That
difference is the guarantee that freed pages are zeroed (tested by looking for the erased bytes in the file in
`test_sqlite_erasure_policy.py`).

## 6. Break it on purpose

The copy hazard of step 3 *is* the break. A second one: open the database file with an ordinary tool while the
backend is writing and run a long query: with WAL the backend is not blocked (readers do not block writers),
but a long-held read snapshot stops the log from being truncated (`truncate_wal` returns `False` and erasure
reports "outstanding cleanup" rather than complete). That is a feature: it is better to say "not finished" than
to claim an erasure that is not.

## 7. Exercises

1. Name the three files of a live SQLite WAL database.
2. Why did the naive copy have zero sources?
3. Which API copies a live database safely?
4. What does `busy_timeout = 5000` mean?
5. Why is `foreign_keys = ON` applied on every connection?

**Answers**

1. `library.db`, `library.db-wal`, `library.db-shm`.
2. The committed rows were still in the write-ahead log, which the copy did not include.
3. `sqlite3.Connection.backup` (the SQLite online backup API), or copy after a clean shutdown.
4. A writer waits up to 5000 ms for the write lock before reporting "database is locked".
5. It is a per-connection setting; a connection without it silently ignores foreign keys.

## 8. Related files

- Previous: [01 SQL and tables](01-sql-and-tables.md) · Next: [03 Transactions and the unit of work](03-transactions-and-unit-of-work.md)
- [`backend/infrastructure/db/engine.py`](../../../../backend/infrastructure/db/engine.py)
- [Erasure](07-erasure.md) uses `secure_delete` and `truncate_wal`
- Further reading: sqlite.org "Write-Ahead Logging"
