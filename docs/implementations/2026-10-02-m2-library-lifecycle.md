# M2: the library lifecycle (`open_library`) and real process-kill tests

- **Date:** 2026-10-02
- **Milestone / tracker IDs:** M2 · TST-030; GitHub issues #33 and #39 (Q23, validated here)
- **Status:** done, except the FastAPI lifespan that wraps it (no web app exists yet)
- **Commits:** PR (branch `feat/library-lifecycle`): `feat(app): open a library in the spec's startup order`, `test(recovery): kill real backend processes mid-operation`, `docs: record the library lifecycle`

## What changed

- `backend/app/lifecycle.py`: `open_library(library_root, local_state_root, clock, new_id, retry, index_batch,
  max_index_passes)`, a context manager. In order: validate the roots (`validate_library_root`, `validate_distinct_roots`:
  nothing is created for a typo or nested roots) -> **take the library lock** -> create the layout (idempotent) -> migrate to
  `head` -> build the engine, Storage Manager, workspaces, IndexCoordinator and eraser -> `recover_on_startup`. The caller
  gets an `OpenLibrary` (roots, engine, session factory, store, workspaces, coordinator, eraser and the `StartupReport`).
  Leaving the block, or a failure at any step, disposes the engine and then releases the lock (an `ExitStack`).
- `migrate(database_path)` refuses a database stamped with a revision this application does not have
  (`DatabaseNewerThanApplicationError`, persistence section 27 rule 3) before touching it. Alembic is configured in code
  (`script_location`, the database path), not from `alembic.ini`, so a packaged application does not depend on that file.
- No threshold has a default: the retry policy and the two index catch-up limits are the caller's, like
  `recover_on_startup`; the clock and the id source are injected.
- `tests/fixtures/processes.py`: `start_until` (run a script, wait for a line, with a start-up timeout and cleanup on any
  failure), `kill_tree` (the Windows launcher/child tree), `close_streams`; the lock tests use it too.
- `tests/integration/test_library_lifecycle.py` (13) and `tests/recovery/test_process_kill.py` (4).

## Why

Startup recovery existed and was tested in process but nothing called it (issue 33). Persistence section 28 gives the order, the
owner's decisions (2026-10-01) put the lock before migrations and recovery, and architecture 25.13 asks for tests that terminate
real processes.

## Decisions

- The lifecycle is framework-free (a context manager): the FastAPI lifespan is a three-line wrapper when the app exists, and
  adding FastAPI now would have been a dependency without a use.
- Layout creation comes after the lock (and creates the local state folders too), before the migration: the database folder
  must exist for SQLite.
- The kill tests run the child with the real wall clock; the parent's frozen test clock is advanced past it before the
  next start, otherwise the child's work is not yet "due".
- Not covered by a kill test: a kill in the middle of a migration (each revision is its own transaction and that is tested in
  `test_migration_*`), and a kill between two steps of the erasure (each step is tested in process: PER-07).

## Verification

- `ruff format --check`, `ruff check`, `mypy`, `mypy --platform linux` clean; `HYPOTHESIS_PROFILE=ci pytest --cov -q`: 1144 passed, backend coverage 100%.
  14 mutations (the validations, the lock first, migrate before layout, the engine disposal, the newer-database refusal,
  the unstamped database, recovery called, the index folder, and the recovery steps the kill tests rely on), each broken, shown
  to fail a test and restored byte-identical; the kill tests ran 5 times without a failure.
- **Not verified:** a kill on a network share or removable drive; a non-Windows platform.

## Open issues / follow-ups

- The FastAPI lifespan (with the app, M4) and the shell's persisted library setting.
- Issue #34: recovery that needs the M3 run lifecycle.
