# Data 01 SQL and tables

## 1. What this is and why it exists

A **relational database** stores data in **tables**. A table has **columns** (the fields) and **rows**
(the records). Each row is identified by a **primary key**. Tables refer to each other with **foreign
keys**: a column holding another table's primary key. **SQL** is the language for asking a database
questions. You rarely write SQL in this project (the ORM does), but reading the migrations, the specs and
your own library is far easier when you recognise `SELECT`, `WHERE` and `JOIN`.

## 2. Where it lives

- The schema, as Python classes: `backend/app/**/models.py` (`sources`, `artifacts`, `observations`,
  `representations`, `identities`, `people`, `occurrences`, `evidence`, `jobs`, `processing_runs`, ...), all
  registered in `backend/app/models.py`.
- The schema, as the authority: `docs/specs/PERSISTENCE_IMPLEMENTATION.md` (`ERD.md` is conceptual only).
- The schema, as SQL: the migrations in `backend/alembic/versions/` ([lesson 04](04-migrations-alembic.md)).
- Your data: `<library root>/database/library.db`. At revision `0010` it has **35 tables** (including
  Alembic's own `alembic_version`).

## 3. How it works

```text
sources                           observations
id (PK)    kind    state          id (PK)   source_id (FK -> sources.id)   box   state
-----------------------           ----------------------------------------------------
s1         IMAGE   ACTIVE         o1        s1                              ...   ACTIVE
                                  o2        s1                              ...   ACTIVE
```

```sql
SELECT id, state FROM sources WHERE kind = 'IMAGE' ORDER BY created_at DESC LIMIT 10;
INSERT INTO sources (id, kind, state) VALUES (...);
UPDATE sources SET state = 'RECYCLED' WHERE id = '...';
DELETE FROM sources WHERE id = '...';
SELECT o.id FROM observations o JOIN sources s ON s.id = o.source_id WHERE s.state = 'ACTIVE';
```

**Constraints** make the database refuse bad data whatever the code does:

- `NOT NULL`: a value is required. `UNIQUE`: no two rows may share the value(s).
- **`CHECK (state IN ('ACTIVE','RECYCLED',...))`**: only listed values allowed. Status columns with a decided,
  finite vocabulary have one, generated from the Python enum (a few runtime-catalog fields deliberately stay
  plain strings until their value sets are decided).
- **Foreign key `ON DELETE RESTRICT`**: you may not delete a row something else still points at (nearly
  everywhere, so history cannot be orphaned); `SET NULL` clears the pointer.
- **Indexes** (not the vector kind): a sorted structure that makes lookups on a column fast. A **partial
  unique index** enforces a rule over only some rows (for example "at most one valid FINAL checkpoint per run").

Names are deterministic (`ck_sources_state`, `fk_sources_original_artifact_id_artifacts`, `pk_sources`,
`ix_...`, `uq_...`) because SQLite can only change a constraint by recreating the table, which needs a stable
name for every constraint (`NAMING_CONVENTION` in `backend/infrastructure/db/engine.py`).

Types worth knowing: ids are **UUIDs stored as 32-character text** (`CHAR(32)`); times are **UTC** (stored as
naive UTC, re-tagged on load, and a time without a timezone is refused); JSON columns hold payloads.

## 4. Try it

**Works with no models. Verified 2026-10-12** on a library produced by the lesson-07 run (a read-only
connection, so it is safe even while the backend runs).

Run this as a script (paste into `uv run python -`), changing the path if yours differs:

```python
import sqlite3, pathlib
db = pathlib.Path.home() / "faceidentify-play/lib/database/library.db"
con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)

print([r[0] for r in con.execute("select name from sqlite_master where type='table' order by 1")])
```

Expected: a list of 35 table names starting `'alembic_version', 'ann_key_sequences', 'app_state', 'artifacts',
'component_versions', 'components', 'evidence', ...` and including `identities`, `observations`,
`representations`, `sources`, `jobs`, `processing_runs`.

1. **The shape of one table, with its constraints:**

   ```python
   print(con.execute("select sql from sqlite_master where name='sources'").fetchone()[0])
   ```

   Expected: a `CREATE TABLE sources (id CHAR(32) NOT NULL, kind VARCHAR NOT NULL, state VARCHAR NOT NULL, ...)`
   with lines such as `CONSTRAINT ck_sources_state CHECK (state IN ('ACTIVE', 'RECYCLED', 'DELETING', 'DELETED',
   'UNAVAILABLE'))` and `CONSTRAINT ck_sources_display_name_not_empty CHECK (length(trim(display_name)) > 0)`.
2. **Count rows by state** (a question you will ask constantly):

   ```python
   for sql in ["select state, count(*) from sources group by state",
               "select state, count(*) from identities group by state",
               "select kind, count(*) from evidence group by kind"]:
       print(sql, [tuple(r) for r in con.execute(sql)])
   ```

   Expected for the three-picture run: sources `[('ACTIVE', 3)]`, identities `[('ACTIVE', 2)]`, evidence
   `[('IDENTITY_CREATED', 2), ('IDENTITY_MATCHED', 1)]`.
3. **A join across the chain Source, Observation, Representation, Identity:**

   ```python
   sql = """select s.display_name, i.state, count(*)
            from sources s
            join observations o on o.source_id = s.id
            join representations r on r.observation_id = o.id
            join identities i on i.id = r.identity_id
            group by s.display_name, i.state order by 1"""
   print([tuple(r) for r in con.execute(sql)])
   ```

   Expected: one row per source with its identity's state and a count of faces, e.g.
   `[('green', 'ACTIVE', 1), ('red', 'ACTIVE', 1), ('red-copy', 'ACTIVE', 1)]`.
4. **Columns of a table:** `[r[1] for r in con.execute("pragma table_info(representations)")]` lists
   `id, observation_id, identity_id, processing_run_id, execution_segment_id, representation_space_id, state,
   ann_key, vector, vector_dimension, quality_json, created_at, activated_at, erased_at, runtime_variant_id`.

## 5. Change it

Never edit the real library by hand. To see a constraint work, change a **copy** (taken safely, see
[lesson 02](02-sqlite-and-wal.md)). Back up with the SQLite backup API, then break rules in the copy:

```python
import sqlite3, pathlib
home = pathlib.Path.home() / "faceidentify-play"
src = sqlite3.connect(f"file:{home}/lib/database/library.db?mode=ro", uri=True)
dst = sqlite3.connect(home / "copy.db")
src.backup(dst); src.close()
try:
    dst.execute("update sources set state='BOGUS'")
except sqlite3.IntegrityError as e:
    print("IntegrityError:", e)
```

Expected: `IntegrityError: CHECK constraint failed: ck_sources_state`. The database refused text the enum does
not list. (Delete `copy.db` afterwards.)

## 6. Break it on purpose

Foreign keys are **off by default in every new SQLite connection**. On the copy:

```python
print(dst.execute("pragma foreign_keys").fetchone())        # (0,)  off
dst.execute("delete from sources")                          # succeeds!? every source gone
dst.rollback()
dst.execute("pragma foreign_keys = on")
dst.execute("delete from sources")                          # IntegrityError: FOREIGN KEY constraint failed
```

Observed: with enforcement off the delete succeeded and removed the rows; with it on it failed with
`FOREIGN KEY constraint failed`. That is why `engine.py` applies `PRAGMA foreign_keys = ON` on **every**
connection (the `SQLITE_PRAGMAS` list), never "once at startup". Any script that opens the database
itself, like these, must do the same before changing anything, or better, open it read-only.

## 7. Exercises

1. Which column links an observation to its source?
2. What does `ck_sources_state` prevent?
3. Write the query that counts the representations in each state.
4. Why does a new connection need `PRAGMA foreign_keys = ON`?
5. Count the tables in your library. Is the number 35?

**Answers**

1. `observations.source_id` (a foreign key to `sources.id`).
2. Any `state` text other than the five enum members.
3. `select state, count(*) from representations group by state`.
4. SQLite ignores foreign keys unless asked, per connection.
5. `select count(*) from sqlite_master where type='table'` gives 35 at revision `0010`; it changes when a
   revision adds a table.

## 8. Related files

- Next: [02 SQLite, WAL and the pragmas](02-sqlite-and-wal.md) · [Data index](README.md)
- [`docs/specs/PERSISTENCE_IMPLEMENTATION.md`](../../specs/PERSISTENCE_IMPLEMENTATION.md), [`backend/infrastructure/db/engine.py`](../../../backend/infrastructure/db/engine.py)
- [Domain vocabulary](../03-backend/domain/01-vocabulary.md)
- Further reading: sqlite.org "SQL As Understood By SQLite"
