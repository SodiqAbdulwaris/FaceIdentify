# Tools 03 pytest

## 1. What this is and why it exists

A **test** is a function that runs your code and asserts what must be true. **pytest** finds files
named `test_*.py`, runs functions named `test_*`, and reports failures. This project has about 3,000
Python tests, and its rule is that nothing is "done" until the relevant ones pass and you have
reported the real output. Tests are also the best documentation of what the code promises: a test
name here reads as a sentence.

## 2. Where it lives

| Thing | Where |
|---|---|
| The tests | `tests/` in folders `unit/`, `contracts/`, `integration/`, `recovery/`, `property/`, `security/`, `concurrency/`, `e2e/` |
| pytest settings | `[tool.pytest.ini_options]` in `pyproject.toml` |
| Shared fixtures | `tests/conftest.py` and `tests/fixtures/*.py` (`clock`, `new_id`, `rng`, `app_dirs`, `sqlite_engine`, `db_session`, `api`, `processing_api`, ...) |
| Model factories | `tests/factories/models.py` (the `build` fixture) |
| The test guide | [`docs/guides/TESTING_GUIDE.md`](../../../TESTING_GUIDE.md) and the strategy in `docs/strategy/TESTING_STRATEGY.md` |
| What is tested, per task | `docs/plans/TESTING_IMPLEMENTATION_TRACKER.md` (rows `TST-nnn`) |

## 3. How it works

```python
def test_a_policy_with_matching_off_never_matches(...):
    decision = IdentityReasoner(OFF).decide(assess(retrieval(candidate(1, 1.0, identity=7)), GOOD))
    assert decision.outcome is RecognitionOutcome.ABSTAIN
```

Concepts you will meet:

- **Fixtures** (`@pytest.fixture`): reusable set-up. A test asks for one by naming it as a parameter.
  `tmp_path` is pytest's built-in fixture giving a fresh empty folder. `clock`, `new_id`, `rng` give a
  frozen clock, predictable ids and seeded randomness. `api` is a whole running application on a
  temporary library.
- **`@pytest.mark.parametrize`**: run one test over many inputs.
- **`pytest.raises(SomeError, match="text")`**: assert that a block raises that error.
- **`monkeypatch`**: temporarily replace something (an environment variable, a function) for one test.
- **Markers**: the *directory decides the marker* (`DIRECTORY_MARKERS` in `tests/conftest.py`):
  `unit`, `contract`, `property`, `integration`, `recovery`, `security`, `concurrency`, `e2e`. Four
  markers are **excluded by default** because they need real models, hardware or minutes: `e2e`,
  `ml_eval`, `benchmark`, `hardware` (the `-m "not (e2e or ml_eval or benchmark or hardware)"`
  default in `addopts`). Markers are `--strict-markers`, and warnings are errors
  (`filterwarnings = ["error"]`).
- **Test doubles**: fakes that stand in for slow or dangerous parts (planted perception that "sees" a
  face, a frozen clock). Dependency injection ([Python 03](../python/03-functions-and-errors.md)) makes
  them possible.
- **Real SQLite, USearch and files, never mocks, for persistence tests.** A database test runs on a real
  file migrated to the current schema.
- **Property-based tests** (`hypothesis`, in `tests/property/`): the library generates hundreds of
  random sequences of merges and splits and checks that an *invariant* always holds.
- **Safety:** the suite cannot reach a real library. User-data environment variables point at a sandbox
  and every path is checked against `tmp_path` (`tests/security/test_test_data_isolation.py`).
- **Coverage** (`--cov`): which lines and branches the tests ran. The working rule is 100% of what you
  touched; CI produces the report but enforces no number.
- **Hand mutation testing**: after writing a guard, deliberately break it and confirm a test fails (the
  exercise in [Python 07](../python/07-read-a-real-function.md)). You will see "mutations caught" in
  `docs/implementations/`.

## 4. Try it

**Works with no models. Verified 2026-10-12 on Linux.** All commands from the repository folder.

1. The fast unit tests (most of the quick feedback):

   ```bash
   uv run pytest tests/unit -q
   ```

   Expected: a row of dots, then `384 passed in 2.5s` (the count grows over time).
2. One file, then one test, then by name:

   ```bash
   uv run pytest tests/unit/test_recognition_reasoner.py -q                # 59 passed
   uv run pytest tests/unit/test_recognition_reasoner.py::test_a_clear_match_matches_the_identity_of_the_best_group -q   # 1 passed
   uv run pytest tests/unit -q -k reasoner                                  # tests whose name contains "reasoner"
   ```

3. By marker (the directory decides): `uv run pytest -m unit -q` runs the same 384;
   `uv run pytest -m "not integration" -q` skips the slower database tests. `uv run pytest --co -q
   tests/unit | tail -1` only *collects*: `384 tests collected`.
4. Coverage for one module while running its tests:

   ```bash
   uv run pytest tests/unit/test_recognition_reasoner.py --cov=backend.app.recognition.reasoner --cov-report=term-missing -q
   ```

   Expected: a table with `backend/app/recognition/reasoner.py  75 stmts  0 missed  22 branches  0 partial  100%`
   and `59 passed`. A line that appeared under `Missing` would be code no test runs. For the whole
   backend: `uv run pytest --cov --cov-report=term-missing` (on Windows; many minutes) or
   `--cov-report=html` and open `htmlcov/index.html`.
5. Useful flags: `-x` stop at the first failure; `--lf` rerun only the last failures; `-v` list each test;
   `-ra` summarise skips and failures (already on by default); `--durations=10` the slowest tests.
6. The **front-end** tests are a separate runner: `npm test` ([JavaScript and Rust tools](07-javascript-and-rust-tools.md)).
7. The **whole** suite: `uv run pytest -q`. On Windows (CI's platform) it passes; **on Linux in the
   writing sandbox it reported `37 failed, 2894 passed, 3 skipped, 2 deselected, 15 errors`** after about
   5 minutes, all Windows-specific (shared memory, file locks, process kill). Run folders you need
   instead.

## 5. Change it

Write your own test in a **scratch file** (do not commit it). Create `tests/unit/test_scratch.py`:

```python
import pytest

from backend.app.recognition.reasoner import DecisionPolicy


def test_my_first_test(clock) -> None:
    assert clock().year == 2026


@pytest.mark.parametrize("margin", [0.0, -0.1, 2.5])
def test_a_margin_outside_the_range_is_refused(margin: float) -> None:
    with pytest.raises(ValueError, match="margin"):
        DecisionPolicy("v", 0.5, 0.6, margin, 0.3)
```

Run `uv run pytest tests/unit/test_scratch.py -v`. Expected (observed): four lines marked `PASSED`
(`test_my_first_test` and the three parameter values). `clock` came from `tests/fixtures/deterministic.py`
and is frozen at 2026-01-01. Now change one value to something the policy accepts (say `margin=0.5`),
rerun, and read how pytest reports a test whose `pytest.raises` block did not raise (`Failed: DID NOT
RAISE <class 'ValueError'>`). Then delete the file: `rm tests/unit/test_scratch.py`; `git status` must
show nothing from `tests/`.

To change a *real* test, find the rule's own test file, make the code change, and run that file and its
neighbours first, then the whole folder (`tests/unit`, then `tests/integration`). The rule for bugs is
fixed in `.agents/rules/testing.md`: **a bug fix gets a test that fails without the fix**; and you never
delete, skip, or weaken a test to get green.

## 6. Break it on purpose

Misspell a marker on the command line: `uv run pytest -m unitt -q`. Observed: `2951 deselected` and no
test runs (a typo selects nothing, so look at the count). Put a misspelled marker in a *test*
(`@pytest.mark.unitt`) and the run stops with `'unitt' not found in markers configuration option`,
because `--strict-markers` is on. Add `import warnings; warnings.warn("x")` to a scratch test and watch it
**fail** (`FAILED ... - UserWarning: x`), not warn, because `filterwarnings = ["error"]`. These are
deliberate: a misspelling or a new deprecation fails loudly rather than scrolling past.

## 7. Exercises

1. What decides that a test under `tests/integration/` has the `integration` marker?
2. How do you run only the tests with "stale" in their name, in one file?
3. Which four markers does a plain `uv run pytest` skip, and why?
4. Why do persistence tests use a real SQLite file and not a mock?
5. What is the rule for a bug fix and tests?

**Answers**

1. `DIRECTORY_MARKERS` in `tests/conftest.py` maps the first folder name under `tests/` to a marker.
2. `uv run pytest tests/integration/test_person_use_cases.py -k stale -q`.
3. `e2e`, `ml_eval`, `benchmark`, `hardware`: they need real models, a GPU or long runs.
4. A mock cannot show that a constraint, a transaction or a migration really works; the real engine can.
5. A bug fix includes a test that fails without the fix.

## 8. Related files

- Previous: [02 uv](02-uv-and-dependencies.md) · Next: [04 ruff and mypy](04-ruff-and-mypy.md)
- [`docs/guides/TESTING_GUIDE.md`](../../../TESTING_GUIDE.md), [`.agents/rules/testing.md`](../../../../../.agents/rules/testing.md)
- [`tests/conftest.py`](../../../../../tests/conftest.py)
