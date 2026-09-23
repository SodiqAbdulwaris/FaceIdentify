# FaceIdentify — Testing Guide

How to run and extend the test suite. The strategy lives in [`TESTING_STRATEGY.md`](../strategy/TESTING_STRATEGY.md); progress in
[`TESTING_IMPLEMENTATION_TRACKER.md`](../plans/TESTING_IMPLEMENTATION_TRACKER.md).

## Setup

Python dependencies are managed with [uv](https://docs.astral.sh/uv/) from `pyproject.toml` /
`uv.lock`. Python 3.12 is pinned in `.python-version`.

```bash
uv sync
```

This installs runtime dependencies (SQLAlchemy 2, USearch) and the `dev` group (pytest,
pytest-asyncio, pytest-cov, HTTPX, Hypothesis, ruff, mypy, numpy). No GPU, CUDA, datasets or
desktop session are needed.

JavaScript dependencies use npm workspaces from the root `package.json` (Node version in
`.nvmrc`):

```bash
npm install
```

## Running tests

| Goal | Command |
|---|---|
| All fast tests (default) | `uv run pytest` |
| One category | `uv run pytest -m unit` (or `contract`, `property`, `integration`, `recovery`, `security`, `concurrency`) |
| Everything except integration | `uv run pytest -m "not integration"` |
| Integration tests only | `uv run pytest -m integration` |
| End-to-end / hardware (explicit only) | `uv run pytest -m e2e`, `uv run pytest -m hardware` |
| ML evaluation (explicit only) | `uv run pytest evaluation -m ml_eval` |
| Benchmarks (explicit only) | `uv run pytest benchmarks -m benchmark` |
| Coverage report | `uv run pytest --cov --cov-report=term-missing --cov-report=html` → `htmlcov/index.html` |
| Deterministic Hypothesis (as CI) | set `HYPOTHESIS_PROFILE=ci`, then `uv run pytest` |

The default run excludes `e2e`, `ml_eval`, `benchmark` and `hardware` through `addopts` in
`pyproject.toml`. Passing `-m` on the command line replaces that filter. `testpaths` is only
`tests/`, so `evaluation/` and `benchmarks/` must also be named as paths, as in the table.

Markers come from the directory: every test under `tests/unit/` gets `unit`,
`tests/integration/` gets `integration`, `tests/contracts/` gets `contract`, and so on (see `DIRECTORY_MARKERS` in
`tests/conftest.py`). Mark tests explicitly only for cross-cutting markers such as `hardware`.
Benchmarks live in `benchmarks/` and ML quality evaluation in `evaluation/`
(IMPLEMENTATION_ARCHITECTURE.md §24). Neither is under `testpaths`, so run them explicitly, e.g.
`uv run pytest evaluation -m ml_eval`, and mark every test in them `benchmark` or `ml_eval`.
Evaluation datasets never go in Git: `evaluation/datasets/` is ignored, and results must not
include biometric data (TESTING_STRATEGY.md §12).

Warnings are errors (`filterwarnings = ["error"]`), and markers are strict. A misspelled marker
or a new deprecation fails the run instead of scrolling past.

## Frontend tests

Vitest + React Testing Library + jsdom, configured in `frontend/vite.config.ts` (`test` block).
Global setup is in `frontend/src/test/setup.ts` (jest-dom matchers and automatic cleanup). Tests
sit next to their component as `*.test.tsx` and import through the `@/` alias.

| Goal | Command (from the repo root) |
|---|---|
| Run tests once | `npm test` |
| Watch mode | `npm exec --workspace frontend vitest` |
| Type check | `npm run typecheck` |
| Lint | `npm run lint` |

Query by role or label (`screen.getByRole`) and assert what the user sees. Do not rely on
snapshots of UI primitives (TESTING_STRATEGY.md §10.3). `src/components/ui/` is shadcn-generated
code; test the features that use it, not the primitives.

## Running the CI checks locally

```bash
uv sync --locked
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest --cov --cov-report=xml --cov-report=html
npm ci
npm run typecheck && npm run lint -- --deny-warnings && npm test && npm run build
sh .githooks/commit-msg <file-containing-a-commit-message>
sh .githooks/check-branch-name "$(git branch --show-current)"
```

## Available fixtures

Registered in `tests/conftest.py` via `pytest_plugins`. They are available to every test.

| Fixture | Source | Provides |
|---|---|---|
| `sandbox_user_data` | `conftest.py` (session, autouse) | `LOCALAPPDATA`, `APPDATA`, `USERPROFILE`, `HOME` redirected to a temp dir for the whole run |
| `app_dirs` | `fixtures/persistence.py` | `AppDirs` with `library_root`, `local_state`, `database_path`, `indexes`, `temp`, `logs` under `tmp_path` |
| `sqlite_engine` | `fixtures/persistence.py` | Real file-backed SQLite from the production `create_sqlite_engine` (WAL + all Persistence §25 pragmas). Schema from `Base.metadata`. Teardown deletes DB/WAL/SHM, so a leaked connection fails the test on Windows. |
| `db_session` | `fixtures/persistence.py` | Session from the production `create_session_factory`, rolled back on teardown |
| `make_usearch_index` | `fixtures/persistence.py` | `make(ndim, name=..., metric="cos")` → real `usearch.index.Index` saved under `app_dirs.indexes`, reset on teardown |
| `clock` | `fixtures/deterministic.py` | `FrozenClock`: call for UTC `now`, `.advance(seconds=...)` |
| `new_id` | `fixtures/deterministic.py` | `SeededUUIDs`: call for reproducible version-4 UUIDs |
| `rng`, `np_rng` | `fixtures/deterministic.py` | Seeded `random.Random` and `numpy.random.Generator` |

### Adding fixtures

- Put reusable fixtures in `tests/fixtures/<topic>.py` and add the module to `pytest_plugins`
  in `tests/conftest.py`. Keep suite-specific fixtures in that suite's own `conftest.py`.
- Anything that touches disk must derive its paths from `tmp_path` / `app_dirs` and go through
  `_require_inside(path, tmp_path)`.
- Fixtures that allocate OS resources (connections, indexes, subprocesses) must release them on
  teardown.
- Hypothesis `@given` tests cannot use function-scoped fixtures. Construct helpers such as
  `FrozenClock()` inside the test instead.

### Model factories (`build`)

`tests/factories/models.py` provides `ModelFactory`, exposed as the `build` fixture. Each method
returns a valid, flushed row with ids from `new_id` and timestamps from `clock`, and creates
missing parents on demand:

```python
def test_example(build: ModelFactory) -> None:
    run = build.run()
    face = build.observation(run)                     # shares the run's segment, next sequence
    rep = build.representation(face, state="ACTIVE", identity_id=build.identity().id, ann_key=1)
```

- Override any column with a keyword. Passing `parent_id=None` explicitly is kept as `None`,
  so NOT NULL rules can be tested; omitting it creates a parent.
- Builders cover: `artifact`, `source`, `snapshot`, `run`, `segment`, `checkpoint`, `job`,
  `component_version`, `representation_space`, `observation`, `representation`, `occurrence`,
  `identity`, `evidence`, `lineage`, `index_operation`, `person`, `association`. Link rows
  (`evidence_representations`, `evidence_candidates`, `occurrence_observations`,
  `ann_key_sequences`) and runtime-catalog rows are built inline with `build.add(Model(...))`.
- Add a builder when two or more tests need the same row shape.

### Asserting constraint failures

Use `tests/fixtures/constraints.py`: `rejected(session, make, check("ck_<table>_<name>"))` or
`unique("table.col", ...)`. `rejected` runs `make()` inside a SAVEPOINT, so rows created
earlier in the test survive. Do the whole failing mutation inside `make()`: a change made
before calling `rejected` is flushed *outside* the savepoint.

## Writing deterministic tests

- Inject time and identity: production code should accept `clock: Callable[[], datetime]`
  and `new_id: Callable[[], UUID]`. Tests pass `clock` / `new_id`. Never assert against real
  `datetime.now()`.
- Draw randomness from `rng` / `np_rng` (seed `DEFAULT_SEED`), never from global `random` or
  `np.random`.
- Change environment variables and settings only through `monkeypatch`, which restores them
  after each test.
- Coordinate concurrency with events/barriers, not `sleep`.
- A test must pass alone, in any order, and in parallel with others. It must not depend on
  state left by another test.

## Test-data safety

The suite cannot reach a real library. User-data environment variables point at a sandbox,
every database and index path is checked against `tmp_path`, and
`tests/security/test_test_data_isolation.py` (SEC-001) verifies both. Passing tests' temp
dirs are deleted (`tmp_path_retention_policy = "failed"`). Never commit real biometric data as
test fixtures.
