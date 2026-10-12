# Data 03 Transactions, the unit of work and optimistic concurrency

## 1. What this is and why it exists

A **transaction** is a group of database changes that succeed or fail *together*, like a bank transfer where
the debit and credit must both happen or neither. Merging two identities moves their representations and
occurrences, writes evidence and a lineage edge and bumps revisions; if the program died halfway you would have
a corrupted memory. So the whole merge is one transaction. This lesson explains the guarantees (**ACID**), the
project's wrapper (**`UnitOfWork`**), why a "write function" can run more than once, and how two people editing
the same thing are kept from overwriting each other (**optimistic concurrency**).

## 2. Where it lives

| Thing | Where |
|---|---|
| The unit of work | `UnitOfWork` in `backend/infrastructure/db/unit_of_work.py` (`read`, `write`, `TransactionRetry`, `DatabaseBusyError`) |
| `BEGIN IMMEDIATE` | the `sqlite_begin_immediate` option in `backend/infrastructure/db/engine.py` |
| Optimistic update helper | `optimistic_locked_update` in `backend/infrastructure/db/optimistic.py` |
| Tests | `tests/integration/test_unit_of_work.py`, `test_transaction_rollback.py`, `test_engine_transactions.py`, `tests/concurrency/test_optimistic_concurrency.py` |

## 3. How it works

### ACID

- **A**tomic: all or nothing. **C**onsistent: constraints always hold at commit. **I**solated: concurrent
  transactions do not see each other's half-done work. **D**urable: once committed, it survives a crash.
- `COMMIT` makes the changes permanent; `ROLLBACK` throws them away.

### BEGIN IMMEDIATE, busy errors and retry

A normal SQLite transaction starts as a reader and upgrades to a writer at its first write. If another writer
got in first, the upgrade fails at once with "database is locked", which no waiting can fix. So the project
starts every *writing* transaction with **`BEGIN IMMEDIATE`** (claim the writer slot first; others wait up to
`busy_timeout`). If the database is still busy, the **whole transaction** is rolled back and run again, a bounded
number of times (the caller's `TransactionRetry(max_attempts, backoff)`; the host uses 3 attempts), and then
reported as `DatabaseBusyError` (the API maps it to a retryable error).

> **Consequence to remember:** a "write function" may run more than once. So it must be a pure function of the
> session: read, decide, write. No sending, no moving files, no calling the worker inside it. Do such work after
> `write` returns, or make it idempotent. Events are announced *after* the commit.

```python
class UnitOfWork:
    def read(self, work):    # a read-only transaction, always rolled back
        ...
    def write(self, work):   # BEGIN IMMEDIATE ... COMMIT, retried whole on busy
        ...
```

A use case is just a function you hand to `uow.write(lambda session: ...)`. Routes do exactly that
(`library.unit_of_work.write(write)` in `backend/api/routes/people.py`).

### Optimistic concurrency: the `revision` column

Two actions can race ("rename this person" and "merge this person"). Rows a user can edit (`identities`,
`people`, `sources`) carry a `revision` integer that starts at 1. An edit says "change the row *if its revision is
still N*" and increments it; if someone else changed it first, zero rows match and the code raises a **conflict**
instead of overwriting. The API exposes `revision` and takes `expected_revision` back; a stale one is a
`409` such as `PERSON_REVISION_CONFLICT` or `IDENTITY_CHANGED` ("reload and try again").

## 4. Try it

**Works with no models. Verified 2026-10-12.**

1. **Rollback, with the project's own wrapper**, on a scratch copy (taken safely, see [lesson 02](02-sqlite-and-wal.md)):

   ```python
   from pathlib import Path
   from sqlalchemy import select
   import backend.app.models                      # registers every table
   from backend.infrastructure.db.engine import create_sqlite_engine
   from backend.infrastructure.db.unit_of_work import UnitOfWork, TransactionRetry
   from backend.app.sources.models import Source

   engine = create_sqlite_engine(Path.home() / "faceidentify-play/copy.db")
   uow = UnitOfWork(engine, retry=TransactionRetry(max_attempts=3, backoff=lambda n: 0.1))
   names = lambda s: s.scalars(select(Source.display_name).order_by(Source.created_at)).all()

   def rename(session):
       first = session.scalars(select(Source).order_by(Source.created_at)).first()
       first.display_name = "changed"
       return first.display_name

   def boom(session):
       first = session.scalars(select(Source)).first()
       first.display_name = "never saved"
       raise RuntimeError("stop")

   print(uow.write(rename))          # changed
   print(uow.read(names))            # ['changed', ...]
   try:
       uow.write(boom)
   except RuntimeError as e:
       print("RuntimeError:", e)     # RuntimeError: stop
   print(uow.read(names))            # still ['changed', ...]: boom's change was rolled back
   ```

   Observed: `changed`, then the list starting with `changed`, then `RuntimeError: stop`, then the same list: the
   second function's change vanished because it raised before the commit.
2. **See a busy writer.** Two raw connections, the first holding the write lock:

   ```python
   import sqlite3
   p = str(Path.home() / "faceidentify-play/copy.db")
   a = sqlite3.connect(p, timeout=0.2, isolation_level=None)
   b = sqlite3.connect(p, timeout=0.2, isolation_level=None)
   a.execute("BEGIN IMMEDIATE")
   try:
       b.execute("BEGIN IMMEDIATE")
   except sqlite3.OperationalError as e:
       print("second writer:", e)           # second writer: database is locked
   a.execute("ROLLBACK")
   b.execute("BEGIN IMMEDIATE"); print("after the first finishes: ok"); b.execute("ROLLBACK")
   ```

   Observed: `second writer: database is locked`, then `after the first finishes: ok`. `UnitOfWork.write` is a loop
   around exactly this, retrying a bounded number of times.
3. **A stale revision through the API** (backend running, a named person exists; see start-here lesson 07):
   `PATCH /api/v1/people/{id}` with `{"display_name":"X","expected_revision":5}` when the person is at revision 1
   returns `409 PERSON_REVISION_CONFLICT` with `"reason": "person ... is at revision 1, expected 5"` (observed).
4. Run the tests: `uv run pytest tests/integration/test_unit_of_work.py tests/integration/test_transaction_rollback.py tests/concurrency/test_optimistic_concurrency.py -q`.
   Expected: pass. Read `test_unit_of_work.py` for retry and exhaustion cases (a final failure is `DatabaseBusyError`).

## 5. Change it

The safe modification is to a use case's *transaction scope*, which you check with a rollback test. Open
`tests/integration/test_transaction_rollback.py`: it forces a failure in the middle of a use case and asserts
nothing persisted. If you add a step to a use case (say another Evidence row in `merge_identities`), you extend
the matching test to assert it is rolled back with everything else. Never add a `session.commit()` inside a
use case: the unit of work commits, and a commit inside would defeat retry and atomicity (the module docstring
of `unit_of_work.py` says so; the same file explains why the work must not open transactions of its own).

## 6. Break it on purpose

Make a "write function" do something that cannot be repeated, in a scratch session (reusing `uow` from
step 1), and force one retry by raising what SQLite raises when it is busy:

```python
import sqlite3
from sqlalchemy.exc import OperationalError

runs = []
def work(session):
    runs.append(1)                                   # the "side effect" that must not repeat
    if len(runs) == 1:
        busy = sqlite3.OperationalError("database is locked")
        busy.sqlite_errorcode = sqlite3.SQLITE_BUSY
        raise OperationalError("UPDATE ...", {}, busy)
    return session.scalars(select(Source.display_name)).first()

print(uow.write(work), "ran", len(runs), "times")   # changed ran 2 times
```

Observed: `changed ran 2 times`. **The function ran twice.** That is the lesson: only touch the session inside,
because a sent email, a moved file or a worker call inside would happen twice.

## 7. Exercises

1. What does the "I" in ACID guarantee?
2. Why `BEGIN IMMEDIATE` for writers and a deferred `BEGIN` for readers?
3. What error means "someone changed this since you looked", and how do you recover?
4. Why must the function given to `write` not commit?
5. Where do the retry limits come from, and why are there no defaults?

**Answers**

1. Concurrent transactions do not see each other's half-finished work.
2. A writer takes the write lock first so what it reads cannot be made stale before it writes; a reader never
   needs the lock.
3. A `409` with a revision-conflict code; reload the data and repeat with the new revision.
4. The wrapper retries the whole function; a commit inside would repeat work that already took effect.
5. The caller (the host passes 3 attempts and a short backoff); choosing them would be an unmeasured threshold,
   so the module ships none.

## 8. Related files

- Previous: [02 SQLite and WAL](02-sqlite-and-wal.md) · Next: [04 Migrations with Alembic](04-migrations-alembic.md)
- [`backend/infrastructure/db/unit_of_work.py`](../../../backend/infrastructure/db/unit_of_work.py)
- [`docs/specs/PERSISTENCE_IMPLEMENTATION.md`](../../specs/PERSISTENCE_IMPLEMENTATION.md) section 25
- [Revisions and states](../03-backend/domain/07-states-revisions-provenance.md)
