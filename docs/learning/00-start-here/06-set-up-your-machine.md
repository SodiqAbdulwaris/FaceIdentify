# 06 Set up your machine

## 1. What this is and why it exists

Before you can run, test or change anything you need the project's tools installed and a clean
checkout that passes its own checks. This lesson takes you from "nothing installed" to "the
repository's checks run and pass". Do it once per computer.

The project targets **Windows** (it is a Windows desktop application), and its continuous
integration runs the Python suite on Windows. The commands in this guide were verified on **Linux**
while it was written; where Windows differs, both forms are shown and the Windows form is marked
*unverified here*.

## 2. Where it lives

The versions are pinned in files in the repository, so you never have to guess:

| File | Pins |
|---|---|
| `.python-version` | Python `3.12` |
| `.nvmrc` | Node `24` |
| `pyproject.toml`, `uv.lock` | Python dependencies and their exact versions |
| `package.json`, `package-lock.json` | JavaScript dependencies (npm workspaces: the root plus `frontend`) |
| `desktop/src-tauri/Cargo.toml`, `Cargo.lock` | Rust dependencies; `rust-version = "1.77.2"` |
| `.githooks/` | The commit and push checks you enable in step 4 |

## 3. How it works

You install four tools, and each installs the rest by itself:

| Tool | Why | Needed for |
|---|---|---|
| **Git** | History, branches, pull requests | everything |
| **uv** | Installs the right Python (3.12) and every Python package from `uv.lock` | the backend, the tests, the checks |
| **Node.js 24** (with npm) | Runs the front end's tools | the front end and its tests |
| **Rust** (via `rustup`) plus, on Windows, the Microsoft C++ Build Tools and WebView2 | Builds the desktop shell | **only** `npm run tauri dev` and the shell's tests |

You can learn, run and test the backend and front end without Rust. You need Rust only to open the
desktop window. Optional: **GitHub CLI** (`gh`) for pull requests, and a read-only reviewer such as
the **Codex CLI** (see [rules, branches and reviews](../06-evaluation-and-operations/06-rules-branches-reviews.md)).

## 4. Try it

**Works with no models.** Commands verified on Linux, Python 3.12, Node 22 on 2026-10-12 unless
marked.

1. **Install the tools.** On Windows, for example (*unverified here: names change; follow each
   tool's own install page if one fails*):

   ```powershell
   winget install --id Git.Git
   winget install --id astral-sh.uv
   winget install --id OpenJS.NodeJS
   winget install --id Rustlang.Rustup
   ```

   For the desktop shell on Windows, Tauri also needs the Microsoft C++ Build Tools and the WebView2
   runtime (Windows 11 has it). The authoritative list is Tauri's prerequisites page,
   <https://v2.tauri.app/start/prerequisites/>.
2. **Get the code** and enter it:

   ```bash
   git clone https://github.com/SodiqAbdulwaris/FaceIdentify.git
   cd FaceIdentify
   ```

3. **Enable the project's hooks** (once per clone):

   ```bash
   git config core.hooksPath .githooks
   ```

   Expected: no output. From now on a commit with a bad message, or a push to `main`, is refused.
4. **Install the Python side:**

   ```bash
   uv sync
   ```

   Expected: uv downloads Python 3.12 if needed, creates `.venv/` and installs the packages
   (`fastapi`, `sqlalchemy`, `alembic`, `usearch`, `onnxruntime`, `numpy`, `pillow`, `uvicorn`,
   `websockets` and the dev tools: `pytest`, `ruff`, `mypy`, `httpx`, `hypothesis`, `onnx`).
5. **Install the JavaScript side** with `npm ci`, not `npm install`:

   ```bash
   npm ci
   ```

   Expected: `node_modules/` appears. `npm ci` installs exactly what `package-lock.json` says and never
   edits it. On 2026-10-12 `npm install` on Linux with Node 22 removed 93 lines of platform entries from
   `package-lock.json`; if you ever see `git status` show that file changed without you asking, run
   `git restore package-lock.json`.
6. **Prove the checks run** (each should end clean):

   ```bash
   uv run ruff format --check .      # "297 files already formatted" (the number changes as files are added)
   uv run ruff check .               # "All checks passed!"
   uv run mypy                       # "Success: no issues found in 291 source files"
   npm run typecheck                 # prints "> tsc -b" and nothing else
   npm run lint                      # oxlint; no errors
   npm test                          # "Tests 193 passed (193)" in about 20 seconds
   ```

7. **Run the Python tests.** On Windows, the way CI does:

   ```bash
   uv run pytest -q
   ```

   On Windows, expected: all pass (CI runs it with coverage). **On Linux this guide's author saw
   `37 failed, 2894 passed, 3 skipped, 2 deselected, 15 errors` in about 5 minutes**: every failure is a
   Windows-only behaviour (file locks, shared memory, process kill semantics) in
   `test_shared_memory.py`, `test_ml_supervisor.py`, `test_storage_files.py`, `test_representation_index.py`
   and a few others. That is a property of the sandbox it was run in, not a bug in your checkout. On
   Linux, run the part you care about instead (lesson [pytest](../01-basics/tools/03-pytest.md)).

8. **Optional, to see the window** (Rust installed):

   ```bash
   npm run tauri dev
   ```

   *Unverified here: the writing environment has no display.* It starts the front end's dev server
   (`npm run dev` via `beforeDevCommand`), builds the Rust shell, opens a window titled
   "FaceIdentify" and, because it is a debug build, starts the backend on the development profile.
   The cold build takes minutes. `npx tauri build --debug --no-bundle` is the "does it compile" check
   (about 3 minutes cold, per `.agents/CONTEXT.md`; also unverified here).

## 5. Change it

Make one harmless local change and see the toolchain notice it. Add a line `x=1` to the end of
`scripts/smoke_real_models.py` and run:

```bash
uv run ruff format --check .
```

Expected: ruff reports it would reformat that file (`x=1` lacks spaces) and exits non-zero. Undo with
`git restore scripts/smoke_real_models.py`. (Run on 2026-10-12.)

## 6. Break it on purpose

Use the wrong command, `pytest` without `uv run`:

```bash
pytest -q
```

Expected: `command not found`, or, if you have another Python on the path, errors such as
`ModuleNotFoundError: No module named 'sqlalchemy'`. The project's packages live in `.venv/`;
`uv run` is how you step into it without "activating" anything.

## 7. Exercises

1. Which file decides which Python version runs the tests?
2. Why `npm ci` and not `npm install`?
3. Which tool do you not need to install if you only want to run the backend and its tests?
4. What does `git config core.hooksPath .githooks` protect you from?

**Answers**

1. `.python-version` (and `requires-python = ">=3.12"` in `pyproject.toml`).
2. `npm ci` follows the lockfile exactly and never rewrites it; `npm install` may.
3. Rust (and its Windows build tools).
4. Committing with a malformed message, committing to `main`, pushing to `main`, or pushing a badly
   named branch.

## 8. Related files

- Previous: [05 One request, end to end](05-one-request-end-to-end.md) · Next: [07 Run it and see it work](07-run-it-and-see-it-work.md)
- [`docs/guides/TESTING_GUIDE.md`](../../guides/TESTING_GUIDE.md)
- [uv and dependencies](../01-basics/tools/02-uv-and-dependencies.md)
- [Git and pull requests](../01-basics/tools/05-git-and-pull-requests.md)
