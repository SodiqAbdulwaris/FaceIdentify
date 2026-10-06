# M4 W2.1: revision 0007, the integer job priority rank

- **Date:** 2026-10-07
- **Milestone / tracker IDs:** M4 W2 · TST-032 (migrations), TST-060 (claim order)
- **Status:** done
- **Commits:** PR (this change): `feat(db): add the integer job priority rank (revision 0007)`

## What changed

- Revision `0007`: `jobs.priority_rank INTEGER NOT NULL` (INTERACTIVE 0, HIGH 1, NORMAL 2, LOW 3,
  MAINTENANCE 4), backfilled from the string in the upgrade; a CHECK
  (`ck_jobs_priority_rank_matches_priority`, a `CASE` over the string) keeps rank and string in agreement; the claim index is now
  `(state, priority_rank, created_at)` instead of `(state, priority, created_at)`. The upgrade adds
  the column with SQLite's native `ALTER`, fills it, then recreates the table so the temporary
  default is gone. Downgrade (guarded, development only) restores the old shape and index.
- `Job.priority_rank` derives from `priority` when a row is created (an unknown priority gets no
  valid rank, so the database still refuses it with `ck_jobs_priority`); `PRIORITY_RANK` lives in
  `backend/app/jobs/models.py`.
- `JobRepository.claim_next` orders by `priority_rank, created_at, id` (the alphabetical `CASE`
  workaround is gone).

## Why

CONTEXT question 14, decided by the owner 2026-10-06: an integer rank, before the scheduler loop;
the string is never scheduling semantics. Persistence section 15 carries the dated note.

## Decisions

None new. The `priority` string stays (it is the API-facing descriptive value, Persistence section 15).

## Verification

- Full gate (2026-10-07): ruff format/check and native/Linux mypy pass; `HYPOTHESIS_PROFILE=ci uv run
  pytest --cov -q -p no:cacheprovider` — **2,395 passed in 436.64s, 100% line and branch coverage**.
  The first full run found three expectations to update, not defects: the head-revision pin in
  `test_library_lifecycle.py`, the required-index list in `test_schema_contract.py` (now
  `(state, priority_rank, created_at)`, with a dated note in Persistence section 21), and a CHECK that
  named the wrong constraint for an unknown priority (the rank CHECK now leaves an unknown priority
  to `ck_jobs_priority`, so the value-set test still sees its own constraint).
- `tests/integration/test_migration_0007.py` (6): a populated 0006 library upgrades with every job
  kept and ranked from its string, the claim index and the old index, the CHECK and a refused row
  with no rank, downgrade restores the old columns, rows and index, a populated downgrade is refused
  without the override, and the revision prints as SQL. `test_job_repository.py` gained a test that
  claiming follows the rank, not the alphabetical order. Three of four guard mutations were caught
  (claiming by the string, a wrong backfill order, a wrong model mapping); the fourth pattern did not
  match the code and was not run.
- The head-revision pins in `test_migrations.py` moved to `0007`.

## Open issues / follow-ups

W2 continues: the scheduler loop (claim, execute, accept, index wake) and the ML supervisor wiring.
