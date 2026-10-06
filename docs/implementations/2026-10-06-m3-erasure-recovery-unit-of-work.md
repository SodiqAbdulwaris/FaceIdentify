# M3.1: the eraser and recovery writes on the UnitOfWork

- **Date:** 2026-10-06
- **Milestone / tracker IDs:** M3.1 · TST-023, TST-030, TST-031 · issue #66
- **Status:** done for the eraser and `startup.py`; the artifact-settlement functions are left on
  plain sessions by design (see Decisions)
- **Commits:** PR (this change): `refactor(memory): use the unit of work in erasure and recovery`

## What changed

- `RepresentationEraser` takes a required `unit_of_work`. Its three write transactions (queueing
  the erasure, clearing the vector and key, clearing the WAL-truncation marker) are now
  `UnitOfWork.write` calls, each a function of its session only, so a whole-transaction retry after
  `SQLITE_BUSY` is safe. Reads still use the session factory.
- `startup.py`: `interrupt_in_flight_work` and the `NOT_RESUMABLE` marking take the `UnitOfWork`;
  `accept_finalizing_runs` reads through it; `recover_on_startup` takes `unit_of_work`.
  `open_library` passes the shared one.
- Tests: a `uow_for(factory)` helper (`tests/fixtures/persistence.py`); retry-safety tests that run
  each write once rolled back and then for real (eraser end to end; recovery's writes; the
  interruption on its own).

## Why

Deferred transactions that read before writing fail with `SQLITE_BUSY_SNAPSHOT` instead of queueing
(CONTEXT question 20). The coordinator moved in PR #105; this finishes the writers that M4's
concurrent scheduler and API will contend with.

## Decisions

Scope: the `sources` functions `recover_artifacts`, `mark_missing_managed_files` and
`mark_missing_referenced_originals` stay on plain sessions. They interleave file effects with short
transactions (so a whole-transaction retry is not a drop-in change) and run during startup, before
any other writer exists. Issue #66 is updated with this remainder. Say if you want them converted too.

## Verification

- Full gate (2026-10-06): ruff format/check and native/Linux mypy pass; `HYPOTHESIS_PROFILE=ci uv
  run pytest --cov -q -p no:cacheprovider` — **2,354 passed in 242.20s, 100% coverage**.
- Mutations (restored byte-identically): queueing, the WAL-marker clear or the interruption
  bypassing the unit of work, and the clearing write keeping state across attempts, each make a new
  test fail. One probe first survived (the interruption bypass) because other writes satisfied the
  attempt count; a direct test of the interruption closed that.

## Open issues / follow-ups

- Issue #66 remainder: the `sources` settlement functions (above).
- Next in the plan: M3.2 real-process crash tests of the pipeline.
