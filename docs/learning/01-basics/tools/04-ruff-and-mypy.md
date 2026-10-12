# Tools 04 ruff and mypy

## 1. What this is and why it exists

Two automatic reviewers that read your code without running it, so a whole class of mistakes never
reaches a person. **ruff** is a *linter* (it flags probable mistakes and style problems: an unused
import, a line that is too long) and a *formatter* (it rewrites files into the one house style).
**mypy** is the *type checker*: it reads the type hints and tells you, before anything runs, that you
passed a `str` where a `float` was expected. Both must be clean before any change is called done.

## 2. Where it lives

Everything is configured in `pyproject.toml`:

```toml
[tool.ruff]
target-version = "py312"
line-length = 100
include = ["*.py", "*.pyi", "pyproject.toml"]       # Python only: the specs (.md) are never reformatted

[tool.ruff.lint]
select = ["E", "F", "W", "I", "B", "UP", "PT"]      # pycodestyle, pyflakes, warnings, import order, bugbear, upgrades, pytest style

[tool.mypy]
python_version = "3.12"
files = ["backend", "tests"]
strict = true
warn_unreachable = true
```

`backend/alembic/versions/*.py` is exempt from the line-length rule (E501): those files bake in long
generated SQL strings.

## 3. How it works

| Command | What it does | Changes files? |
|---|---|---|
| `uv run ruff format --check .` | Says which files would be reformatted | no |
| `uv run ruff format .` | Reformats them | **yes** |
| `uv run ruff check .` | Reports lint problems | no |
| `uv run ruff check . --fix` | Fixes the safely fixable ones | **yes** |
| `uv run mypy` | Checks the types of `backend` and `tests` as seen on **your** operating system | no |
| `uv run mypy --platform linux` | Checks what CI's Linux job sees | no |

Why the platform matters: CI's "Static validation" job runs these on **Linux** while the backend is
built on Windows. A call that exists only on Windows (for example `ctypes.WinDLL`, `os.startfile`,
`socket.SO_EXCLUSIVEADDRUSE`) must sit behind `if sys.platform == "win32":` so the Linux check does not
fail. You will see exactly that in `backend/api/host.py` (`parent_alive`, `_loopback_listener`).

**`strict` mypy** means every function needs full type hints, `Any` is not allowed to leak silently,
and so on. The project keeps `# type: ignore[code]` to a minimum. `onnxruntime` ships no type
information, so it is `ignore_missing_imports` (`[[tool.mypy.overrides]]`); `usearch` is partially
annotated, so calls into it are excluded from `untyped_calls`.

The numbers in the mypy message are not the problem: `Success: no issues found in 291 source files`
counts files, and grows as files are added.

## 4. Try it

**Works with no models. Verified 2026-10-12.**

1. The project's own state. All three should be clean:

   ```bash
   uv run ruff format --check .
   uv run ruff check .
   uv run mypy
   ```

   Expected, in order: `297 files already formatted` (the number grows), `All checks passed!`,
   and `Success: no issues found in 291 source files`. `uv run mypy` took about 20 seconds cold.
2. See what ruff says about messy code. Create `lint.py` **outside the repository** (any scratch
   folder) with:

   ```python
   import os, sys
   x = 1
   def f( a ):
       return a+1
   ```

   Then, from the repository folder, `uv run ruff check --output-format concise path/to/lint.py`.
   Expected:

   ```text
   lint.py:1:1: E401 [*] Multiple imports on one line
   lint.py:1:1: I001 [*] Import block is un-sorted or un-formatted
   lint.py:1:8: F401 [*] `os` imported but unused
   lint.py:1:12: F401 [*] `sys` imported but unused
   Found 4 errors.
   [*] 4 fixable with the `--fix` option.
   ```

   `[*]` means ruff can fix it for you. Now see the formatter's opinion:
   `uv run ruff format --diff path/to/lint.py` prints a diff that adds blank lines, writes `f(a)` and
   `a + 1`, and ends `1 file would be reformatted`.
3. See what mypy says: `uv run mypy path/to/lint.py`. Expected: `lint.py:3: error: Function is missing
   a type annotation  [no-untyped-def]` and `Found 1 error in 1 file`. (Fix: `def f(a: int) -> int:`.)
4. The Linux view: `uv run mypy --platform linux` ends `Success: no issues found in 291 source files`.
5. Read the rule behind a code: `uv run ruff rule F401` explains "unused import".

## 5. Change it

Make a deliberate formatting mistake in a real file and let ruff repair it:

1. Add the line `x=1` at the end of `scripts/smoke_real_models.py`.
2. `uv run ruff format --check .` reports `1 file would be reformatted` and exits non-zero.
3. `uv run ruff format scripts/smoke_real_models.py` fixes it (the `x=1` becomes `x = 1`).
4. Undo: `git restore scripts/smoke_real_models.py`.

(Run on 2026-10-12.) When you change real code, run all three checks before you commit; CI will run
them again, and so will the reviewer. Never silence a rule with `# noqa` or a new per-file ignore to get
green without a recorded reason.

## 6. Break it on purpose

Introduce a type error in a real file and see what the checker says: in `backend/app/recognition/reasoner.py`
change the field `margin: float` of `DecisionPolicy` to `margin: str`. Run `uv run mypy`. Observed
(2026-10-12): `Found 14 errors in 5 files`, for example
`backend/app/processing/execute_job.py:859: error: Argument 4 to "DecisionPolicy" has incompatible type
"float"; expected "str"  [arg-type]` and `Unsupported operand types for >= ("float" and "str")  [operator]`
in the tests. The checker found every caller of the field without running anything. Undo with
`git restore backend/app/recognition/reasoner.py` and re-run `uv run mypy` to see it clean again.

## 7. Exercises

1. Which command tells you what *would* be reformatted without changing anything?
2. Why does CI run mypy on Linux when the backend is developed on Windows?
3. What does `[*]` next to a ruff error mean?
4. Why is the line length 100?
5. Where would you look to find out why a line has `# type: ignore[...]`?

**Answers**

1. `uv run ruff format --check .`
2. CI's static job runs on a Linux runner; code that only exists on Windows must be guarded or the Linux
   check fails.
3. The problem can be fixed automatically with `--fix`.
4. It is the project's configured line length (`line-length = 100`); a longer line is reported as E501.
5. Next to the line itself; the project's rule is to keep ignores few and to record why.

## 8. Related files

- Previous: [03 pytest](03-pytest.md) · Next: [05 Git and pull requests](05-git-and-pull-requests.md)
- [`pyproject.toml`](../../../../pyproject.toml)
- [CI](06-ci.md) for the job that runs these
