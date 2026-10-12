# Data 05 SQLAlchemy: rows as Python objects, and repositories

## 1. What this is and why it exists

You do not write SQL strings in this project. **SQLAlchemy** (version 2) maps each table to a Python class (the
**ORM**, object-relational mapper) and builds the SQL for you, and **repositories** wrap the queries a feature
needs ("claim the next queued job") so use cases do not scatter SQL. This lesson shows how a table becomes a
class, how to query and change rows, and where a repository sits.

## 2. Where it lives

| Thing | Where |
|---|---|
| The shared base and the naming convention | `Base` and `NAMING_CONVENTION` in `backend/infrastructure/db/engine.py` |
| Column helpers | `backend/infrastructure/db/types.py`: `uuid_pk`, `UTCDateTime`, `enum_check` |
| Models, one file per topic | `backend/app/sources/models.py`, `backend/app/memory/models.py`, `backend/app/identities/models.py`, `backend/app/people/models.py`, `backend/app/processing/models.py`, `backend/app/jobs/models.py`, `backend/app/runtime/models.py`, `backend/app/settings/models.py` |
| The registry of all models | `backend/app/models.py` |
| Repositories | `backend/app/*/repository.py` (for example `backend/app/jobs/repository.py`, `backend/app/sources/repository.py`, `backend/app/memory/index_operation_repository.py`) |
| The optimistic update | `optimistic_locked_update` in `backend/infrastructure/db/optimistic.py` |

## 3. How it works

```python
class Identity(Base):                                   # a table
    __tablename__ = "identities"
    id: Mapped[uuid.UUID] = uuid_pk()                    # a column
    state: Mapped[str] = mapped_column(String)
    merged_into_identity_id: Mapped[uuid.UUID | None] = mapped_column(...)
    revision: Mapped[int] = mapped_column(Integer, default=1)

with Session(engine) as session:                         # a unit of conversation with the database
    identity = session.get(Identity, some_id)            # by primary key
    rows = session.scalars(select(Identity).where(Identity.state == "ACTIVE")).all()
    session.add(Identity(...))                           # stage an insert
    session.flush()                                      # send to the database, keep the transaction open
    session.commit()                                     # make permanent (the UnitOfWork does this for you)
```

- A **Session** is a workspace that tracks the objects you loaded and changed and sends the changes at `flush` or
  `commit`.
- **`select(...)`** builds a query; `.where`, `.join`, `.order_by`, `.limit` refine it. `session.scalars(...)` gives
  model objects (or single columns), `session.execute(...)` gives rows.
- Types: `Uuid` primary keys are stored as 32-character text; `UTCDateTime` stores UTC and refuses a time with no
  timezone; a `StrEnum` gives each state column its vocabulary and its `CHECK` constraint
  (`enum_check("state", IdentityState)` becomes `ck_identities_state`).
- **Repositories** are narrow and explicit: `add`, `get`, atomic `claim_next`, guarded `transition`. They **join the
  caller's transaction and never commit**. Every change is a **guarded `UPDATE` evaluated by the database**, never
  a decision made on a cached object, so two writers cannot both win. `JobRepository.claim_next` is one
  `UPDATE ... RETURNING` whose row is chosen by a subquery, so choosing and transitioning cannot be separated by
  another writer.
- `get(...)` uses `populate_existing=True`: "the row as the database has it now, not as this session last saw it".
  After an `optimistic_locked_update` (which sets `revision = revision + 1` in SQL) do not trust an in-memory
  copy; re-fetch.

## 4. Try it

**Works with no models. Verified 2026-10-12.** Use a **copy** of a library made with the backup API
([lesson 02](02-sqlite-and-wal.md)): `~/faceidentify-play/copy.db`. Paste as one block:

```python
from pathlib import Path
from sqlalchemy import select, func
from sqlalchemy.orm import Session
import backend.app.models                              # registers every table (needed once)
from backend.infrastructure.db.engine import create_sqlite_engine
from backend.infrastructure.db.optimistic import optimistic_locked_update
from backend.app.identities.models import Identity
from backend.app.jobs.models import Job
from backend.app.jobs.repository import JobRepository

engine = create_sqlite_engine(Path.home() / "faceidentify-play/copy.db")
with Session(engine) as s:
    ident = s.scalars(select(Identity).where(Identity.state == "ACTIVE")).first()
    print(type(ident.id).__name__, ident.state, ident.revision, ident.created_at.tzinfo)
    job = s.scalars(select(Job)).first()
    print(JobRepository(s).get(job.id).state, JobRepository(s).get(job.id).priority_rank)
    print([tuple(r) for r in s.execute(select(Identity.state, func.count()).group_by(Identity.state))])
    stale = optimistic_locked_update(s, Identity, ident.id, expected_revision=ident.revision + 7,
                                     values={"state": "ACTIVE"})
    right = optimistic_locked_update(s, Identity, ident.id, expected_revision=ident.revision,
                                     values={"state": "ACTIVE"})
    print("rows updated with a stale revision:", stale, "| with the right one:", right)
    s.rollback()
```

Expected (observed): `UUID ACTIVE 8 UTC` (a real `uuid.UUID`, a state string, a revision, and a timezone-aware
time), `COMPLETED 0` (a finished job and its rank 0 = `INTERACTIVE`), `[('ACTIVE', 2)]`, and finally
`rows updated with a stale revision: 0 | with the right one: 1`. The stale update matched nothing: that is how a
revision conflict is detected, and the caller decides what a `0` means. `s.rollback()` throws the change away;
you edited only a copy anyway.

## 5. Change it

Add a query, not a column. In the same session, write the "how many representations does each identity hold?"
query: `select(Representation.identity_id, func.count()).group_by(Representation.identity_id)`
(`Representation` is in `backend/app/memory/models.py`). To make it a permanent part of the code it belongs in
a repository or a use case in `backend/app/`, with a test using the real database fixtures
(`tests/fixtures/persistence.py`, the `build` factory in `tests/factories/models.py`). Look at
`tests/integration/test_memory_repositories.py` for the style: build rows with `build.identity()`, call the
repository, assert. Run `uv run pytest tests/integration/test_job_repository.py -q` as a model of a complete
repository test file.

## 6. Break it on purpose

Give the time column a time without a timezone, in the same session:

```python
>>> from datetime import datetime, UTC
>>> from backend.infrastructure.db.types import UTCDateTime
>>> UTCDateTime().process_bind_param(datetime(2026, 1, 1), None)
ValueError: naive datetime: all timestamps must be timezone-aware UTC
>>> UTCDateTime().process_bind_param(datetime(2026, 1, 1, tzinfo=UTC), None)
datetime.datetime(2026, 1, 1, 0, 0)
```

The column type refuses to guess a timezone, and stores aware times as naive UTC. A mistyped column is a plain
Python error: `Identity.statee` raises `AttributeError: type object 'Identity' has no attribute 'statee'` (both
observed 2026-10-12). Models are registered by importing them, which is why `backend/app/models.py` imports every
one: code that needs the whole schema imports that module first.

## 7. Exercises

1. What does `session.flush()` do that `session.commit()` does not?
2. Why do repositories never commit?
3. What does `optimistic_locked_update` return, and what should the caller do when it is 0?
4. Which helper gives a model its UUID primary key, and how is the UUID stored in SQLite?
5. Where would you look to see every column of `representations`?

**Answers**

1. `flush` sends the pending changes to the database inside the open transaction (constraints are checked now);
   it does not make them permanent.
2. The unit of work owns the transaction, so retry and atomicity work across several repository calls.
3. The number of rows updated (0 or 1). On 0 the row is missing, the revision is stale, or an extra condition did
   not hold; the caller reports the right conflict.
4. `uuid_pk()`; as `CHAR(32)` text.
5. `backend/app/memory/models.py`, class `Representation`; or `PRAGMA table_info(representations)` on a real database.

## 8. Related files

- Previous: [04 Migrations](04-migrations-alembic.md) · Next: [06 The vector index and the outbox](06-vector-index-and-outbox.md)
- [`backend/app/jobs/repository.py`](../../../backend/app/jobs/repository.py), [`backend/infrastructure/db/types.py`](../../../backend/infrastructure/db/types.py)
- [`docs/specs/PERSISTENCE_IMPLEMENTATION.md`](../../specs/PERSISTENCE_IMPLEMENTATION.md) section 26
- Further reading: the SQLAlchemy 2.0 tutorial
