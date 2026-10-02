# M2: the write unit of work (`BEGIN IMMEDIATE` and whole-transaction retry)

Date: 2026-10-02. Issue: 37 (CONTEXT open question 20). Owner direction 2026-10-01, finalised for item 3 of the build order.

## What was built

- `backend/infrastructure/db/engine.py`: the `sqlite_begin_immediate` execution option. The begin hook sends `BEGIN IMMEDIATE`
  when it is set, plain `BEGIN` otherwise, and nothing under `AUTOCOMMIT`.
- `backend/infrastructure/db/unit_of_work.py`:
  - `UnitOfWork(engine, retry=TransactionRetry(max_attempts, backoff))` with `read(work)` (deferred, always rolled back) and
    `write(work)` (`BEGIN IMMEDIATE`, commit).
  - A busy or locked database anywhere in a write (begin, `work`, commit) rolls the **whole** transaction back and runs `work`
    again, up to `max_attempts`; the last failure is `DatabaseBusyError` (chained from the SQLAlchemy error), which the API
    layer will map to a retryable error. Anything else (I/O error, constraint, a domain error) rolls back and propagates at once.
  - `is_busy` decides by the SQLite result code of a real `sqlite3.OperationalError` (`code & 0xFF` in `SQLITE_BUSY`,
    `SQLITE_LOCKED`, so the snapshot and recovery variants count), never by message text.
- `backend/app/lifecycle.py`: `open_library` takes `transaction_retry` and exposes `OpenLibrary.unit_of_work`.
- Neither the attempts nor the back-off has a default (an unmeasured threshold); `sleep` is injected.

## Decisions and consequences

- The work function runs again from the start on a retry, so it must depend on the session only. Sending, writing a file or
  spawning belongs after `write` returns, or must be idempotent. This is in the module docstring.
- A reader takes no lock, so reads stay deferred.
- Nothing is changed in the schema.
- The existing services are **not** moved onto it yet (issue 66); `work` must not commit itself.
- Review (Explore subagent), no blocker. Fixed: the commit-time retry now has a test; the no-commit rule is documented; the
  "built" wording no longer overstates. Noted, not changed: `SQLITE_LOCKED` is retried like busy (as agreed); `read` discards
  writes by design; the pooled-connection isolation reset after AUTOCOMMIT use is pre-existing (issue 67).

## Verification

`tests/integration/test_unit_of_work.py` (26): the statement sent (`BEGIN IMMEDIATE` vs `BEGIN`), commit and rollback, two
threads contending (the second queues behind the first and sees its write, no sleep), the retry sequence and back-off,
exhaustion, an I/O error not retried, a really locked database with `busy_timeout = 0`, and `is_busy` for each code, a plain
`RuntimeError` carrying a busy code, and an `IntegrityError`. Mutation-checked (15 mutants killed), 5 repeated runs. The
lifecycle tests check that an opened library hands out a working unit of work.
