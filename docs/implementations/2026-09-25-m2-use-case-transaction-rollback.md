# M2: use-case transaction rollback

- **Date:** 2026-09-25
- **Milestone / tracker IDs:** M2 (TST-023)
- **Status:** done
- **Commits:** PR #13: `test(persistence): prove use cases roll back cleanly at every statement`,
  `docs: record m2 use-case transaction rollback`

## What changed

Tests only; no production code changed.

`tests/integration/test_transaction_rollback.py` (17 tests):

- **Fault at every statement** (8 cases): for each use-case path (assign a representation as
  `IDENTITY_CREATED` and as `IDENTITY_MATCHED`, activate, merge, split, correct a Person link, remove a
  Person link, rename), a dry run counts every
  SQL statement it sends; the use case is then re-run once per statement with an `InjectedFault`
  raised in place of exactly that statement (via SQLAlchemy's `before_cursor_execute` event). After
  each failure the caller rolls back, then **commits the same session**, and every row of every table
  must be identical to before. 59 fault points in total, 32 of them on `INSERT`/`UPDATE`. Each case
  finishes by running the use case unfaulted and committing, which must send exactly the statements
  the loop covered, to prove the faults were injected into a path that genuinely succeeds and writes.
- **Closing without committing** (8 cases): a successful use case whose session is simply closed
  (no commit, no rollback) leaves nothing behind.
- **A stale merge that has already written** (1 test): `merge_identities` checks the loser's revision
  last, after moving representations, carrying over the Person link and inserting Evidence and
  lineage (recorded as known behaviour in the M1 merge/split entry); after the caller's rollback,
  none of it survives.

## Why

TST-023 ("Partial authoritative writes cannot commit"); TESTING_STRATEGY.md PER-01 ("Multi-record
authoritative domain operations must commit atomically"). Use cases flush but never commit
(PERSISTENCE_IMPLEMENTATION.md §26), so atomicity is only as good as two things: no use case commits
on its own, and a rollback discards everything a use case did, including bulk `UPDATE`s run with
`synchronize_session=False`, which bypass the ORM's own bookkeeping.

## Decisions

- **Every statement, not a few hand-picked failure points.** Hand-picked points test what the author
  thought of. Enumerating statements is cheap here (49 re-runs, about a second) and covers the reads
  and flushes in between too. Because `BEGIN` is also sent as a statement (the engine's explicit
  `BEGIN` hook), the first fault point is "the transaction could not even start".
- **The committed state is compared in full.** Every table, every row, read through a plain
  `sqlite3` connection outside SQLAlchemy, so no session cache can hide a leftover.
- **"Roll back, then commit" rather than "roll back and look".** A caller that catches an error and
  carries on committing other work is the realistic failure. After `rollback()` the connection has
  already gone back to the pool, so the commit cannot persist anything left on the connection; what
  it does catch is ORM state (pending objects) that survived the rollback and would be flushed again.
  The full-state comparison after it covers the connection side.
- **Rolling back also rolls back `ann_key` allocation, so a rolled-back key is handed out again.**
  The tests pin that behaviour (the full-state comparison includes `ann_key_sequences`). It is safe
  only while nothing sees a key before commit: USearch does not (INDEX-01), but the review pointed
  out that the planned run-local pending index (§23) could, and that §6.3 ("allocated in the same
  transaction that creates representations... never reused") disagrees with the code, which
  allocates only when a representation becomes ACTIVE. That is a pre-existing spec-vs-code
  question, so it is recorded as CONTEXT open question 21 with a recommendation, not decided here.
  The `allocate_ann_key` docstring, which said "never reused", now says committed keys are never
  reused and rolled-back ones are.
- **No production unit-of-work helper was added.** The spec's scoped session context managers
  (§24) belong with the API/background-operation layer; the tests use a session per operation
  exactly as that layer will.
- One arrangement pitfall found while writing the tests: the model factory sets `ann_key` directly,
  bypassing `ann_key_sequences`, so a factory-made ACTIVE representation with `ann_key=1` collides
  with the sequence's first allocation. (The review then showed that row wasn't needed at all, and it
  was removed.)

## Verification

- `HYPOTHESIS_PROFILE=ci uv run pytest --cov --cov-report=term-missing -q`: 288 passed (17 new, no
  regressions in the prior 271); `backend/` coverage 100%; strict mypy and ruff clean.
- The new tests were run 10 more times in a row: 0 failures.
- `InjectedFault` propagates unwrapped through SQLAlchemy, so the tests assert that exact exception
  type (a first draft accepted any `Exception` plus a cause check; the precise version replaced it).
- Mutation checks (each reverted, restore confirmed byte-identical via `diff`): inserting a
  `session.commit()` part-way through `merge_identities` (after Person reconciliation),
  `split_identity` (after the new identity is flushed), `assign_representation_to_identity` (after
  `ann_key` allocation; re-checked against both assignment cases after the review) and
  `assign_identity_to_person` (after its Evidence is flushed) — each is caught, by the fault-at-every-statement and the close-without-commit test for that use case (plus
  the stale-merge test for merge).
- No real defect was found: every use case already rolled back cleanly. The value is that a future
  change which commits inside a use case now fails here.

## Independent review (subagent, disposable worktree): approve, 5 findings addressed

The reviewer read the SQLAlchemy 2.0.54 source to check the fault mechanics and hand-counted every
statement; it could not run the tests (no environment in its worktree).

| # | Finding | Resolution |
|---|---|---|
| 1 | Medium: the `ann_key` reasoning misquoted §6.3 and relied on an unstated condition (no key seen before commit), which the planned run-local pending index (§23) could break | Doc rewritten; CONTEXT open question 21 added with a recommendation; `allocate_ann_key` docstring qualified. No behaviour changed: it is a spec-vs-code decision for the owner |
| 2 | "Roll back, then commit" was overstated: after rollback the connection is back in the pool, so the commit can only re-flush surviving ORM state | Reworded to say exactly that |
| 3 | A run sending *more* statements than the dry run would leave the extras untested | The final unfaulted run now must send exactly the dry run's statements |
| 4 | The assignment case's IDENTITY_CREATED evidence and `ann_key=1000` row were dead (MATCHED skips that check), and the CREATED branch was never fault-tested | Replaced by two cases, `assign_created` and `assign_matched`, with no dead rows |
| 5 | Nits: "multi-row" was wrong for activate/rename; tracker heading date stale | Fixed |

Confirmed by the reviewer from the source: `InjectedFault` is raised outside SQLAlchemy's DBAPI error
handling, so it is not wrapped and does not invalidate the connection; a fault on `BEGIN` is handled
by the session closing that connection; the snapshot connection is outside the listener; and the 49
statement / 26 write counts (before finding 4) matched a hand count.

## Open issues / follow-ups

- Next in M2: TST-022 (repository contract) and TST-025 onwards (Storage Manager, artifacts, USearch,
  IndexOperation replay, cross-storage failure, startup recovery, deletion).
