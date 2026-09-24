# M2: SQLite WAL behaviour and optimistic concurrency

- **Date:** 2026-09-24
- **Milestone / tracker IDs:** M2 (TST-021, TST-024)
- **Status:** done
- **Commits:** PR #12: `test(persistence): add sqlite wal and single-writer behaviour tests`,
  `test(concurrency): add optimistic concurrency tests`, `docs: record m2 wal and concurrency`

## What changed

Tests only; no production code changed.

- `tests/integration/test_sqlite_wal_behaviour.py` (4 tests, TST-021): the database file itself is
  in WAL mode (a plain `sqlite3` connection with none of our pragmas sees `wal`); a reader is not
  blocked by an open write transaction and sees only committed state; a second writer is refused
  with `database is locked` while the first holds the write lock; and a transaction that has
  already read fails **immediately** if another writer commits before it writes (`BUSY_SNAPSHOT`),
  ignoring a generous `busy_timeout`.
- `tests/concurrency/test_optimistic_concurrency.py` (19 tests, TST-024): with separate sessions, a
  stale rename, activation and merge are rejected and change nothing; with threads released
  together by a barrier (5 rounds each), simultaneous renames (6 writers), activations (4) and merges
  of one shared loser into two different survivors each land exactly once, completely (revision
  bumped once, all representations in one place, one lineage row, one `IDENTITY_MERGED` evidence
  row). One more test checks that the shared clock/id sources are thread-safe, so the races cannot
  pass because two writers drew the same id.

## Why

TST-021 ("WAL and required constraints verified") and TST-024 ("Stale semantic updates are
handled"). The pragma *values* and the constraints were already asserted (M0/M1); what was missing
was the **behaviour** the backend leans on. Code comments in PR #7 and #8 justify plain
`revision += 1` and select-then-update pairs with "SQLite's single-writer model", and until now no
test pinned that model. `PERSISTENCE_IMPLEMENTATION.md` §25: "WAL permits readers during normal
writes; it does not permit multiple writers to hold long transactions."

## Decisions

- **The tests state SQLite's real behaviour, including the awkward part.** A transaction that reads
  and then writes fails at once, with `database is locked`, if another connection committed in
  between — waiting does not help. Merge, split and assignment all read first. So the loser of a
  simultaneous merge gets a raw `OperationalError`, not a domain error, and the merge race test
  accepts either (`IdentityManagerError | OperationalError`) while insisting that exactly one merge
  lands completely. The rename and activation races, whose first statement is the guarded `UPDATE`,
  are asserted stricter: every loser must be a `StaleRevisionError`.
- **No retry/`BEGIN IMMEDIATE` was implemented.** Persistence §25 requires bounded retry of transient
  write conflicts and a retryable error, and nothing does that today. Building it would be a new
  feature (and a unit-of-work design) rather than a test, so it is recorded with a recommendation as
  CONTEXT open question 20 for you to decide.
- **Timeouts are shortened per connection (`PRAGMA busy_timeout = 50`) in the refusal test** so it
  takes milliseconds, and set generously (5000) in the `BUSY_SNAPSHOT` test so it *proves* nothing
  is waited (it asserts the failure arrives in under 2 s).
- **Threads, not processes.** Each writer has its own session and its own pooled connection to the
  same file, which is what SQLite's locking cares about. One `SeededUUIDs`/`FrozenClock` is shared
  across writers by design; a test proves its ids stay unique under 6 threads.
- **Only Person and Identity are covered for TST-024** because they are the only aggregates with
  revision-guarded use cases so far (jobs, runs, sources arrive with later milestones).
- A raw `sqlite3.connect` must be wrapped in `contextlib.closing`: its `with` block commits but does
  not close, and Windows then cannot delete the database file at teardown (the first version of the
  WAL test errored on exactly that).

## Verification

- `HYPOTHESIS_PROFILE=ci uv run pytest --cov --cov-report=term-missing -q`: 272 passed (23 new, no
  regressions in the prior 249); `backend/` coverage 100%; strict mypy and ruff clean.
- **Stability:** the new tests were run 25 times in a row: 0 failures.
- Mutation checks against the real helper `backend/infrastructure/db/optimistic.py` (each reverted,
  restore confirmed byte-identical via `diff`):
  - dropping only the `revision = :expected_revision` condition → 6 tests fail (the stale-rename
    test and all 5 rounds of the rename race). Activation and merge are *not* caught by this alone:
    their `state` conditions independently stop a second writer, so for those the revision guard is
    a second layer, and the rename race is the test that isolates it;
  - dropping every condition from the helper → 12 fail (renames and activations, all rounds);
  - dropping every condition **and** merge's own "loser is ACTIVE" check → the merge race fails in
    all 5 rounds, on each of 3 repeated runs. (With only the helper's conditions removed the merge
    race still passes, because SQLite's own `BUSY_SNAPSHOT` refusal and the Python check cover it —
    three layers.)
  - The WAL tests assert facts about SQLite rather than about our code, so there is nothing in this
    repository to mutate for them. (The engine's pragma values, which would change the outcome,
    are asserted by `test_production_pragmas_are_applied`; that assertion was not re-mutated here.)

## Independent review

Not yet run at the time of writing this entry; see the PR for the outcome.

## Open issues / follow-ups

- CONTEXT open question 20: `SQLITE_BUSY` handling (retry, `BEGIN IMMEDIATE`, error mapping).
- Next in M2: TST-023, use-case transaction rollback (the caller owns the transaction, so a failure
  midway through merge/split/assignment must leave nothing behind).
