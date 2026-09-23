# M0 testing foundation

- **Date:** 2026-09-23
- **Milestone / tracker IDs:** M0 · TST-001 to TST-010, SEC-001
- **Status:** done; CI green on PR #1 (tasks become `COMPLETE` when it merges)
- **Commits:** `445970c` build, `2c44b53` engine, `8bc983b` tests (on `chore/project-foundation`, PR #1)

## What changed

- `pyproject.toml`: uv project (Python ≥ 3.12, pinned 3.12 in `.python-version`). Runtime deps
  `sqlalchemy`, `usearch`. Dev group: pytest, pytest-asyncio, pytest-cov, httpx, hypothesis, ruff,
  numpy (mypy added later, see the scaffolding entry). Also configures pytest (11 strict markers,
  expensive suites deselected by default, warnings as errors, `tmp_path_retention_policy =
  "failed"`), coverage (branch, `backend/`) and ruff (Python files only).
- `backend/infrastructure/db/engine.py`: `create_sqlite_engine`, `create_session_factory`, the
  `SQLITE_PRAGMAS` connect listener and an empty `Base`, exactly as Persistence §24/§25 specify.
- `tests/conftest.py`: plugin registration, a session-wide sandbox for `LOCALAPPDATA`, `APPDATA`,
  `USERPROFILE` and `HOME`, directory→marker mapping, and Hypothesis `dev`/`ci` profiles.
- `tests/fixtures/deterministic.py`: `FrozenClock`, `SeededUUIDs` and the `clock`, `new_id`,
  `rng`, `np_rng` fixtures.
- `tests/fixtures/persistence.py`: the `AppDirs`/`app_dirs`, `sqlite_engine`, `db_session` and
  `make_usearch_index` fixtures, plus the `_require_inside` path guard.
- Smoke tests: `tests/unit/test_test_infrastructure.py` (9), `tests/integration/test_persistence_fixtures.py`
  (8), `tests/security/test_test_data_isolation.py` (2).
- `.github/workflows/ci.yml`, `.gitignore`, `docs/guides/TESTING_GUIDE.md`, tracker update.

## Why

TESTING_STRATEGY.md and TESTING_IMPLEMENTATION_TRACKER.md M0. The persistence fixtures use the
production engine factory instead of their own pragma list. Otherwise the tests would prove the
fixture's configuration rather than the application's.

## Decisions

- **uv** as the Python dependency manager. No spec names one; uv was installed and is
  `pyproject.toml`-native.
- **Synchronous** SQLAlchemy only, because Persistence §24 specifies a sync engine. There are no
  async sessions.
- **No build-system** in `pyproject.toml` yet. `backend` is imported via pytest's `pythonpath`.
  Add one when packaging (M8) needs it.
- **Env sandbox is session-scoped**, because Hypothesis rejects function-scoped fixtures in
  `@given` tests.
- **Fixture teardown deletes the DB/WAL/SHM files**, so on Windows a leaked connection fails the
  test.

## Verification

- `uv run pytest`: 19 passed, 0 skipped, 0 warnings (Windows 11, Python 3.12.14).
- `HYPOTHESIS_PROFILE=ci uv run pytest`: 19 passed.
- `-m unit` 9, `-m integration` 8, `-m security` 2, `-m benchmark` 0 selected.
- Coverage: `engine.py` 100% (17 statements, 2 branches). XML and HTML were generated.
- Mutation checks: removing the `foreign_keys` pragma failed 3 tests. A leaked connection failed
  teardown with `PermissionError [WinError 32]`.
- No `*.db`/`*.usearch` files appeared outside pytest's temp directory, and nothing was created
  in the real `%LOCALAPPDATA%`/`%APPDATA%`.
- **Remote CI (2026-09-23):** PR #1, run `35902624488`: all five jobs passed on GitHub Actions
  (backend on `windows-latest`: 19 passed; frontend: 1 passed; coverage artifact uploaded).

## Open issues / follow-ups

- Domain factories are blocked until models exist (M1/M2).
- Schema initialisation uses `create_all` until Alembic `0001_initial_schema` exists.
