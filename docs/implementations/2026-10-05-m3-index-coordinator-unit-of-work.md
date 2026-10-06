# M3: IndexCoordinator write transactions use the UnitOfWork

- **Date:** 2026-10-05
- **Milestone / tracker IDs:** M3 step 11 · TST-028 · issue #66 (narrow coordinator slice)
- **Status:** done; merged in PR #105
- **Commits:** `83a51fe` (PR #105)

## What changed

`IndexCoordinator` now receives the library's shared `UnitOfWork`.  Its two write paths, failed-operation requeue and operation settlement, read their current database state and write their transition inside one `BEGIN IMMEDIATE` whole-transaction retry boundary.  The lifecycle constructs that UnitOfWork once and supplies the same instance to both `OpenLibrary` and the coordinator.

Settlement returns its committed outcome lists from the retry callback and updates the caller-visible report only after the UnitOfWork succeeds.  A rolled-back attempt therefore cannot duplicate `applied`, `failed`, or `retrying` report entries.  The existing race test now settles an operation through a competing SQLite session before the coordinator's retried transaction and proves the coordinator does not resurrect it.

Read-only coordinator work continues to use the ordinary session factory.  Representation erasure and startup recovery are deliberately unchanged: issue #66 limits this M3 slice to the writer that will contend with acceptance.

## Why

M3 acceptance will atomically activate representations and append index operations through `UnitOfWork`.  Leaving the coordinator's write paths on deferred SQLite transactions would retain a reader-then-writer `SQLITE_BUSY_SNAPSHOT` window at that boundary.  The change follows the owner-approved issue #66 scope without broadening UnitOfWork adoption to unrelated services.

## Decisions

- **2026-10-05:** UnitOfWork retries receive only session-dependent work.  Clock time is captured before entering the retry callback, and report mutation happens only after the successful attempt.
- No new conditional guard was added.  The pre-existing settlement/requeue race guards remain observable through TST-028.  The new retry-report boundary was mutation-probed by duplicating its applied entries; the retry test failed, then the exact source bytes were restored.

## Verification

- `uv run ruff format --check .` — 201 files already formatted.
- `uv run ruff check .` — all checks passed.
- `uv run mypy` — success, 201 source files.
- `uv run mypy --platform linux` — success, 201 source files.
- `HYPOTHESIS_PROFILE=ci uv run pytest --cov -q -p no:cacheprovider` — 2169 passed, 100% coverage.
- Targeted coordinator, erasure, and recovery suites — 193 passed.
- Mutation probe: duplicate a settled `applied` report entry — `test_settlement_report_contains_only_the_committed_unit_of_work_attempt` failed; source SHA-256 was restored byte-identically.

## Open issues / follow-ups

- Issue #66 remains open for its intentionally deferred eraser and recovery write paths; only the acceptance-contending IndexCoordinator writer is in this slice.
- PR #106 resolved the accepted-`ABSTAIN` evidence-kind boundary (`RECOGNITION_ABSTAINED`) and closed issue #104; this does not alter the coordinator work.
