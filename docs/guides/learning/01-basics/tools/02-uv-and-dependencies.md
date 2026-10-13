# Tools 02 uv and dependencies

## 1. What this is and why it exists

Python projects depend on other people's code (packages). Two projects on the same computer can need
different versions of the same package, so each project gets a private folder of installed packages: a
**virtual environment**, here `.venv/`. **`uv`** is the tool that creates it, installs the right Python
and the right package versions, and runs commands inside it. You never "activate" anything: you put
`uv run` in front of a command.

## 2. Where it lives

| File or folder | What it holds |
|---|---|
| `.python-version` | The Python version to use: `3.12` |
| `pyproject.toml` | The project's Python version rule (`requires-python = ">=3.12"`), its **dependencies**, the **dev** dependencies, and the settings of pytest, ruff, mypy and coverage |
| `uv.lock` | The exact version of every package (51 of them) so every machine installs the same thing |
| `.venv/` | The installed packages (Git-ignored; recreated by `uv sync`) |

The runtime dependencies (what the application needs): `alembic`, `fastapi`, `numpy`, `onnxruntime`,
`pillow`, `sqlalchemy`, `usearch`, `uvicorn`, `websockets`. The dev dependencies (what building and
checking it needs): `httpx`, `hypothesis`, `mypy`, `onnx`, `pytest`, `pytest-asyncio`, `pytest-cov`,
`ruff`.

## 3. How it works

- **`uv sync`** makes `.venv` match `uv.lock` exactly (creating it and downloading Python 3.12 if
  needed). **`uv sync --locked`** is what CI uses: it fails if `pyproject.toml` and `uv.lock` disagree.
- **`uv run <command>`** runs a command inside that environment: `uv run pytest`, `uv run python`,
  `uv run python -m backend.api.host`, `uv run ruff check .`.
- **`uv tree`** shows the dependency tree; **`uv lock --check`** checks the lock matches `pyproject.toml`.
- The project's rule (`.agents/rules/scope.md`) is that **uv is the only Python package manager** and
  **npm the only JavaScript one**. A new dependency needs a reason, an entry in the implementation
  entry and a row in `docs/research/licensing-and-commercialization.md`.
- `pyproject.toml` also says: no `build-system` (the backend is imported from the repository root,
  because `pytest` has `pythonpath = ["."]` and commands run from there); the warning filter is
  `error` (a warning fails a test); and markers are strict (a misspelled marker fails the run).

## 4. Try it

**Works with no models. Verified 2026-10-12.**

1. See which Python you run:

   ```bash
   uv run python -c "import sys; print(sys.executable); print(sys.version.split()[0])"
   ```

   Expected: a path ending `.venv/bin/python3` (`.venv\Scripts\python.exe` on Windows) and a `3.12.x`
   version.
2. See the direct dependencies:

   ```bash
   uv tree --depth 1
   ```

   Expected: `faceidentify v0.0.0` and a list: the nine runtime packages, then the dev ones marked
   `(group: dev)`, each with its pinned version (for example `fastapi v0.142.2`, `numpy v2.5.3`).
3. Check the lock is in step with the project file: `uv lock --check`. Expected: `Resolved 51 packages
   in ...ms` and exit code 0 (no network needed when nothing changed).
4. Count what is installed: `uv pip list | wc -l` printed 51 on the verified run (49 packages plus
   two header lines; `uv sync` itself says `Checked 49 packages`; the lock lists 51 entries, which includes the project
   itself and, presumably, packages that apply only to other platforms; that split was not examined).
5. Run a one-off script without installing anything extra: `uv run python -c "import fastapi, sqlalchemy; print(fastapi.__version__, sqlalchemy.__version__)"`.

## 5. Change it

Do **not** add a dependency in this guide's exercises: the rules forbid it without a reason. The safe
way to practise is to read what adding one would change. In a scratch clone (not this checkout):
`uv add <package>` would edit `pyproject.toml` *and* `uv.lock` together; both belong in the same commit
as the code that needs it, and CI's `uv sync --locked` would fail if only one were committed. Verify the
second half yourself in this checkout: edit nothing, run `uv sync --locked`; expected: it succeeds and
changes nothing.

## 6. Break it on purpose

Run Python without `uv run` when you have another interpreter: `python -c "import fastapi"` gives
`ModuleNotFoundError: No module named 'fastapi'` (that Python has none of the project's packages). Or
delete `.venv/` and run `uv run pytest -q tests/unit/test_recognition_reasoner.py`: uv recreates the
environment first (slower once), then runs. (Not repeated here to avoid reinstalling; documented
behaviour of `uv run`.)

## 7. Exercises

1. Which file lists the exact version of every installed package?
2. Why does CI use `uv sync --locked`?
3. Name three runtime and three dev dependencies.
4. What does `uv run` save you from?

**Answers**

1. `uv.lock`.
2. It fails if `pyproject.toml` and `uv.lock` disagree, so nobody can merge a dependency change without
   committing its lock.
3. For example `fastapi`, `sqlalchemy`, `usearch`; `pytest`, `ruff`, `mypy`.
4. Activating a virtual environment and using the wrong Python by accident.

## 8. Related files

- Previous: [01 Terminal](01-terminal-and-environment.md) · Next: [03 pytest](03-pytest.md)
- [`pyproject.toml`](../../../../../pyproject.toml), [`.agents/rules/scope.md`](../../../../../.agents/rules/scope.md)
- [Set up your machine](../../00-start-here/06-set-up-your-machine.md)
