# M2: use-case transaction rollback

- **Date:** 2026-09-25
- **Milestone / tracker IDs:** M2 (TST-023)
- **Status:** done
- **Commits:** PR #13: `test(persistence): prove use cases roll back cleanly at every statement`,
  `docs: record m2 use-case transaction rollback`

## What changed

Tests only; no production code changed.

`tests/integration/test_transaction_rollback.py` (15 tests):

- **Fault at every statement** (7 cases): for each multi-row use case (assign a representation,
  activate, merge, split, correct a Person link, remove a Person link, rename), a dry run counts every
  SQL statement it sends; the use case is then re-run once per statement with an `InjectedFault`
  raised in place of exactly that statement (via SQLAlchemy's `before_cursor_execute` event). After
  each failure the caller rolls back, then **commits the same session**, and every row of every table
  must be identical to before. 49 fault points in total, 26 of them on `INSERT`/`UPDATE`. Each case
  finishes by running the use case unfaulted and committing, to prove the faults were injected into a
  path that genuinely succeeds and writes.
- **Closing without committing** (7 cases): a successful use case whose session is simply closed
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
  carries on committing other work is the realistic failure; merely inspecting after a rollback
  would not catch writes that a rollback failed to discard but a later commit would persist.
- **Rolling back also rolls back `ann_key` allocation, so a rolled-back key is handed out again.**
  `allocate_ann_key` says keys are "never reused". This is consistent with the spec, which
  deliberately allocates "in the same short transaction that creates representations" (§6.3): a
  rolled-back key was never committed to any row, and USearch only ever sees keys after commit
  (INDEX-01). "Never reused" protects keys that were committed and later erased or crashed on. The
  full-state comparison pins the sequence's rollback.
- **No production unit-of-work helper was added.** The spec's scoped session context managers
  (§24) belong with the API/background-operation layer; the tests use a session per operation
  exactly as that layer will.
- One arrangement pitfall found while writing the tests: the model factory sets `ann_key` directly,
  bypassing `ann_key_sequences`, so a factory-made ACTIVE representation with `ann_key=1` collides
  with the sequence's first allocation. The arrangement uses `ann_key=1000`.

## Verification

- `HYPOTHESIS_PROFILE=ci uv run pytest --cov --cov-report=term-missing -q`: 286 passed (15 new, no
  regressions in the prior 271); `backend/` coverage 100%; strict mypy and ruff clean.
- The new tests were run 10 more times in a row: 0 failures.
- `InjectedFault` propagates unwrapped through SQLAlchemy, so the tests assert that exact exception
  type (a first draft accepted any `Exception` plus a cause check; the precise version replaced it).
- Mutation checks (each reverted, restore confirmed byte-identical via `diff`): inserting a
  `session.commit()` part-way through `merge_identities` (after Person reconciliation),
  `split_identity` (after the new identity is flushed), `assign_representation_to_identity` (after
  `ann_key` allocation) and `assign_identity_to_person` (after its Evidence is flushed) — each is
  caught, by the fault-at-every-statement and the close-without-commit test for that use case (plus
  the stale-merge test for merge).
- No real defect was found: every use case already rolled back cleanly. The value is that a future
  change which commits inside a use case now fails here.

## Independent review

Not yet run at the time of writing this entry; see the PR for the outcome.

## Open issues / follow-ups

- Next in M2: TST-022 (repository contract) and TST-025 onwards (Storage Manager, artifacts, USearch,
  IndexOperation replay, cross-storage failure, startup recovery, deletion).
