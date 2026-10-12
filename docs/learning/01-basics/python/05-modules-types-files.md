# Python 05 Modules, types, files and hashes

## 1. What this is and why it exists

Four everyday topics that the backend leans on. **Modules** are how code is split across files and how
a program is started. **Type hints** are notes about what each value is that a checker (`mypy`)
verifies before the code runs. **Paths and bytes** are how the program handles files, and a **hash**
is the fingerprint it uses to know a file is the file it thinks it is. **`with`** is how it guarantees
cleanup. Together they explain how an imported photograph is stored safely.

## 2. Where it lives

| Idea | Real example |
|---|---|
| Starting a module as a program | `python -m backend.api.host` runs `backend/api/host.py`; its last lines are `if __name__ == "__main__": raise SystemExit(main())` |
| Type hints, strict | `[tool.mypy] strict = true` in `pyproject.toml`; the whole `backend` and `tests` are checked |
| Hashing a file in chunks | `digest_path` and `_digest_stream` in `backend/infrastructure/storage/files.py` |
| Atomic write | `ManagedFileStore` in the same file: write `staging/<id>.part`, hash while streaming, `fsync`, then rename |
| A context manager | `open_library` in `backend/app/lifecycle.py` (`@contextmanager`): releases the library lock and disposes the engine on exit |

## 3. How it works

### Modules and packages

A file `foo.py` is a **module**; a folder is a **package**. `import` makes names from another module
available:

```python
import hashlib                                  # use as hashlib.sha256(...)
from pathlib import Path                        # use as Path(...)
from backend.app.recognition.reasoner import DecisionPolicy
import numpy as np                              # `as` gives a short alias
```

The dotted path mirrors the folders: `backend.app.recognition.reasoner` is
`backend/app/recognition/reasoner.py`. `python -m backend.api.host` means "run that module as the main
program" (`-m` = module); the block `if __name__ == "__main__":` at the bottom of a file runs only
when the file is run directly, not when it is imported. The standard library gives you most tools for
free: `pathlib`, `json`, `hashlib`, `uuid`, `datetime`, `threading`, `subprocess`, `socket`, `sqlite3`,
`argparse`, `logging`, `enum`, `dataclasses`, `typing`. Third-party packages are installed by `uv` and
listed in `pyproject.toml`.

### Type hints

Python does not require declaring types. This project writes them everywhere and checks them with
`mypy --strict`. They are notes to humans and to the checker; they do not change how the program runs.

```python
def decide(assessment: RecognitionAssessment) -> RecognitionDecision: ...
threshold: float = 0.35
names: list[str] = []
maybe: str | None = None            # a str or None
callback: Callable[[int], str]      # a function taking an int, returning a str
LIMIT: Final = 5                    # a constant
```

`T = TypeVar("T")` makes a **generic**: `def read(self, work: Callable[[Session], T]) -> T` says "whatever
type `work` returns, `read` returns that same type". `# type: ignore[code]` silences one line when the
checker is wrong; the project keeps these to a minimum.

### Files, paths and bytes

```python
from pathlib import Path
folder = Path("local-models") / "state"          # `/` joins path parts, on any OS
folder.mkdir(parents=True, exist_ok=True)
file = folder / "policy.json"
file.write_text("{}", encoding="utf-8"); text = file.read_text(encoding="utf-8")
data = file.read_bytes()
file.exists(); file.is_dir(); file.stat().st_size
```

`bytes` are raw data. A **hash** (`hashlib.sha256(data).hexdigest()`) turns any amount of data into a
fixed-size fingerprint: change one bit and the fingerprint changes completely. The code uses SHA-256
to identify files (a photograph, a model file) and to check that what it reads is what it recorded.

**Atomic writes.** If the power fails halfway through writing a file you are left with half a file. So
the storage layer writes to a temporary file in `staging/`, flushes it to disk, then **renames** it into
place (a rename is all-or-nothing). A file at its final path is therefore always complete.

### Context managers

`with` guarantees cleanup even if an error occurs:

```python
with open(path, "rb") as handle:        # closed when the block ends
    data = handle.read()
with open_library(library_root=..., ...) as library:   # lock released, engine disposed on exit
    ...
```

You write your own with `contextlib.contextmanager` (a function that `yield`s once) or a class with
`__enter__` and `__exit__`.

## 4. Try it

**Works with no models. Verified 2026-10-12.**

1. SHA-256, in `uv run python`: a one-letter change gives an unrelated fingerprint.

   ```python
   >>> import hashlib
   >>> hashlib.sha256(b"abc").hexdigest()
   'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad'
   >>> hashlib.sha256(b"abd").hexdigest()
   'a52d159f262b2c6ddb724a61840befc36eb30c88877a4030b65cbe86298449c9'
   ```

2. The project's own file hasher, which reads in 1 MiB chunks:

   ```python
   >>> import pathlib, tempfile
   >>> from backend.infrastructure.storage.files import digest_path
   >>> f = pathlib.Path(tempfile.mkdtemp()) / "f.txt"; f.write_text("abc", encoding="utf-8")
   3
   >>> r = digest_path(f); r.sha256.hex()[:16], r.size_bytes
   ('ba7816bf8f01cfea', 3)
   ```

3. Paths: `pathlib.Path("local-models") / "state" / "policy.json"` prints
   `local-models/state/policy.json` (backslashes on Windows) and its `.suffix` is `'.json'`.
4. **Make the type checker earn its keep.** Create a scratch file outside the repository (any folder)
   `wrong.py`:

   ```python
   def accepted(score: float, threshold: float) -> bool:
       return score >= threshold


   accepted("0.4", 0.35)
   x: int = "three"
   ```

   and run `uv run mypy path/to/wrong.py` from the repository folder. Expected: two errors,
   `Argument 1 to "accepted" has incompatible type "str"; expected "float"  [arg-type]` and
   `Incompatible types in assignment (expression has type "str", variable has type "int")  [assignment]`,
   then `Found 2 errors in 1 file`. Nothing was run; the mistakes were caught by reading.
5. Watch `python -m` at work: `uv run python -m backend.api.host --help` (the usage text from
   [lesson 01](../../00-start-here/01-what-it-is.md)) runs `host.py` as a program.

## 5. Change it

The strictest safe change is to a type hint in a **scratch copy** of something small. For a real file:
open `backend/infrastructure/storage/files.py` and read `_digest_stream`; the test that proves the
hash is of the bytes read is in `tests/integration/test_storage_files.py`:

```bash
uv run pytest tests/integration/test_storage_files.py -q
```

On Windows (CI's platform) these pass. **On Linux four of them fail in this guide's author's sandbox**
(`test_a_link_loop_is_an_unusable_key_not_a_crash`, `test_different_bytes_never_overwrite_managed_content`,
`test_a_file_appearing_at_the_key_during_the_write_is_not_overwritten`,
`test_a_locked_staging_file_does_not_hide_the_real_error`): they depend on Windows behaviour (the
`cmd` shell, renaming onto an existing file being refused, locked files; the failures read
`No such file or directory: 'cmd'` and `DID NOT RAISE ExistingContentError`). If you break the chunk loop in `_digest_stream` (say, stop after the first chunk), the
tests that check size and hash of a multi-chunk file fail on any platform.

## 6. Break it on purpose

Import something that does not exist: `from backend.app.nowhere import x`. Expected:
`ModuleNotFoundError: No module named 'backend.app.nowhere'`. Run a script that imports `backend`
from outside the repository folder and you get `ModuleNotFoundError: No module named 'backend'`; this
is why commands in this guide are run from the repository root and why `pytest` has
`pythonpath = ["."]` in `pyproject.toml`.

## 7. Exercises

1. What does `python -m backend.api.host` do that `python backend/api/host.py` might not?
2. If a hash of a stored original no longer matches the recorded one, what does that tell you?
3. Why does the storage layer write to `staging/` and rename, instead of writing to the final path?
4. Which command checks every type hint in the repository? Which flag makes it strict?
5. What does `with` do if the block raises an error?

**Answers**

1. It runs the file as a module of the `backend` package, so `from backend...` imports resolve from the
   repository root.
2. The file has changed or is damaged; the app marks such an artifact unusable (`MISSING`) rather than
   trusting it, and a referenced original can be relinked only to a file with the same size and SHA-256.
3. A rename is all-or-nothing, so a file at the final path is never half-written, even if the power fails.
4. `uv run mypy`; `strict = true` in `pyproject.toml`.
5. It still runs the cleanup (closes the file, releases the lock) and then lets the error continue.

## 8. Related files

- Previous: [04 Classes, dataclasses and enums](04-classes-dataclasses-enums.md) · Next: [06 Iterators, decorators and concurrency](06-iterators-decorators-concurrency.md)
- [`backend/infrastructure/storage/files.py`](../../../../backend/infrastructure/storage/files.py)
- [ruff and mypy](../tools/04-ruff-and-mypy.md), [storage roots and artifacts](../../02-data-and-storage/08-storage-roots-and-artifacts.md)
