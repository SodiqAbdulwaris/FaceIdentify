# The FaceIdentify Learning Guide

**What this is.** One document that teaches you everything you need to understand this codebase,
starting from "what is a variable" and ending at "how a photograph becomes a named person on the
screen". It replaces the old `StackResearch.md`, which was a bare list of topics to research. Every
topic from that list is still here (Part 5 keeps its checklist and says, for each topic, whether the
project uses it, designed it for later, or only researched it).

**Who it is for.** You, the owner, reading code you did not type. It assumes you can read English
and use a computer. It assumes nothing else.

**How it is organised.** Twelve parts. Read them in order the first time; after that, use the
contents and the glossary (Part 12) as a reference.

| Part | You will learn | Read it when |
|---|---|---|
| 1 | What the application is and how its pieces fit | First, always |
| 2 | Python from zero, with examples from this repository | You cannot yet read a `.py` file |
| 3 | The tools: uv, pytest, ruff, mypy, git, CI | You want to run or check anything |
| 4 | Maths and machine-learning ideas: vectors, embeddings, thresholds | You want to know what "recognition" means |
| 5 | The computer-vision topic map (the old research checklist) | You want the wider field |
| 6 | Databases and storage: SQL, SQLite, transactions, the vector index | You want to know where memory lives |
| 7 | The backend: layers, FastAPI, the worker, scheduling, recovery | You want to know how work gets done |
| 8 | The domain model: Source, Observation, Identity, Person, Evidence ... | You want the vocabulary of the product |
| 9 | The front end: TypeScript, React, queries, events | You want to read the screens |
| 10 | The desktop shell: Rust and Tauri | You want to know how the window starts the backend |
| 11 | How this project is run: rules, branches, reviews, decisions | You want to contribute or review |
| 12 | A walkthrough of one photograph, a reading path, exercises, a glossary | When you want it all to click |

**Markers used in the text**

- **[built]**: exists in the repository and is tested.
- **[designed]**: written in a specification, not built yet.
- **[researched]**: considered, not chosen or not needed yet.
- `code like this`: a file name, a command, a function or a value you can find with a search.
- `docs/specs/...`: the authoritative design documents. If this guide and a spec ever disagree, the
  spec wins and this guide is out of date.

**A promise about accuracy.** Where this guide describes this repository it describes what is in
`main` on 2026-10-08. Where it describes general knowledge (what a loop is, what a CNN is), it
describes the idea in the simplest honest way and does not pretend to be a textbook. The
"Further reading" list at the end points to real ones.

---

# Part 1. The big picture

## 1.1 What FaceIdentify is

FaceIdentify is a **Windows desktop application that remembers people by their faces, on your own
computer**. You give it photographs (video and cameras are planned, not built). It finds the faces,
turns each face into a list of numbers, compares that list with the lists it has seen before, and
decides one of three things for each face:

1. **This is someone I already know**: attach the face to that person's memory.
2. **This is someone new**: start a new memory.
3. **I am not sure**: do nothing automatically and leave the face for you to place by hand
   ("abstain").

You can then name a person, correct a wrong guess, merge two memories that are the same person, split
one that is two people, and (planned) search by name or by a face. Nothing leaves your machine:
there is no cloud, no account and no network service in the design. This is a personal tool.

The owner's rule, repeated through the project: **a wrong automatic guess is worse than no guess.**
That single idea explains most of the caution you will see in the code (thresholds, abstaining,
evidence records, "pending" data that is private until it is accepted).

## 1.2 The four programs that run when you start it

When you start the app, four different programs are involved. They are separate *processes*
(running programs, each with its own memory). Learn these four names; everything else hangs on them.

```
 you
  |  clicks, types
  v
+--------------------------+      starts and stops       +-------------------------------+
| 1. THE SHELL             | --------------------------> | 2. THE BACKEND (the "sidecar") |
|    Rust + Tauri          |  gives it a secret token    |    Python + FastAPI            |
|    desktop/src-tauri     |  reads one line back        |    backend/api/host.py         |
|  shows a window          |                             |  HTTP + WebSocket on           |
+-----------+--------------+                             |  127.0.0.1:<random port>       |
            |  loads                                     +---+------------------+---------+
            v                                                |                  |
+--------------------------+       HTTP requests with          |                  | starts and
| 3. THE FRONT END         | <--------------------------------+                  | supervises
|    TypeScript + React    |   the token; WebSocket events                       v
|    frontend/src          |                                      +----------------------------+
| runs inside the window   |                                      | 4. THE ML WORKER           |
+--------------------------+                                      |    Python + ONNX Runtime   |
                                                                  |    backend/ml/worker       |
                                                                  | runs the face models       |
                                                                  +----------------------------+
```

1. **The shell** (Rust, using a toolkit called Tauri) is the thing you double-click. It opens a
   window, picks the folder where your library lives, starts the backend, and stops it when you quit.
2. **The backend** (Python, using a toolkit called FastAPI) is the real application. It owns the
   database, the files, the rules and the memory. It listens only on your own machine
   (`127.0.0.1`, "loopback"), on a random port, and only answers requests that carry a secret token
   the shell generated for this launch.
3. **The front end** (TypeScript, using React) is the web page shown inside the window. It has no
   memory of its own. It asks the backend for everything and tells the backend what you did.
4. **The ML worker** (Python, using ONNX Runtime) is a separate process that only runs the neural
   networks. It is separate so that a crash inside native model code can never corrupt your data:
   the backend notices, restarts it and carries on.

   **What runs today.** The worker, its supervisor and the real models are built and tested, and the
   host now has a *real profile* that uses them (Part 7.3): it registers the installed model package,
   keeps one worker per plan, and builds each run from the measured policy file. A **debug** build of
   the shell still starts the backend in its *development profile*, where a fake in-process
   "perception" stands in for the worker; a **release** build runs the real profile. The real profile
   needs the model package installed and a measured policy file: with no package the app is
   `DEGRADED` (`runtime_package: UNAVAILABLE`), and with no usable policy it reports
   `processing_policy: UNAVAILABLE`; either way it refuses to process (`503`) rather than guess.
   Until a verified evaluation exists it also refuses any policy that could match or create an
   identity from a score, whatever the file says.

**Why a web page inside a desktop window?** Because building screens with web technology is faster
and better supported than building them natively, and Tauri gives you a small, secure window to host
them in. **Why Python for the real work?** Because the machine-learning ecosystem (ONNX Runtime,
NumPy, image libraries) lives in Python. **Why Rust for the shell?** Because Tauri is written in
Rust, and the shell is a thin, careful piece that handles processes and secrets.

## 1.3 The rule that organises the data: authoritative versus derived

The most important design idea in the project is stated in `docs/research/tech-stack.md` section 19:

- **Authoritative** data is the truth and cannot be recomputed: the SQLite database, your original
  photographs, and the model files.
- **Derived** data can be rebuilt from the authoritative data if it is lost or damaged: the vector
  index (USearch), thumbnails, caches.
- **Operational** data is temporary: lock files, work folders, logs.

So if the search index file is deleted or corrupted, nothing is lost: the program rebuilds it from the
database at the next start. If the *database* is lost, that is a real loss, so the database gets the
careful treatment: transactions, a write-ahead log, constraints, migrations, backups-by-design. When
you read the persistence code, ask of every piece "is this the truth, or can it be rebuilt?"

## 1.4 The layers inside the backend

The backend is organised in layers. A layer may use the layers below it, never above.

```
 backend/api/            HTTP and WebSocket: routes, errors, events, the sidecar host, the scheduler loop
    |  calls
 backend/app/            Application logic, grouped by topic ("use cases"): sources, processing,
    |                    recognition, identities, people, memory, jobs, recovery, runtime, settings
    |  uses
 backend/infrastructure/ Technical plumbing: database engine and unit of work, storage on disk,
    |                    the vector index, media decoding, events, diagnostics
    |
 backend/ml/             Everything about the model worker: the message contract, the supervisor
                         that starts/stops the worker, the worker itself, the face-detection maths
```

Why layers? So that a rule like "a merge must be atomic" lives in exactly one place
(`backend/app/identities/`), not scattered across routes. And so that tests can exercise each layer
on its own: `tests/unit/` for tiny pieces, `tests/integration/` for pieces with a real database,
`tests/e2e/` for the whole thing.

## 1.5 One request, end to end (a first look)

You drop a photograph into the library screen and press "process". In outline:

1. The front end sends `POST /api/v1/sources/import`; the backend copies or references the file,
   hashes it, and creates a **Source** row.
2. You press process: `POST /api/v1/sources/{id}/process`. The backend writes a **Job** and a
   **ProcessingRun** (with a frozen copy of all the settings, the "snapshot") in one transaction and
   answers `202 Accepted`. Nothing has been recognised yet.
3. The **scheduler** loop, a background task inside the backend, claims the job, and the
   **ProcessingRunner** executes it: decode the image, ask the worker to detect faces, write each face
   as a *pending* **Observation**, ask the worker (in the development profile, the fake stand-in)
   for each face's embedding, write *pending*
   **Representations**, search the memory for similar ones, and let the **reasoner** decide.
4. A final checkpoint is written. Then **acceptance** runs in one transaction: pending data becomes
   active, **Occurrences** and **Evidence** are written, new **Identities** are created, vectors are
   queued for the index, and the run is marked completed.
5. The backend publishes an event over the WebSocket; the front end re-fetches and the screen shows
   the faces and the people found.

Part 12 walks the same path again, naming the exact files, once you know the vocabulary.

---
# Part 2. Python from zero

The backend is about 9,300 executable statements of Python, measured by the tests (the project's working rule is 100% coverage, checked by the author before every merge; CI produces the report but does not enforce a number). This part
teaches the language in the order you meet it. Every section ends with where the idea shows up in
this repository. You can try any snippet: run `uv run python` in the project folder to get an
interactive prompt (`>>>`), type a line, press Enter, see the result. Press Ctrl+Z then Enter (on
Windows) to leave.

## 2.1 What a program is

A program is a list of instructions a computer follows from top to bottom. Python reads a file
(`something.py`), turns it into instructions and runs them. A line starting with `#` is a *comment*:
Python ignores it; it is for humans. A string between triple quotes at the top of a file, a class or
a function is a *docstring*: documentation that tools can read. This repository's files nearly
always start with one that explains the file's purpose, and those docstrings are often the best
explanation you will find.

```python
# This is a comment. Python skips it.
print("hello")          # prints: hello
```

## 2.2 Values and types

Everything in Python is a **value** with a **type**. The types you will meet most:

| Type | Example | What it is |
|---|---|---|
| `int` | `42`, `-7` | whole number, any size |
| `float` | `0.5`, `1e-6` | number with a fraction (approximate, see below) |
| `bool` | `True`, `False` | yes/no |
| `str` | `"abc"`, `'abc'` | text |
| `bytes` | `b"\x00\xff"` | raw bytes (files, hashes, images in memory) |
| `None` | `None` | "no value" |
| `list` | `[1, 2, 3]` | ordered, changeable collection |
| `tuple` | `(1, 2, 3)` | ordered, **unchangeable** collection |
| `dict` | `{"a": 1}` | key-to-value map |
| `set` | `{1, 2, 3}` | unordered, no duplicates |

`type(x)` tells you the type of `x`. Floats are *approximate*: `0.1 + 0.2` is `0.30000000000000004`
because computers store them in binary. That is why this repository compares thresholds rather than
checking exact equality, and why a face-similarity of `0.3544` is rounded to four places before it
is compared (`evaluation/measure_operating_point.py`).

## 2.3 Variables

A variable is a name attached to a value. `=` attaches (it does not mean "equals" as in maths).

```python
threshold = 0.3544        # attach the name `threshold` to the float 0.3544
threshold = 0.5           # now the name points at a different value
name, age = "Ada", 36     # attach two names at once (tuple unpacking)
a = b = 0                 # both names point at 0
```

Names are lower_snake_case for variables and functions, `CapitalizedWords` for classes, and
`UPPER_CASE` for constants (values that are never meant to change), for example `TAIL_FLOOR = 0.326`
in the evaluation script. Python does not stop you changing a constant; it is a convention, and the
type checker (Part 3) can enforce it with `Final`.

## 2.4 Operators

```python
7 + 2      # 9      addition
7 - 2      # 5
7 * 2      # 14
7 / 2      # 3.5    true division, always a float
7 // 2     # 3      floor division
7 % 2      # 1      remainder (modulo)
2 ** 10    # 1024   power
"ab" + "c" # "abc"  strings join with +
"ab" * 3   # "ababab"
a == b     # equal?          a != b   not equal?
a < b      # also <=, >, >=
a and b    # both true       a or b   either       not a   opposite
x is None  # identity: is it the very same object? Use `is` only for None/True/False
x in items # membership: is x one of the items?
```

`and`/`or` *short-circuit*: `a or b` does not look at `b` if `a` is already true. The idiom
`value or default` returns the default when `value` is empty/zero/`None`.

## 2.5 Strings

```python
name = "Ada"
f"Hello {name}, you are {2 + 2} years old"   # f-string: "Hello Ada, you are 4 years old"
name.upper(); name.lower(); name.strip()      # methods return NEW strings; strings never change
"a,b,c".split(",")                            # ["a", "b", "c"]
"-".join(["a", "b"])                          # "a-b"
name[0]; name[-1]; name[0:2]                  # "A", "a", "Ad"  (indexing and slicing; first index is 0)
len(name)                                     # 3
"x" in name                                   # False
```

An **f-string** (`f"..."`) puts values inside text. You will see them in error messages
throughout the code: `f"{package_key} is not installed"`.

## 2.6 Collections

**List**: ordered and changeable.

```python
faces = ["a", "b"]
faces.append("c")          # ["a", "b", "c"]
faces[0]                   # "a"
faces[-1]                  # "c" (last)
faces[1:]                  # ["b", "c"] (slice)
len(faces)                 # 3
faces.sort(); sorted(faces)# sort in place / return a new sorted list
```

**Tuple**: ordered, *unchangeable*, therefore safe to share, and usable as a dictionary key when all its items are themselves unchangeable (hashable). A
function that returns two things returns a tuple: `return accepted, correct`.

**Dict**: look things up by key.

```python
policy = {"match_threshold": 0.35, "margin": 0.02}
policy["margin"]                 # 0.02
policy.get("ceiling")            # None (no error if missing)
policy.get("ceiling", -1.0)      # -1.0 (default)
policy["version"] = "v1"         # add or replace
for key, value in policy.items(): ...
```

**Set**: no duplicates, fast "is it in here?".

```python
seen = {1, 2, 2, 3}       # {1, 2, 3}
2 in seen                 # True
```

A **JSON** document, which the API and many database columns use, is just nested dicts, lists,
strings, numbers, booleans and null (`None`). `json.dumps(obj)` turns Python values into text;
`json.loads(text)` turns text back.

## 2.7 Truth and conditionals

`if` runs a block only when a condition is true. The block is whatever is **indented** under it.
Indentation is not decoration in Python; it is the grammar.

```python
score = 0.42
if score >= 0.35:
    print("match")
elif score >= 0.20:
    print("unsure")
else:
    print("different")
```

What counts as false: `False`, `None`, `0`, `0.0`, `""`, `[]`, `{}`, `()`, `set()`. Everything else
is true. So `if items:` means "if the list is not empty".

A one-line conditional (a *ternary*): `label = "yes" if ok else "no"`. This appears in the
code as, for example, `"allow_fallback": len(providers) > 1`.

**Chained comparisons** read like maths: `-1.0 <= ceiling <= threshold <= 2.0`. This exact line is the
validity check on a decision policy in `backend/app/recognition/reasoner.py`.

Python 3.10+ also has `match`/`case` (structural pattern matching). This codebase mostly uses
`if`/`elif`, so you can skip it for now.

## 2.8 Loops

**`for`** repeats a block for each item of something iterable (list, tuple, dict, string, file,
range, generator).

```python
for face in faces:
    print(face)

for i in range(3):           # 0, 1, 2
    print(i)

for index, face in enumerate(faces):     # (0, "a"), (1, "b") ...
    ...

for a, b in zip(names, scores):          # walk two lists together
    ...
```

**`while`** repeats as long as a condition is true.

```python
failed = 0
while True:
    try:
        do_the_work()
        break              # leave the loop
    except Busy:
        failed += 1
        if failed >= 3:
            raise          # give up
```

This is nearly the real shape of `UnitOfWork.write` in
`backend/infrastructure/db/unit_of_work.py`: try the whole transaction; if the database is busy, roll
back and try again, up to a limit.

- `break` leaves the loop now. `continue` skips to the next item. A loop's `else:` block runs only if
  the loop was *not* ended by `break` (rarely used).
- **Never change a list while looping over it** with `for`; build a new one.

**Comprehensions** build a collection from a loop in one expression:

```python
squares = [n * n for n in range(5)]                 # [0, 1, 4, 9, 16]
big     = [n for n in numbers if n > 10]            # filter
lookup  = {p.key: p for p in packages}              # dict comprehension
unique  = {q.person for q in queries}               # set comprehension
```

**Generator expressions** are the same in parentheses and produce items lazily:
`sum(1 for q in queries if q.known)` counts without building a list. `any(...)` and `all(...)` ask
whether some/every item satisfies a test. `next(x for x in items if ok(x))` takes the first match
(a pattern you will meet whenever the code looks something up in a collection).

## 2.9 Functions

A function is a named, reusable block. `def` defines it; `return` hands back a value (without
`return`, the result is `None`).

```python
def accepted_at(queries, threshold, margin):
    taken = [q for q in queries if q[2] >= threshold and q[2] - q[3] >= margin]
    return len(taken), sum(1 for q in taken if q[4] and q[0] == q[1])

accepted, correct = accepted_at(queries, 0.3544, 0.02)   # a tuple, unpacked
```

**Parameters** can have defaults (`def f(x, k=5)`), be passed by name (`f(1, k=3)`), be collected
(`*args` for extras by position, `**kwargs` for extras by name), and be forced to be keyword-only by a
bare `*` (`def f(x, *, k)`), or positional-only by `/`. This repository uses keyword-only parameters
heavily so a call reads clearly: `register_package(session, package, new_id=..., clock=...)`.

**Functions are values.** You can pass one to another function. That is the basis of the code's
**dependency injection**: instead of calling `datetime.now()` inside, a function takes a `clock`
parameter, and the test passes a fake clock that always says 2026-01-01. Same for `new_id`
(`uuid.uuid4` in production, a seeded counter in tests).

```python
def stamp(clock):            # clock is a function that returns "now"
    return clock()
stamp(lambda: "frozen")      # lambda: a tiny one-expression function with no name
```

**Scope and closures.** A name assigned inside a function is local to it. A function defined *inside*
another can read the outer function's variables and keeps them alive: that is a **closure**.
`development_processing()` in `backend/api/development.py` defines `prepare` inside itself so that it
can see the `settings` argument.

**Recursion** is a function calling itself; this codebase hardly uses it.

## 2.10 Errors and exceptions

When something goes wrong Python *raises an exception* which unwinds the call stack until something
*catches* it. If nothing does, the program stops and prints a traceback (read it from the bottom: the
last line says what happened, the lines above say where).

```python
try:
    value = int(text)
except ValueError:
    value = 0                 # handle one specific kind of error
else:
    ...                       # runs only if no exception happened
finally:
    cleanup()                 # ALWAYS runs, even on error or return
```

- `raise ValueError("a policy has a version")` creates and throws one.
- `raise Other(...) from error` throws a new, clearer exception and remembers the original cause.
- Define your own with `class RegistrationError(Exception): ...`. The code defines dozens
  (`ProcessingUnavailableError`, `DatabaseBusyError` ...) so a caller can catch exactly the situation
  it can handle and let everything else propagate.
- **Fail closed**: when input is invalid or unknown, refuse rather than guess. The code does this at
  trust boundaries (a malformed checkpoint is refused, an unknown policy field is refused).
- `assert condition, "message"` states something that must be true; if not, it raises
  `AssertionError`. Used for "this cannot happen" and, heavily, in tests.

## 2.11 Classes and objects

A **class** is a blueprint for objects that bundle data and the functions that work on it.

```python
class Person:
    def __init__(self, name):        # runs when you write Person("Ada")
        self.name = name             # `self` is the object being built/used

    def rename(self, new_name):      # a method: a function that belongs to the object
        self.name = new_name

p = Person("Ada")
p.rename("Grace")
p.name                               # "Grace"
```

- **Attributes** are values on an object (`self.name`). **Methods** are functions on it.
- **Inheritance**: `class B(A)` makes `B` start as a copy of `A` and add or replace parts.
- **Properties**: `@property` makes a method look like an attribute (`supervisor.state`).
- **Dunder ("double underscore") methods** customise behaviour: `__init__` (build), `__repr__` (how it
  prints), `__eq__` (what == means), `__post_init__` (a dataclass hook, below).
- **`@staticmethod` / `@classmethod`**: functions attached to the class rather than an object.
  `ProcessingRequestV1.parse(...)` is a classmethod that builds a request from a dict.

### Dataclasses

A `@dataclass` writes `__init__`, `__repr__` and `__eq__` for you from a list of fields.

```python
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class DecisionPolicy:
    version: str
    min_detection_score: float
    match_threshold: float
    margin: float
    new_identity_ceiling: float

    def __post_init__(self) -> None:        # runs after construction: validate here
        if not -1.0 <= self.new_identity_ceiling <= self.match_threshold <= 2.0:
            raise ValueError("the thresholds must satisfy ...")
```

`frozen=True` makes instances unchangeable (so they can be shared safely and used as dictionary keys);
`slots=True` saves memory and forbids stray attributes. This is a real class from
`backend/app/recognition/reasoner.py`. The pattern **"make invalid states impossible to construct"**
(validate in `__post_init__`, then trust the object everywhere) is used all over the project.

### Enums

An `Enum` is a fixed set of named values. `StrEnum` makes each value a string.

```python
from enum import StrEnum

class IdentityState(StrEnum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    MERGED = "MERGED"
    FORGOTTEN = "FORGOTTEN"
    DELETED = "DELETED"
```

The state of nearly everything in the database (a job, a run, a representation, a source) is one of
these. The database stores the text, and a `CHECK` constraint (Part 6) refuses any other text.

### Protocols and abstract classes

A **Protocol** (from `typing`) describes "anything that has these methods", without inheriting. It
lets a test substitute a fake. `WorkerHandle` in `backend/ml/supervisor/process.py` is one: the
supervisor needs `connection`, `is_alive()` and `kill()`, and a real process or a test double both
fit.

## 2.12 Modules, packages and imports

A file `foo.py` is a **module**; a folder with `__init__.py` is a **package** (Python also allows folders without one, "namespace packages"; this project uses `__init__.py`). `import` makes names
from another module available.

```python
import hashlib                                  # use as hashlib.sha256(...)
from pathlib import Path                        # use as Path(...)
from backend.app.recognition.reasoner import DecisionPolicy
import numpy as np                              # `as` gives a short alias
```

The path `backend.app.recognition.reasoner` mirrors the folder structure. Running
`python -m backend.api.host` runs the module `backend/api/host.py` as a program (`-m` means "module").
The block `if __name__ == "__main__":` at the bottom of a file runs only when the file is run directly,
not when imported.

The standard library (included with Python) gives you most tools: `pathlib`, `json`, `hashlib`,
`uuid`, `datetime`, `threading`, `multiprocessing`, `subprocess`, `socket`, `sqlite3`, `argparse`,
`logging`, `enum`, `dataclasses`, `typing`, `collections`, `functools`, `itertools`, `contextlib`.
Third-party packages are installed with `uv` and listed in `pyproject.toml`.

## 2.13 Type hints

Python does not require declaring types, but this project writes them everywhere and checks them with
`mypy --strict`. They are notes to humans and to the checker; they do not change how the program runs.

```python
def decide(assessment: RecognitionAssessment) -> RecognitionDecision: ...
threshold: float = 0.35
names: list[str] = []
lookup: dict[str, int] = {}
maybe: str | None = None            # a str or None   (older style: Optional[str])
callback: Callable[[int], str]      # a function taking an int, returning a str
pair: tuple[int, str]               # exactly two items
anything: Any                       # opt out of checking for this value
LIMIT: Final = 5                    # a constant
```

`T = TypeVar("T")` creates a **generic**: `def read(self, work: Callable[[Session], T]) -> T`
says "whatever type `work` returns, `read` returns that same type".

`mypy` reads the hints and tells you *before running* that you passed a `str` where a `float` was
expected. `# type: ignore[code]` silences one line when the checker is wrong; the project keeps these
to a minimum and records why.

## 2.14 Files, paths and bytes

```python
from pathlib import Path
folder = Path("local-models") / "state"          # `/` joins path parts, on any OS
folder.mkdir(parents=True, exist_ok=True)
file = folder / "policy.json"
file.write_text("{}", encoding="utf-8")
text = file.read_text(encoding="utf-8")
data = file.read_bytes()
file.exists(); file.is_dir(); file.stat().st_size
for child in folder.glob("*.json"): ...
```

`bytes` are raw data. A **hash** (`hashlib.sha256(data).hexdigest()`) turns any amount of data into a
fixed-size fingerprint: change one bit of the input and the fingerprint changes completely. The code
uses SHA-256 to identify files (an imported photograph, a model file) and to verify that what was
read is what was recorded.

**Atomic writes.** If the power fails halfway through writing a file you are left with half a file.
So the storage layer writes to a temporary file in a *staging* folder, flushes it to disk, then
**renames** it into place (a rename is all-or-nothing). Look for "staged writes" in
`backend/infrastructure/storage/`.

## 2.15 Context managers (`with`)

`with` guarantees cleanup, even if an error occurs.

```python
with open(path, "rb") as handle:       # the file is closed when the block ends
    data = handle.read()

with self._write() as session:          # a database session is closed (and rolled back on error)
    ...
with lock:                              # a lock is released
    ...
```

You can write your own with `contextlib.contextmanager` or a class with `__enter__`/`__exit__`
(`open_library(...)` in `backend/app/lifecycle.py` is one: on exit it releases the library lock and
disposes the database engine).

## 2.16 Iterators and generators

An **iterator** produces one item at a time. A **generator function** uses `yield` instead of `return`
and pauses between items, so a huge sequence never sits in memory.

```python
def numbers():
    n = 0
    while True:
        yield n
        n += 1
```

Tests use generators with `yield` in **fixtures** (set something up, `yield` it to the test, clean up
afterwards).

## 2.17 Decorators

A decorator is a function that wraps another function, written with `@` above it.

```python
@dataclass(frozen=True)          # wraps a class
class X: ...

@router.post("/import", status_code=201)    # registers this function as the handler of POST /import
async def import_source(...): ...

@pytest.fixture                  # tells pytest "this function builds a test dependency"
def clock(): ...
```

You can use decorators long before you can write one. Read `@something(...)` as "register or modify
the function below with these settings".

## 2.18 Concurrency: threads, processes and async

A program often needs to do several things "at once". Python offers three tools; this project uses all
three, for different reasons.

- **Threads** (`threading`): several lines of execution inside one process sharing memory. Python's
  *global interpreter lock* (GIL) lets only one thread run Python code at a time, so threads help with
  *waiting* (disk, network), not heavy computing. Danger: two threads changing the same data. Fix:
  a `Lock` so only one at a time enters a section. The scheduler runs the processing work in a thread
  so the web server stays responsive.
- **Processes** (`multiprocessing`, `subprocess`): separate programs with separate memory. They can
  truly run in parallel and a crash in one cannot corrupt another. The ML worker is a separate
  process started with the **spawn** method (a fresh interpreter that re-imports your code; this is
  why scripts that start workers need an `if __name__ == "__main__":` guard on Windows). Processes
  talk through **pipes** and **shared memory** (the image bytes are placed in a shared block so they
  are not copied through the pipe).
- **Async** (`async def` / `await`, library `asyncio`): one thread that switches between many tasks
  at the points where each says `await` ("I am waiting; run someone else"). FastAPI and the WebSocket
  server are async. Rule: never run a slow, blocking call directly in an `async def`; hand it to a
  thread (`anyio.to_thread.run_sync(...)`) as the startup code does for opening the library.

```python
async def handler():
    data = await fetch()         # pause here, let other tasks run
    return data
```

## 2.19 Putting it together: read a real function

From `backend/app/recognition/reasoner.py` (shortened). Read it line by line with what you now know.

```python
def decide(self, assessment: RecognitionAssessment) -> RecognitionDecision:
    policy = self.policy

    if assessment.quality.detection_score < policy.min_detection_score:
        return abstain(Reason.LOW_QUALITY)
    if not assessment.complete:
        return abstain(Reason.RETRIEVAL_INCOMPLETE)
    if not assessment.groups:
        return create(Reason.NO_CANDIDATE)
    top = assessment.groups[0]
    if top.best_similarity >= policy.match_threshold:
        margin = assessment.margin
        if margin is not None and margin < policy.margin:
            return abstain(Reason.AMBIGUOUS_CANDIDATES)
        if top.identity_id is None:
            return abstain(Reason.UNRESOLVED_NEIGHBOUR)
        return RecognitionDecision(RecognitionOutcome.MATCH_EXISTING, Reason.MATCHED, ...)
    if top.best_similarity < policy.new_identity_ceiling:
        return create(Reason.NOT_SIMILAR)
    return abstain(Reason.UNCERTAIN_SIMILARITY)
```

What it says, in plain words: *Check quality first. If the search was incomplete, do not trust it.
If there is nobody to compare with, this is a new person. Otherwise look at the best candidate: if it
is similar enough and clearly ahead of the runner-up, it is a match; if it is so dissimilar it is
clearly someone else, create a new identity; anything in between, abstain.* Every `return` is a
different decision with a recorded reason. That is the whole recognition policy in thirty lines.

**Exercise.** Without running anything: what does this function return for a face with detection score
0.3 when `min_detection_score` is 0.5? (Answer: abstain, reason `LOW_QUALITY`, before anything else is
looked at.)

---
# Part 3. The tools around the code

Code is only half a project. The other half is the machinery that installs it, runs it, checks it
and keeps its history. This part explains each tool, and the commands you will actually type.

## 3.1 The terminal and the shell

A **terminal** is a window where you type commands. A **shell** is the program inside it that
interprets them (PowerShell, or Git Bash on this machine). A command is a program name followed by
*arguments*: `git status`, `uv run pytest -q`. Flags start with `-` or `--` (`-q` quiet, `--cov`
coverage). `cd folder` changes directory; `ls`/`dir` lists files. Environment variables (named values
a program can read) are set with `export NAME=value` in Git Bash or `$env:NAME = "value"` in
PowerShell. The project passes secrets and options this way (for example `FACEIDENTIFY_LAUNCH_TOKEN`
and `FACEIDENTIFY_ORT_GPU_DIR`).

## 3.2 uv: Python versions, environments and packages

- A **virtual environment** (`.venv/`) is a private folder of installed packages for one project, so
  two projects can use different versions without clashing.
- **`pyproject.toml`** lists the project's Python version, its dependencies and the settings of
  pytest, ruff, mypy and coverage. **`uv.lock`** records the exact version of every package so every
  machine installs the same thing.
- **`uv sync`** creates `.venv` and installs everything from the lock. **`uv run <command>`** runs a
  command inside that environment, so you never "activate" anything: `uv run pytest`,
  `uv run python -m backend.api.host`, `uv run ruff check .`.
- The dependency list at the time of writing: `fastapi`, `uvicorn`, `websockets` (the web server),
  `sqlalchemy`, `alembic` (database), `usearch` (vector index), `onnxruntime`, `numpy`, `pillow`
  (models, arrays, images). Development only: `pytest` (+ `pytest-asyncio`, `pytest-cov`), `httpx`,
  `hypothesis`, `ruff`, `mypy`, `onnx`.

## 3.3 pytest: how the tests work

A **test** is a function that runs your code and asserts what must be true. pytest finds files named
`test_*.py`, runs functions named `test_*`, and reports failures.

```python
def test_a_policy_with_matching_off_never_matches(...):
    decision = IdentityReasoner(OFF).decide(assess(retrieval(candidate(1, 1.0, identity=7)), GOOD))
    assert decision.outcome is RecognitionOutcome.ABSTAIN
```

Concepts you will meet in the test files:

- **Fixtures** (`@pytest.fixture`): reusable set-up. A test asks for one by naming it as a parameter.
  `tmp_path` is a built-in fixture giving a fresh empty folder. `clock` and `new_id` are this
  project's fixtures giving a frozen clock and predictable ids.
- **`@pytest.mark.parametrize`**: run one test over many inputs.
- **`pytest.raises(SomeError)`**: assert that a block raises.
- **`monkeypatch`**: temporarily replace something (an environment variable, a function) for one
  test.
- **Markers**: tests are tagged by folder (`unit`, `integration`, `contract`, `property`, `recovery`,
  `security`, `concurrency`) and some are excluded by default (`e2e`, `ml_eval`, `benchmark`,
  `hardware`) because they need real models, a GPU or minutes of time. Run those on purpose with
  `-m e2e`.
- **Test doubles**: fakes that stand in for slow or dangerous parts (a fake perception that "sees" a
  face in every image, a fake clock). Dependency injection (Part 2.9) is what makes this possible.
- **Property-based tests** (`hypothesis`): instead of one hand-picked example, the library generates
  hundreds of random inputs (sequences of merges and splits, say) and checks that an *invariant*
  always holds. See `tests/property/`.
- **Coverage** (`--cov`): which lines and branches the tests ran. This project's working rule is **100%** (a rule followed by running it, not a number CI enforces), so a
  line that no test exercises is itself a failure.
- **Mutation testing by hand**: after writing a guard, the author deliberately breaks the guard and
  confirms a test fails. A test that still passes when the code is broken is not testing anything.
  You will see "mutation" mentioned throughout `docs/implementations/`.

Commands:

```bash
uv run pytest -q                     # the fast default suite
uv run pytest tests/unit -q          # just the unit tests
uv run pytest -k reasoner            # only tests whose name contains "reasoner"
uv run pytest --cov                  # with coverage (the working rule is 100%)
uv run pytest -m e2e tests/e2e       # the real-model test (needs the local weights)
```

## 3.4 ruff and mypy: automatic reviewers

- **ruff** is a linter and formatter. `uv run ruff format .` rewrites files to the house style;
  `uv run ruff check .` reports probable mistakes and style problems (unused imports, lines over 100
  characters, ...). Both are required clean.
- **mypy** is the type checker (`strict` mode). `uv run mypy` checks the Windows view;
  `uv run mypy --platform linux` checks what CI's Linux job sees (Windows-only calls need a
  `sys.platform == "win32"` guard so the Linux check does not fail).

## 3.5 Git: history, branches and pull requests

**Git** records every version of every file as a chain of **commits**, each with a message, an
author and a parent. A **branch** is a movable name for a line of commits. `main` is the shared,
protected line; you never commit to it directly.

The daily loop in this project:

```bash
git switch -c feat/short-description    # start a branch  (type/kebab-name)
# ... edit files ...
git status                              # what changed?
git add path/to/file                    # stage it for the next commit
git commit -m "feat(api): add X"        # record it (Conventional Commits: type(scope): summary)
git push -u origin feat/short-description
gh pr create ...                        # open a pull request on GitHub
```

- **Conventional Commits** headers: `feat:` new capability, `fix:` bug fix, `docs:`, `test:`,
  `chore:`, `build:`, `ci:`, `refactor:`; header at most 72 characters; small commits sliced by
  kind. A hook (`.githooks/commit-msg`) rejects a bad header.
- A **pull request** (PR) asks to merge a branch into `main`. GitHub shows the difference and runs the
  checks. `main` accepts only **rebase merges** after all required checks pass (a rebase replays the
  branch's commits on top of the current `main`, keeping history a straight line).
- **Rebase conflicts** happen when two branches edited the same lines (often `PROJECT_STATUS.md` or
  `CONTEXT.md`). You resolve them by keeping both sides' meaning, then continue.
- **Worktrees** (`git worktree add`) give you a second checkout of the repository in another folder;
  the review procedure uses a disposable one so the reviewer never touches your files.
- Never `git push --force` to `main`. `--force-with-lease` on your own branch is the safe form.

## 3.6 GitHub Actions: continuous integration (CI)

`.github/workflows/ci.yml` tells GitHub to run checks on every pull request. The jobs, as named in the
PR check list:

| Job | What it checks |
|---|---|
| Branch name | the branch is called `type/kebab-name` |
| Commit messages | every new commit header is a valid Conventional Commit |
| Static validation | `ruff format --check`, `ruff check` and `mypy` on a Linux runner (this is why Windows-only calls need a platform guard) |
| Backend fast tests | the whole default Python suite with coverage, on Windows |
| Frontend | regenerates the API types and fails if they differ from the committed ones, then typecheck, lint (warnings are errors), tests and the production build |
| Desktop shell | builds the front end, then `cargo fmt --check`, `cargo clippy -D warnings`, `cargo test`, the Rust tests against the real Python backend, and the end-to-end desktop workflow |

A PR is mergeable only when all are green **on the exact head commit** (a later push means waiting
again).

## 3.7 The other tools you will see

- **Alembic**: database migrations (Part 6). **`alembic.ini`**/`backend/alembic/`.
- **npm** and **Node**: the JavaScript package manager and runtime for the front end. `npm install`,
  `npm test`, `npm run build`. **Workspaces**: the root `package.json` lists `frontend` as a workspace.
- **Vite**: the development server and bundler for the front end. **Vitest**: the front-end test
  runner. **oxlint**: the front-end linter. **TypeScript** (`tsc`): the type checker.
- **Cargo**: Rust's build tool and package manager (`desktop/src-tauri/Cargo.toml`).
- **gh**: GitHub's command-line tool (`gh pr create`, `gh pr checks`).
- **codex**: the independent code-review tool used in the review procedure (read-only sandbox).
- **Claude Code** (this assistant): reads `AGENTS.md` and `.agents/` for the project's rules.

---
# Part 4. The ideas behind recognition: vectors, models and thresholds

You do not need advanced mathematics to follow this project. You need five ideas: a vector, a dot
product, a neural network as a function, a threshold, and the difference between "usually right" and
"safe to act on". This part builds them one at a time.

## 4.1 Vectors: a list of numbers is a point in space

A **vector** is an ordered list of numbers: `[0.2, -1.5, 3.0]`. The number of entries is its
**dimension**. A vector of two numbers is a point on a sheet of paper; three, a point in a room; 512
numbers, a point in a space we cannot picture but whose maths works identically.

Two operations matter:

- **Length (norm).** For `[x, y]` the length is `sqrt(x*x + y*y)` (Pythagoras). In general, add the
  squares of all entries and take the square root. A vector of length 1 is a **unit vector**.
- **Dot product.** Multiply the matching entries of two vectors and add the results:
  `[1, 2, 3] . [4, 5, 6] = 1*4 + 2*5 + 3*6 = 32`.

**Cosine similarity** measures how much two vectors point the same way, ignoring length:

```
cosine(a, b) = (a . b) / (length(a) * length(b))
```

It is `1` if they point the same way, `0` if they are at right angles (unrelated), `-1` if they are
opposite. **If both vectors are unit vectors the lengths are 1, so cosine similarity is just the dot
product.** That is why the project normalises every face vector to length 1 ("L2 normalisation") and
then compares with a plain dot product: it is fast, and a single number between -1 and 1 results.

In NumPy (Part 4.2) a single comparison is `float(a @ b)`. You will see exactly that in the
evaluation script: `float(a[2] @ b[2])`.

## 4.2 NumPy: arrays

**NumPy** is the library for working with numbers in bulk. Its central object is the **array**
(`ndarray`): a grid of numbers, all of one **dtype** (such as `float32`, `uint8`), with a **shape**.

```python
import numpy as np
v = np.array([1.0, 2.0, 3.0], dtype=np.float32)   # shape (3,)   a vector
m = np.zeros((2, 3))                               # shape (2, 3) a matrix: 2 rows, 3 columns
img = np.zeros((480, 640, 3), dtype=np.uint8)      # shape (height, width, channels): a colour image
```

- An **image** is an array: rows of pixels, each pixel three numbers (red, green, blue) from 0 to 255
  (`uint8` = unsigned 8-bit integer). "Decode an image" means turning a JPEG/PNG file's bytes into this
  array (`backend/infrastructure/media`, using Pillow).
- A **tensor** is the word machine learning uses for an array of any number of dimensions.
- **Operations act on whole arrays at once** (this is called *vectorisation* and is much faster than a
  Python `for` loop): `a + b`, `a * 2`, `a @ b` (matrix/dot product), `a.T` (transpose), `np.linalg.norm(a)`.
- **Slicing** works like lists, in several dimensions: `img[10:20, 30:40]` is a rectangle of pixels
  (this is how a face is cropped).
- **Broadcasting** lets arrays of different shapes combine when one can be stretched to match
  (`matrix @ vector` scoring one vector against a whole gallery in a single operation, as
  `queries_of` does).
- `np.percentile(values, 99.9)` is the value below which 99.9% of `values` fall.

## 4.3 Machine learning in one page

A **neural network** is a very large function: it takes numbers in (a picture's pixels) and gives
numbers out (a vector, or a set of box coordinates and scores). The function has millions of
adjustable **weights**. **Training** means showing the network many examples with known answers and
nudging the weights so its answers get closer (a *loss* function scores how wrong it is; *gradient
descent* nudges the weights downhill). **Inference** means using the finished, frozen network to
get answers for new input. **FaceIdentify never trains**: it only runs ready-made models, so there is
no training code, no GPU training and no dataset of faces to label. (Training and "retraining" appear
in the specs only as future ideas and as an unused job type.)

A **convolutional neural network (CNN)** is the standard design for images. A *convolution* slides a
small grid of weights (a *kernel*) across the image, producing a map of where a pattern (an edge, a
curve, later an eye) appears; many such layers stacked learn patterns of increasing complexity. The
two models this project uses are CNNs. A **Vision Transformer** is a newer design that cuts the image
into patches and lets them attend to each other; it is mentioned as a model family, not used here.

### ONNX and ONNX Runtime

A trained model is a file of weights plus a description of the calculations. **ONNX** ("Open Neural
Network Exchange") is a standard file format for that, so a model trained in PyTorch can be run by
other software. **ONNX Runtime** is the engine that loads an `.onnx` file and executes it quickly.
It runs a model through an **execution provider**, a back-end for particular hardware:

| Provider | Runs on | In this project |
|---|---|---|
| `CPUExecutionProvider` | your processor | always available; the default and the fallback |
| `CUDAExecutionProvider` | an NVIDIA graphics card, via CUDA and cuDNN | verified on the RTX 4070 (2026-10-07) |
| `TensorrtExecutionProvider` | NVIDIA, with TensorRT's optimiser | [researched]; not used |
| OpenVINO, DirectML | Intel / any Windows GPU | [researched]; not used |

**CUDA** is NVIDIA's platform for running general computations on its GPUs; **cuDNN** is its library of
fast neural-network building blocks; **cuBLAS** does fast matrix maths. They are separate proprietary
downloads, which is why the GPU runtime is installed into a machine-local folder and never committed.
A **GPU** has thousands of small cores and is far faster than a CPU for the big matrix arithmetic of a
network: on this machine detecting and embedding a face took about 0.05 s on CUDA and about 0.6 to 1 s
on CPU.

**The worker never silently falls back.** If CUDA was requested and cannot start, ONNX Runtime would
quietly use the CPU; the worker refuses that (`backend/ml/worker/onnx_session.py`) and reports an
error, because *the backend* decides what a fallback is allowed to be and must record which hardware
actually produced each result.

## 4.4 The face pipeline, stage by stage

```
photograph --decode--> pixel array --DETECT--> boxes + landmarks --ALIGN--> 112x112 crop --EMBED--> 512 numbers
```

1. **Detection.** Find where faces are: for each, a bounding box, a confidence score, and five
   **landmarks** (two eyes, nose, two mouth corners). The model is **SCRFD** (a fast detector from the
   InsightFace project). Its postprocessing is plain code you can read in
   `backend/ml/perception/detection.py`: keep scores above a threshold, convert the model's outputs
   to boxes, then **non-maximum suppression (NMS)** removes duplicate overlapping boxes (keep the best,
   drop boxes that overlap it too much, measured by *intersection over union*).
   **Letterboxing** resizes the image to the model's fixed input size while keeping its proportions,
   padding the rest.
2. **Alignment.** People tilt their heads. Using the landmarks, compute the **similarity transform**
   (rotation + scale + shift) that moves the eyes, nose and mouth to standard positions, and warp the
   face to a fixed 112 by 112 image (`backend/ml/perception/alignment.py`). The embedder was trained
   on faces aligned this way, so skipping this ruins accuracy.
3. **Embedding.** The second model, **ArcFace** (a ResNet-50 CNN), turns the aligned face into a
   vector of 512 numbers called an **embedding** (or "representation" in this project's vocabulary).
   It is trained with **metric learning**: a loss function (ArcFace's is an *angular margin* loss)
   pulls embeddings of the same person together and pushes different people apart, so that
   *distance in this space means difference of identity*. Then we L2-normalise it.
4. **Comparison.** Two faces are compared by the cosine similarity of their embeddings (Part 4.1).

The released weights are the **`buffalo_l`** pack from InsightFace (SCRFD-10GF for detection, ArcFace
ResNet-50 for recognition). Their licence allows non-commercial research use only, which the owner
accepted for personal use and the project records as a **release blocker**
(`docs/research/reference-model-selection.md`, `docs/research/licensing-and-commercialization.md`).

## 4.5 What "recognition" means: four distinct problems

People use "face recognition" for several tasks. Keeping them apart is the key to understanding the
decision code.

- **Verification (1:1).** Are these two photos the same person? Compute one similarity and compare it
  with a threshold.
- **Identification (1:N).** Who among everyone I know is this? Compare with every known face and take
  the best.
- **Closed-set identification.** The person is guaranteed to be someone in the gallery. The best match
  is the answer. Easy, and unrealistic.
- **Open-set identification.** The person may be a stranger. The system must say "someone I know" *or*
  "nobody I know". This is the real problem, and the one FaceIdentify solves. It needs two
  thresholds and a way to abstain.

Related ideas:

- **Re-identification** and **tracking**: following one subject across frames or cameras (needed for
  video, [designed] for M6/M7).
- **Clustering** (DBSCAN, HDBSCAN, agglomerative): grouping faces that probably belong together
  without labels, to discover recurring unknown people. [researched]
- **Template / prototype**: one summary vector per person, built from many faces. The project instead
  keeps *every* representation and takes the best-matching one per identity ("multiple templates").

## 4.6 Thresholds, errors and the decision

For one face and its best candidate, with similarity `s`:

- If `s` is **high** it is probably the same person.
- If `s` is **low** it is probably a different person.
- In between: **uncertain**.

Two kinds of wrong answer exist, and they cost differently:

- A **false accept**: the system says "same person" but it was not. Worst case for FaceIdentify: it
  puts a stranger's face into someone's memory.
- A **false reject**: the system fails to recognise someone it knows. Cheaper: you fix it by hand.

The policy has these knobs (`DecisionPolicy`, `backend/app/recognition/reasoner.py`):

| Field | Meaning |
|---|---|
| `min_detection_score` | below this detector confidence the face is not decided at all |
| `match_threshold` | the best candidate must score at least this to be considered a match |
| `margin` | and must beat the runner-up (another person) by at least this much |
| `new_identity_ceiling` | below this the face is clearly nobody known: create a new identity |
| (between the two) | abstain |

Why a **margin**? If two different known people both score 0.60, the system cannot tell which; a
match requires a clear lead.

### Measuring a policy

Choosing numbers by feel is how systems fail, so the project measures them (`evaluation/`):

- **Precision**: of the faces the system accepted, the share that was correct. *Recall*: of the faces it
  could have accepted correctly, the share it did. Raising the threshold raises precision and lowers
  recall.
- **Selection half / final half**: split the *people* (not the photos) into two groups that share
  nobody. Choose the threshold on one group; judge it on the other, which took no part in the choice.
  Doing otherwise "marks your own homework" (overfitting). This is the most important methodological
  rule in the evaluation code.
- **Leave-one-out**: when a photo is a query, it is removed from the gallery it is compared with.
- **Wilson interval**: a 95% range for a proportion measured on few samples. "40 of 51 correct" is
  not exactly 78.4%; the honest statement is "between about 65% and 87%".
- **Label noise**: the evaluation's labels (which person is in which photo) came from Wikimedia
  Commons categories and are unverified; a wrong label looks like a false accept or false reject.
- **The result so far** (`docs/research/measured-operating-point.md`): the first rule overfitted
  (100% precision on selection, 78% on the held-out half), the owner's conservative rule still left five
  false accepts of 40, so **automatic acceptance is disabled** until a larger verified evaluation set
  exists. Once the real host profile reads that policy, a face with candidates will abstain and wait
  for you.
- **Calibrated vs uncalibrated.** A *calibrated* score would be a true probability ("0.9 means right
  nine times out of ten"). Ours are raw cosines, never probabilities; "calibrated" in this project only
  means "the thresholds were measured". The mode stays `UNCALIBRATED`, and the screen says so.

## 4.7 Approximate nearest-neighbour search

With ten thousand stored vectors, comparing a new face against all of them is instant. With ten
million it is slow. An **approximate nearest-neighbour (ANN)** index finds *almost certainly* the
closest vectors without checking all of them. **HNSW** (hierarchical navigable small world) is the
standard method: a layered graph where you hop towards the target. **USearch** is the library this
project uses (alternatives considered: FAISS, Voyager, pgvector). Because the answer is approximate,
the project never trusts the index alone: it re-reads each candidate from SQLite and **revalidates**
(is it still active? its identity still alive?) before using it.

The index is **derived** data (Part 1.3): if it is lost or stale, it is rebuilt from SQLite.

## 4.8 Video and hardware vocabulary [designed / researched]

None of this is built yet (movies are M6, cameras M7), but the specs and old research list use it:

- **FFmpeg** (the Swiss-army knife for video), **PyAV** (Python bindings to it), **OpenCV**
  (computer-vision library). **Decoding** turns compressed video into frames; **NVDEC** is the NVIDIA
  chip block that decodes in hardware. **Frame sampling** (look at every Nth frame), **keyframes**
  (full frames a video can be sought to), **scene-change detection** (skip near-identical frames).
- **Multi-object tracking** (ByteTrack, DeepSORT, StrongSORT, BoT-SORT): link detections across frames
  into **tracklets**; **track association** and **stitching** join broken ones.
- **Hardware optimisation**: **SIMD** (one CPU instruction on many numbers), **multithreading**,
  **multiprocessing**, **asynchronous pipelines** (decode the next frame while the GPU works),
  **pinned memory** and **zero-copy** transfers (avoid slow copies between CPU and GPU memory),
  **GPU batching** (send many faces in one call), **heterogeneous CPU/GPU pipelines**.
- **Face quality assessment** (blur, pose, occlusion, resolution) to pick the best face from a track.
- **Continual learning**: the project explicitly does *not* retrain networks to learn new people; it
  adds stored vectors, which is cheaper and reversible.

---
# Part 5. The topic map: every topic from the old research list, and where it stands

The previous version of this file was an unexplained list of topics to research. This part keeps
**every one of them**, groups them, explains each in a sentence, and says what the project did with it.
"Chosen" means it is in the locked stack (`docs/research/tech-stack.md`). Deeper explanations of the
ones that matter are in Parts 4, 6 and 7.

## 5.1 Computer vision

| Topic | What it is | Status |
|---|---|---|
| Computer vision | Getting meaning out of images and video | the whole product |
| Face detection | Finding faces and their boxes | [built] SCRFD |
| Face alignment | Warping a face to a standard pose using landmarks | [built] similarity transform to 112x112 |
| Face recognition | Deciding who a face is | [built] embeddings + the reasoner |
| Face verification | Same person or not (1:1) | the base operation; used inside identification |
| Open-set recognition | Known people recognised, strangers rejected | [built] the core design (Part 4.5) |
| Closed-set recognition | Everyone is known | not the goal |
| Face re-identification | Matching a person across cameras/frames | [designed] for video (M6/M7) |
| Metric learning | Training so distance means identity | how ArcFace was trained; we only use the result |
| Contrastive learning | Training by pulling similar pairs together, pushing others apart | background to metric learning |
| Triplet loss | A loss using (anchor, same, different) triples | background (FaceNet-style); ArcFace uses an angular margin instead |
| Self-supervised visual learning | Learning from unlabelled images | [researched]; no training here |
| Face quality assessment | Scoring blur, pose, occlusion, resolution | [partly built] only the detector's score gates a face; fuller quality is [designed] |
| Occlusion handling | Faces partly hidden (masks, hands, glasses) | [researched]; shows up as low scores and abstentions |

## 5.2 Model architectures

| Topic | What it is | Status |
|---|---|---|
| CNNs | Convolutional networks (Part 4.3) | SCRFD and ArcFace-ResNet50 are CNNs |
| Vision Transformers | Attention-based image models | [researched] |
| Hybrid CNN/Transformer | Mixtures of both | [researched] |
| Siamese networks | Two identical networks comparing a pair | background to verification |
| Triplet networks | Networks trained on triples | background |
| Metric-learning architectures | Networks built to output comparable embeddings | what ArcFace is |

## 5.3 Identity representation

| Topic | What it is | Status |
|---|---|---|
| Feature descriptors | Hand-made image features (older methods) | superseded by embeddings |
| Embeddings | A face as a 512-number vector | [built] the "Representation" |
| Identity prototypes | One summary vector per person | not used; we keep all vectors |
| Multiple-template recognition | Many vectors per person, best match wins | [built] |
| Template aggregation | Combining vectors (average, etc.) | not used |
| Prototype learning | Learning a representative vector | [researched] |

## 5.4 Tracking (video)

Multi-object tracking, tracking-by-detection, re-identification, tracklets, track association, track
stitching, and the trackers ByteTrack, DeepSORT, StrongSORT, BoT-SORT: all [designed] for movies and
cameras (M6, M7). The distinction the research list wanted: a *generic* tracker follows boxes by motion;
a *face-aware* one also uses the face embedding, so a person who leaves and returns is reconnected.
Nothing of this is built.

## 5.5 Unknown-person discovery

Clustering (DBSCAN, HDBSCAN, agglomerative, online/incremental clustering) groups faces that probably
belong to the same unknown person. [researched]. The built system takes a simpler route: an unknown
face becomes a new *Identity* immediately, and you merge duplicates by hand (merge is atomic and
reversible in history).

## 5.6 Video and hardware

FFmpeg, PyAV, OpenCV, NVDEC, hardware video decoding, frame sampling, scene-change detection,
keyframes: **FFmpeg/ffprobe and PyAV are the chosen video foundation** for M6; **OpenCV is not a
dependency** (owner decision 2026-10-02: Pillow and NumPy handle still images). Nothing video-related
is built.

CUDA, cuDNN, TensorRT, ONNX Runtime, OpenVINO, CPU SIMD, multithreading, multiprocessing,
asynchronous pipelines, pinned memory, GPU batching, zero-copy memory, CPU/GPU heterogeneous
pipelines: **ONNX Runtime is the chosen runtime; CUDA and cuDNN are verified**; DirectML is the
documented Windows-GPU option; TensorRT and OpenVINO are [researched]. The worker uses spawned
processes and shared memory today; batching and pinned memory are future optimisations.

## 5.7 The research checklist, with its answers

The old list asked questions. Here are the answers the project has reached.

| Question | Answer |
|---|---|
| Face detection: RetinaFace, SCRFD, YOLO-face, MTCNN? | **SCRFD** (from `buffalo_l`); the model is replaceable behind a contract |
| Face representation: ArcFace, FaceNet, AdaFace, MagFace, InsightFace? | **ArcFace** ResNet-50 from the InsightFace `buffalo_l` pack; chosen by documented criteria in `docs/research/reference-model-selection.md` |
| Tracking: ByteTrack, DeepSORT, StrongSORT, BoT-SORT? | open; M6/M7 |
| Vector search: FAISS, HNSW, pgvector? Is an index even needed for thousands of identities? | **USearch (HNSW)**, kept rebuildable; FAISS/Voyager are documented alternatives. For thousands of vectors an exact scan would also work, but the index is built so the design scales and the rebuildable-index discipline is exercised early |
| Video: FFmpeg, OpenCV, PyAV? | FFmpeg + PyAV; OpenCV not baseline |
| Local GPU inference: PyTorch, ONNX Runtime, TensorRT, CUDA? | **ONNX Runtime** with CUDA on the RTX 4070 and CPU as fallback; PyTorch is not a dependency of this repository; the stack decision allows it only for experimentation and export outside the shipped app and it is not shipped |
| Storage: PostgreSQL or SQLite? | **SQLite in WAL mode**; PostgreSQL only if measured write contention demands it |
| Desktop: web UI + local server, Electron, Tauri, native? | **Tauri** shell + React front end + a local FastAPI sidecar |
| Clustering for unknown identities? | not built (Part 5.5) |
| Face quality assessment? | detector score only so far |
| Open-set recognition? | built as the core policy, measured conservatively (Part 4.6) |
| Continual / incremental learning? | no network retraining; adding and correcting stored vectors and identities is the "learning" |
| Local natural-language querying? | deliberately later; deterministic structured search comes first |

The concepts the old list said deserve the most study, in the order they matter for *reading this
code*: open-set recognition, embeddings and metric learning, threshold calibration, identity
correction (merge/split), clustering, re-identification, tracking, continual learning.

---
# Part 6. Memory on disk: databases, transactions and storage

Everything the application "knows" lives in two places: a SQLite database and a folder of files.
This part explains how to read the persistence code, from SQL basics up to the rules that keep the
data safe.

## 6.1 Relational databases and SQL

A **relational database** stores data in **tables**. A table has **columns** (the fields) and
**rows** (the records). Each row is identified by a **primary key**. Tables refer to each other with
**foreign keys**: a column holding another table's primary key.

```
sources                           observations
id (PK)    kind    state          id (PK)   source_id (FK -> sources.id)   box   state
-----------------------           ----------------------------------------------------
s1         IMAGE   ACTIVE         o1        s1                              ...   ACTIVE
                                  o2        s1                              ...   ACTIVE
```

**SQL** is the language for asking a database questions.

```sql
SELECT id, state FROM sources WHERE kind = 'IMAGE' ORDER BY created_at DESC LIMIT 10;
INSERT INTO sources (id, kind, state) VALUES ('s2', 'IMAGE', 'ACTIVE');
UPDATE sources SET state = 'RECYCLED' WHERE id = 's2';
DELETE FROM sources WHERE id = 's2';
SELECT o.id FROM observations o JOIN sources s ON s.id = o.source_id WHERE s.state = 'ACTIVE';
```

You rarely write SQL in this project; the ORM (6.6) does. But reading the migration files and the
specs is much easier if you recognise `SELECT/WHERE/JOIN`.

**Constraints** make the database refuse bad data, whatever the code does:

- `NOT NULL`: a value is required. `UNIQUE`: no two rows may share the value(s).
- **`CHECK (state IN ('ACTIVE','RECYCLED',...))`**: only listed values allowed. Status columns with a decided, finite vocabulary have one, generated from the Python enum (a few
  runtime-catalog fields deliberately remain plain strings until their value sets are decided).
- **Foreign key `ON DELETE RESTRICT`**: you may not delete a row something else still points at (the
  project uses it nearly everywhere so history cannot be orphaned); `SET NULL` clears the pointer.
- **Indexes** (not the vector kind): a sorted structure that makes lookups on a column fast.
  A **partial unique index** enforces a rule over only some rows (for example "at most one valid FINAL
  checkpoint per run").

The database holds 33 tables in the initial schema, e.g. `sources`, `artifacts`, `observations`,
`representations`, `representation_spaces`, `identities`, `identity_lineage`, `people`,
`identity_person_associations`, `occurrences`, `evidence`, `jobs`, `processing_runs`,
`execution_segments`, `processing_checkpoints`, `processing_configuration_snapshots`,
`index_operations`, `components`, `model_exports`, `runtime_variants` (and later `app_state`, added by
revision 0004). Part 8 explains what each is *for*.

## 6.2 SQLite

**SQLite** is a database in a single file with no server: your program calls it as a library. That
suits a single-user desktop app: nothing to install, nothing to administer, one file to back up. The
trade-off is that it allows **one writer at a time**.

- **WAL mode (write-ahead log).** Changes are appended to a side file (`library.db-wal`) and merged
  into the main file later ("checkpoint"). Readers keep reading the last committed state while a
  writer writes, so reading never blocks writing. The project turns WAL on for every connection.
- **`PRAGMA` settings** applied to every connection (`backend/infrastructure/db/engine.py`):
  `foreign_keys = ON` (SQLite ignores foreign keys unless asked), `journal_mode = WAL`,
  `busy_timeout` (how long to wait for the write lock), `secure_delete = ON` (overwrite deleted
  bytes with zeros, so erased data is not left lying in the file).
- **PostgreSQL** was considered and rejected for V1; it would be adopted only if measured write
  contention became a real problem.

## 6.3 Transactions and ACID

A **transaction** is a group of changes that succeed or fail *together*. Think of moving money: debit
and credit must both happen or neither. Databases promise **ACID**:

- **A**tomic: all or nothing. **C**onsistent: constraints always hold at commit.
  **I**solated: concurrent transactions do not see each other's half-done work.
  **D**urable: once committed, it survives a crash.

`COMMIT` makes the changes permanent; `ROLLBACK` throws them away. Examples of why it matters here:
**merging two identities** moves their representations, their occurrences, writes evidence and a
lineage edge and bumps revisions; if the program died halfway you would have a corrupted memory. So
the whole merge is one transaction.

### BEGIN IMMEDIATE, busy errors and retry

A normal SQLite transaction starts as a reader and upgrades to a writer at its first write; if another
writer got in first, the upgrade fails at once with "database is locked", which no waiting can fix.
So the project starts every writing transaction with **`BEGIN IMMEDIATE`** (claim the writer slot
first; others wait up to `busy_timeout`). If the database is still busy, the **whole transaction** is
rolled back and run again, a bounded number of times, and then reported as `DatabaseBusyError`.

Consequence you must remember when reading write code: **a "write function" may run more than once.**
So it must be a pure function of the session (read, decide, write; no sending emails, no moving files,
no calling the worker inside it). Events are announced *after* the commit.

This is `UnitOfWork` in `backend/infrastructure/db/unit_of_work.py`:

```python
class UnitOfWork:
    def read(self, work):   # a read-only transaction, always rolled back
        ...
    def write(self, work):  # BEGIN IMMEDIATE ... COMMIT, retried on busy
        ...
```

and a use case is just a function you hand to `uow.write(lambda session: ...)`.

### Optimistic concurrency: the `revision` column

Two actions can race ("rename this person" and "merge this person"). Rows that can be edited by the
user carry a `revision` integer that starts at 1. An edit says "change the row *if its revision is
still N*" and increments it; if someone else changed it first, zero rows match and the code raises
a **conflict** instead of overwriting. This is **optimistic locking**; the shared helper is
`backend/infrastructure/db/optimistic.py`. The API exposes the revision so the front end can send it
back.

## 6.4 Migrations (Alembic)

The schema changes over time. A **migration** is a small versioned script that moves a database from
one schema version to the next. **Alembic** runs them; each lives in `backend/alembic/versions/`
(`0001_initial_schema`, ... `0009_drop_identity_split_state`) and has an `upgrade()` and a
`downgrade()`. The database remembers its version in a table called `alembic_version`.

SQLite cannot change most constraints in place, so migrations use **batch mode**: create a new table
with the new shape, copy the rows, drop the old, rename. With foreign keys on, that is dangerous, so
`backend/alembic/env.py` follows SQLite's documented procedure (turn enforcement off outside the
transaction, run `PRAGMA foreign_key_check` before each revision commits).

Rules the project enforces with tests: a migration must work on a **populated** database; a refused
migration leaves the database untouched; **downgrade is refused on a populated library** unless a
development-only environment variable is set, because production only ever moves forward; a library
stamped with a revision newer than the program knows is refused (`DatabaseNewerThanApplicationError`).

## 6.5 SQLAlchemy: Python objects for rows

**SQLAlchemy** (version 2) maps tables to Python classes (the **ORM**) and builds SQL for you.

```python
class Identity(Base):                       # a table
    __tablename__ = "identities"
    id: Mapped[uuid.UUID] = mapped_column(...)           # a column
    state: Mapped[str] = mapped_column(String, ...)
    merged_into_identity_id: Mapped[uuid.UUID | None] = mapped_column(...)
    revision: Mapped[int] = mapped_column(Integer, default=1)

with Session(engine) as session:                         # a unit of conversation with the database
    identity = session.get(Identity, some_id)            # by primary key
    rows = session.scalars(select(Identity).where(Identity.state == "ACTIVE")).all()
    session.add(Identity(...))                           # stage an insert
    session.flush()                                      # send to the database, keep transaction open
    session.commit()                                     # make permanent
```

- A **Session** is a workspace that tracks the objects you loaded and changed and sends the changes
  at `flush`/`commit`.
- **`select(...)`** builds a query; `.where`, `.join`, `.order_by`, `.limit` refine it.
- **Repositories** (`backend/app/*/repository.py`) wrap the queries a feature needs ("find the next
  queued job and claim it") so use cases do not scatter SQL.
- Types: `UUID` primary keys stored as 32-character text; `UTCDateTime` stores times in UTC and
  refuses a time without a timezone.

## 6.6 The vector index (USearch)

The embeddings themselves are stored in SQLite (`representations.vector`, as bytes). The **USearch**
index is a separate derived structure for fast similarity search. Key facts:

- One index per **representation space** (a family of mutually comparable vectors, Part 8.4).
- Each vector has an integer **`ann_key`** unique inside its space; the index only knows keys and
  vectors, SQLite maps keys back to rows.
- Changes to the index are first written to the database as **`IndexOperation`** rows (`ADD`/`REMOVE`,
  states `PENDING`/`APPLIED`/`FAILED`) in the same transaction as the change they describe. A
  **coordinator** later applies them to the index and marks them applied. If the program dies in
  between, startup recovery replays what is pending. This is the *outbox pattern*: record the intent
  atomically with the change, perform the side-effect afterwards.
- The index is saved as numbered **generations** with a manifest and a hash. A damaged or mismatched
  index is quarantined and rebuilt from SQLite.

### Erasure (forgetting a face for real)

Deleting a row is not enough: the vector's bytes may remain inside an index generation and inside
SQLite's file. The erasure use case (`backend/app/memory/erasure.py`) is a careful multi-step
procedure: mark the representation `ERASING` (excluded at once from all searches), rebuild the index
without it, delete every old generation file, clear the vector and key (`ERASED`), checkpoint and
truncate the write-ahead log (`secure_delete` already zeroes freed pages), and verify. It records a
"WAL truncation owed" marker in `app_state` so a crash mid-way is finished at the next start. "Securely
retired" here means verified file deletion; it does not claim physical erasure from an SSD.

## 6.7 The two storage roots and the files

From `docs/research/tech-stack.md` section 15:

- **Library root** (you choose it; it can live on any drive): `database/library.db`, `originals/`,
  `crops/`, `thumbnails/`, `models/`, `derived/`, `backups/`, `recovery/` and `staging/`. This is the
  thing you would back up and move. (Which of these folders the current code already uses is a detail
  of the storage layer; the layout is the decided one.)
- **Machine-local state** (`%LOCALAPPDATA%\<App>`): what belongs to this computer only and can be
  rebuilt: `indexes/` (the USearch files), `cache/`, `temp/` (per-job work folders), `logs/`,
  `runtime/` (installed model packages) and `installation/`.

An **Artifact** row describes a file: its kind, its **storage mode** (`MANAGED`, a copy we own, or
`REFERENCED`, an original left where it is), its SHA-256 and its **state** (`PENDING` -> `AVAILABLE`
-> maybe `MISSING`). Writing a managed file follows a three-step protocol (PENDING row, staged write
and rename, AVAILABLE row) so a crash at any step is recoverable and no half file is ever visible.
A referenced original that disappears is marked `MISSING`, never silently dropped, and can be
**relinked** to a replacement file only if its size and SHA-256 match.

**The library lock.** A file `database/.lock` is held with an operating-system lock for as long as
the backend runs, so a second copy of the program (or another computer on a shared drive) cannot open
the same library and corrupt it. The operating system frees the lock if the program crashes.

---
# Part 7. The backend: how work gets done

## 7.1 The web, in the minimum you need

- **HTTP** is how a client asks a server for something: a **request** (method, path, headers, optional
  body) and a **response** (status code, headers, body). Methods: `GET` read, `POST` create/do,
  `PUT`/`PATCH` change, `DELETE` remove. Status codes: `200` OK, `201` created, `202` accepted (will be
  done later), `204` no content, `400` bad request, `401` unauthenticated, `404` not found, `409`
  conflict, `422` invalid input, `500` server fault, `503` unavailable.
- **JSON** is the usual body format. A **URL path** like `/api/v1/sources/{source_id}` names a
  resource; `{source_id}` is a **path parameter**; `?limit=20` is a **query parameter**.
- **REST** is the style of naming resources by path and acting on them with HTTP methods.
- A **WebSocket** is a long-lived two-way connection; here the backend uses one only to *push events*
  ("run 42 changed") to the front end.
- **Loopback** (`127.0.0.1`) is the address of your own machine. A server bound there cannot be reached
  from the network.
- **Bearer token**: a secret the client sends in a header `Authorization: Bearer <token>`. The shell
  creates a fresh 256-bit random token for every launch and gives it to the backend through the
  environment; only the shell and the window know it. This is *not* a user login (there are no
  accounts); it just stops unrelated programs on your computer from calling the backend.

## 7.2 FastAPI and ASGI

**FastAPI** is a Python framework for web APIs. You declare a function and it handles the HTTP.

```python
router = APIRouter(prefix="/sources", tags=["sources"])

@router.get("/{source_id}")
def get_source(source_id: uuid.UUID, backend: Backend = Depends(get_backend)):
    ...
```

- **Type hints drive validation.** `source_id: uuid.UUID` means a malformed id gives a `422` before
  your code runs. **Pydantic** (`BaseModel`) describes request and response bodies as typed classes and
  validates and serialises them.
- **`Depends(...)`** is dependency injection: FastAPI calls a helper (checking the token, finding the
  open library) and passes the result in. `backend/api/dependencies.py`.
- **Routers** group routes by topic (`backend/api/routes/`: sources, processing, jobs, identities,
  people, corrections, identity changes, memory...). All sit under `/api/v1`.
- **ASGI** is the standard interface between Python async web apps and servers; **uvicorn** is the
  server that runs the app and speaks HTTP and WebSocket (`websockets` library underneath).
- **OpenAPI** is a machine-readable description of every route and shape. FastAPI generates it;
  `backend/api/openapi.py` writes it to `frontend/src/api/openapi.json`, and a tool turns that into
  TypeScript types (`schema.d.ts`). A test and a CI step fail if they drift, so the front end and back
  end cannot silently disagree.
- **One error shape** for the whole API (`backend/api/errors.py`):
  `{"error": {"code", "message", "details", "retryable", "diagnostic_id"}}`. Unexpected errors return
  only a generic `INTERNAL_ERROR` and a diagnostic id, never a traceback or user data.
- **Conventions** the routes share: cursor pagination on collection routes, library gating (routes answer `503` until
  the library has opened), `202` for work that happens later, ETags on media.

## 7.3 Starting up: the sidecar host and the lifespan

`python -m backend.api.host --library-root R --local-state-root L ...` (`backend/api/host.py`):

1. Reads the token from the environment (`FACEIDENTIFY_LAUNCH_TOKEN`), validates it; never from the
   command line, never logged.
2. Binds `127.0.0.1` on a free port the operating system picks.
3. Prints **exactly one JSON line** to standard output (the **handshake**: host, port, protocol, pid).
   The shell reads it and then polls `/readiness`.
4. Serves until it is told to stop: the shell closes the backend's **standard input** (the
   `--stdin-lifeline`; on Windows there is no gentle signal, so closing a pipe is the clean request) or
   the shell's process disappears (`--parent-pid`).

The FastAPI **lifespan** (`backend/api/startup.py`) is code that runs at start and at stop:

- Start: open the library on a worker thread (this runs migrations and recovery), claim the library
  *profile*, run the profile's `prepare` step, and *only then* start the scheduler loop. Recovery and
  normal scheduling must never race.
- `/readiness` reports a lifecycle state (`INITIALIZING`, `READY`, `DEGRADED`, `FAILED`,
  `SHUTTING_DOWN`) and a capability list (`database`, `storage`, `index`, `recovery`, `ml_worker`,
  `scheduler`). `DEGRADED` means something recoverable is outstanding.
- Stop: stop the scheduler, close the perception workers, close the library (dispose the engine,
  release the lock).

**Profiles.** The host runs in one of two profiles and refuses a library created under the other:

- **development** (`--development-profile`): a fake catalog and fake perception under an uncalibrated
  demo policy, so the whole app can be exercised without models. Never a release setting.
- **real** [built, `backend/api/real.py`]: installed runtime packages, real workers, a measured
  policy (Part 8.9). It is the host's default without a flag; the shell passes the development
  profile in debug builds (`desktop/src-tauri/src/config.rs`). Preferred providers come from
  `FACEIDENTIFY_PROVIDERS` (CPU by default; `CUDAExecutionProvider,CPUExecutionProvider` tries the
  GPU first, with the CPU as the planned fallback; an unknown name is an error).

## 7.4 The job and run lifecycle

When you press "process", the backend writes (one transaction) a **Job** and a **ProcessingRun** with a
frozen **ProcessingConfigurationSnapshot**. Distinguish:

- A **Job** is *scheduling*: "this work is queued/running/paused", with a priority
  (`INTERACTIVE` > `HIGH` > `NORMAL` > `LOW` > `MAINTENANCE`, stored as an integer rank so ordering is
  correct), a lease (who is working on it and until when) and attempts.
- A **ProcessingRun** is *history*: "this source was processed with these exact models and
  settings". Its states: `PENDING`, `RUNNING`, `PAUSING`, `PAUSED`, `CANCELLING`, `CANCELLED`,
  `FINALIZING`, `COMPLETED`, `FAILED`, `INTERRUPTED`, `NOT_RESUMABLE`.
- The **snapshot** freezes everything that decides the outcome (which detector and embedder exports,
  which representation space, providers, the decision policy). Later changes to settings never rewrite
  history, and a **retry** makes a *new* job and run from a copy of the snapshot.

**State machines.** Jobs and runs move through a fixed set of states by *guarded transitions*: "set
`RUNNING` only if currently `QUEUED`". A guard is an `UPDATE ... WHERE state = 'QUEUED'`; if it matches
no row someone else got there first. Never assume the state you read a moment ago still holds.

**The scheduler** (`backend/api/scheduler.py`): an async loop that repeatedly calls
`ProcessingRunner.run_once` in a worker thread. Work found: call again immediately. Idle: wait until
woken (a job was just queued) or a poll interval passes. An error is recorded by class name and the
loop waits one interval, so a persistent fault never spins at full speed.

**The runner** (`backend/app/processing/runner.py`) claims the next job (priority order), starts it,
executes it, then accepts the result, deciding every outcome (completed, cancelled, failed, paused).

## 7.5 Executing one image

`ExecuteProcessingJob` (`backend/app/processing/execute_job.py`) does, in order, with **no ML inside a
database transaction** (a slow model call must never hold the write lock):

1. Check for a cancellation request (done between every step, never mid-step).
2. Read the source and the frozen snapshot; build a **perception plan** (which model files, which
   providers, in preference order) from the installed packages.
3. Decode the image to pixels.
4. Ask the worker to **detect**; write each face as a `PENDING` Observation.
5. Ask the worker to **embed**; write each vector as a `PENDING` Representation.
6. Retrieve similar vectors (run-local index of this run's own faces, plus the global index) and let the
   **reasoner** decide for each face.
7. Persist the decisions privately, then write a `FINAL` **checkpoint**, and move the run to
   `FINALIZING`.

Everything before acceptance is **private**: `PENDING` rows are invisible to every read route. If the
program dies anywhere, nothing half-done is ever shown.

**Checkpoints** are saved progress markers (kind `INTERMEDIATE` or `FINAL`, state `VALID`/...). A valid
`FINAL` checkpoint holds the complete decision evidence, so acceptance can complete **without running
any ML again**.

**Acceptance** (`accept_run.py`) is one atomic transaction: revalidate the `FINAL` checkpoint against
the database (it fails closed on anything unexpected), activate the observations and representations,
write Occurrences and Evidence, create or attach identities, append `ADD` index operations, move the
source's pointer to this run, and complete the run and job. Then, *after the commit*, wake the index
coordinator.

**Execution segments.** A run is divided into segments, each tied to the model variant that actually
ran. A segment only closes and a new one starts when a *provider fallback* really happens, so history
can tell you "this part ran on CUDA, this on CPU".

## 7.6 The ML worker and its supervisor

Why a separate process? Native model code can crash, hang or leak memory. Isolating it means a crash
costs one request and a restart, never the library.

- **Messages** (`backend/ml/contracts/`): a small versioned protocol of requests and responses (control
  messages such as HELLO and SHUTDOWN, and operations such as detect and represent), sent over a pipe
  (`multiprocessing.Pipe`). The image pixels travel through **shared memory** (a block both processes
  map), so large arrays are not copied through the pipe. A `SegmentLedger` tracks and releases blocks.
- **The worker** (`backend/ml/worker/`) is started with `multiprocessing` "spawn". It builds
  *handlers* (detect, represent) from a configuration string naming the exact model files, their
  SHA-256 and their providers, then serves requests in a loop. It verifies each model file's hash
  before loading and loads from the bytes it hashed (so a swapped file cannot run).
- **The supervisor** (`backend/ml/supervisor/`) starts the worker, waits for HELLO within a timeout,
  sends requests with a timeout, pings, restarts after a failure, **limits restarts inside a time
  window** (a crash loop becomes `FAILED` instead of spinning), and stops it politely then forcibly
  (killing the whole process tree on Windows).
- **The perception client** (`backend/app/runtime/perception_client.py`) is what application code uses:
  `detect(pixels)` and `represent(pixels, detections)`. It tries the plan's providers in order,
  records which one actually ran, and reports any fallback. A *stage never inherits another stage's
  ruled-out provider*.
- **GPU activation.** For CUDA, the worker process itself puts a machine-local `onnxruntime-gpu`
  directory first on its import path and registers the NVIDIA DLL folders
  (`backend/ml/worker/gpu_path.py`, environment variable `FACEIDENTIFY_ORT_GPU_DIR`).

## 7.7 Runtime packages and the catalog

Models are **replaceable components**, not hard-wired. The vocabulary:

- A **runtime package** is a folder on disk with a `manifest.json` and model files, installed into
  machine-local `runtime/` by `RuntimePackageStore` (verified copy into staging, then an atomic rename).
- The manifest describes **components** (a `FACE_DETECTOR`, a `FACE_REPRESENTATION`) with versions and
  **contracts** (input preprocessing, output dimension, normalisation), their **exports** (an ONNX file
  with size and SHA-256 and provenance: licence, source, redistributable) and **variants** (the same
  export on a particular provider and device: CUDA/GPU, CPU).
- **Registration** (`register_package`) copies that description into the database catalog
  (`components`, `component_versions`, `model_exports`, `runtime_variants`, `representation_spaces`),
  find-or-create, verifying every file's hash again.
- **Representation space**: identified by the weights digest, dimension, preprocessing contract,
  normalisation and a compatibility version. Two vectors are comparable only inside one space. A new
  model with different weights is a new space; old and new vectors are never compared.
- **The sweep** keeps those records honest: at startup the real profile marks an installation
  `MISSING` when its file is no longer on this machine (by existence alone), and only registering the
  package again, which re-verifies every byte, brings it back. A missing package is reported, never
  replaced by another, and so is a package the *library's own vectors* need: `/readiness` then lists
  `missing_dependencies` ("key version") and the app opens `DEGRADED`, because vectors of one model
  are never compared with another's.
- **Planning** turns "the frozen snapshot" into "these exact files on this machine", and *refuses*
  to substitute a different export (the frozen choice is exact).

## 7.8 Recovery: surviving crashes

The program is allowed to be killed at any moment (power loss, crash, Task Manager). The design makes
that safe by combining: atomic writes, transactions, durable intent records (job and run states,
index operations, the erasure marker) and **startup recovery** (`backend/app/recovery/startup.py`),
which runs when the library opens and before the scheduler starts. It:

- settles half-written artifacts and marks files that vanished as missing;
- marks `RUNNING` jobs, runs and segments `INTERRUPTED` (never silently re-queued: a retry is an
  explicit new job);
- moves anything found `PAUSING` to `PAUSED`, `CANCELLING` to `CANCELLED`;
- accepts any `FINALIZING` run from its `FINAL` checkpoint without ML;
- clears stale leases, removes leftover work folders;
- validates the vector index and rebuilds a stale or corrupt one;
- retries failed index operations and finishes interrupted erasures;
- returns a report of anything it could not settle (the `DEGRADED` readiness).

It is **idempotent** (running it twice equals running it once) and tested by killing real processes at
every stage (`tests/recovery/`, `tests/e2e/`).

## 7.9 Events

`backend/api/events.py` keeps an in-memory **event hub**. When something changes (a source created,
a run updated) the backend publishes `{type, resource, id, sequence}` to connected WebSocket clients.
Events are **best effort** and only a hint to refetch: the change is already committed, so a failed
publish never fails the work. **Sequence numbers** let the client detect a gap (a lost event) and
simply refetch everything. The server greets each connection with a `hello` message.

## 7.10 Security in this design

- Loopback only, per-launch bearer token, token never on a command line or in a log.
- Request bodies are validated; error responses never echo user input or paths.
- Original files are never modified; paths are resolved safely (no escaping the library root).
- Model files are hash-verified before use; the worker loads exactly the bytes it hashed.
- Biometric data is local; only `ForgetIdentity` [designed] removes it, with the erasure procedure of
  Part 6.6.
- The model weights are licensed for research use; they stay local and are never committed.

---
# Part 8. The domain model: the product's vocabulary

The product speaks in about a dozen nouns. Learn them precisely; the code, the database and the specs
all use them in exactly this sense (`docs/specs/identity-and-memory-model-v1.md` is the authority).

## 8.1 The big diagram

```
 Source (a photograph)                                    Person (a name)
   |  has                                                    ^  attached by
   v                                                         |  IdentityPersonAssociation
 Observation  (a detected face in that source)               |
   |  yields                                          Identity (one visual subject, named or not)
   v                                                    ^  ^
 Representation (the face's vector, in a space)         |  |  belongs to
   |  belongs to ------------------------------------- -+  |
   |                                                        |
 Occurrence (an appearance of an Identity in a Source) -----+   Evidence (why, append-only)
```

Read it as a chain: a **Source** contains **Observations**; each Observation has a **Representation**;
representations are grouped under **Identities**; an Identity may be linked to a **Person**; and every
decision leaves **Evidence**.

## 8.2 The nouns

| Noun | What it is | Notes |
|---|---|---|
| **Artifact** | A file the system knows about: an original, a copy, a model export | has a storage mode (`MANAGED`/`REFERENCED`), a SHA-256 and a state (`PENDING`, `AVAILABLE`, `MISSING`...) |
| **Source** | One thing you imported: an image (video later) | states `ACTIVE`, `RECYCLED` (in the recycle bin, bytes untouched), `DELETING`, `DELETED`, `UNAVAILABLE` |
| **Observation** | A concrete detected face in one source: box, landmarks, detector score | "not a person, not an occurrence"; states `PENDING`, `ACTIVE`, `SUPERSEDED`, `REJECTED`, `DELETED` |
| **Representation** | The canonical face vector (512 float32s) with provenance: which model variant produced it | states include `PENDING`, `ACTIVE`, `SUPERSEDED`, `ERASING`, `ERASED`; the USearch entry is derived from it |
| **RepresentationSpace** | A family of comparable vectors (Part 7.7) | `ACTIVE` or `DEPRECATED` |
| **Identity** | One *visual subject*: the thing a set of similar faces are all of. Named or unnamed | states `PENDING`, `ACTIVE`, `MERGED` (kept as a row pointing at where it went), `FORGOTTEN`, `DELETED`. A merge or split is recorded as **lineage**, not a state |
| **Person** | A *semantic* human with a name | separate from Identity on purpose: one real person may appear as two identities (a beard, a decade) until you merge them. Names are not unique |
| **IdentityPersonAssociation** | The link between an Identity and a Person | can be removed or superseded; reassigning is the correction |
| **Occurrence** | A meaningful appearance of an Identity within a Source (kind `IMAGE`, later `TRACK`, `SEGMENT`) | "this person is in this photo" is an Occurrence; it points at its observations |
| **Evidence** | An immutable, append-only record of *why* a decision was made | kinds: `IDENTITY_CREATED`, `IDENTITY_MATCHED`, `RECOGNITION_ABSTAINED`, `IDENTITY_ASSIGNED_TO_PERSON`, `IDENTITY_REMOVED_FROM_PERSON`, `IDENTITY_MERGED`, `IDENTITY_SPLIT`, `IDENTITY_FORGOTTEN`, `USER_CORRECTION`, `PERSON_RENAMED`. Never rewritten; carries the candidates, scores and policy at the time |
| **IdentityLineage** | A structural edge: `MERGED_INTO` or `SPLIT_FROM` between identities | history of reshaping |
| **Job / ProcessingRun / ExecutionSegment / Checkpoint / ConfigurationSnapshot** | Scheduling and history of a processing (Part 7.4) | |
| **IndexOperation** | A pending change for the vector index (`ADD`/`REMOVE`) | the outbox (Part 6.6) |
| **Component / ComponentVersion / ModelExport / RuntimeVariant** | The model catalog (Part 7.7) | |

### Why separate Observation, Representation, Occurrence and Identity?

Because they answer different questions and change at different times.

- *Observation*: "a face was here." True forever (about this source).
- *Representation*: "its vector is this." Can be erased without deleting the fact that a face existed.
- *Occurrence*: "this identity appears in this source." Can move when you correct a mistake or merge two identities.
- *Identity*: "these faces are all one subject." The thing you correct.

A single sentence to hold on to: **the system remembers evidence; identity is a conclusion drawn from
it, and conclusions can be revised.**

### States everywhere, and "authoritative only"

Almost every table has a `state`. Read routes show only `ACTIVE` data; `PENDING` data (a run still in
progress) is private; `SUPERSEDED`/`DELETED` are history. Filters on state are a constant source of
subtle bugs, which is why the tests assert them so heavily.

## 8.3 Revisions and optimistic updates

Rows a user edits (`identities`, `people`) have `revision`; every change must say which revision it
saw (Part 6.3). When the API answers a `409` such as `PERSON_REVISION_CONFLICT` it means "someone (or another window)
changed this since you looked; reload and try again".

## 8.4 The recognition decision, restated with the nouns

For every new Observation/Representation the system retrieves nearby Representations, **groups them by
Identity** (best score per identity is that identity's score), and the reasoner (Part 2.19) returns:

| Outcome | Meaning | What acceptance does |
|---|---|---|
| `MATCH_EXISTING` | clearly an identity already known | attaches the face to it, writes Occurrence + `IDENTITY_MATCHED` Evidence |
| `CREATE_NEW` | clearly nobody known (or nothing to compare with) | creates an Identity, Occurrence + `IDENTITY_CREATED` Evidence |
| `ABSTAIN` | not sure | stores the Representation *without* an identity (it stays searchable as evidence), creates **no** Occurrence, writes `RECOGNITION_ABSTAINED` Evidence; you resolve it later |

Reasons recorded with each decision: `LOW_QUALITY`, `RETRIEVAL_INCOMPLETE`, `NO_CANDIDATE`, `MATCHED`,
`AMBIGUOUS_CANDIDATES`, `UNRESOLVED_NEIGHBOUR`, `NOT_SIMILAR`, `UNCERTAIN_SIMILARITY`.

**Automatic matching can be switched off.** A policy whose `match_threshold` is above 1.0 can never
match (a similarity never exceeds 1); the run then reports `automatic_matching: false` and the screen
says "Automatic matching disabled". The first face of an empty library still creates an identity;
after that, a face with candidates abstains and waits for you. Scores are called *similarity scores*
in the interface because they are not probabilities of identity.

**The measured real-model policy is abstain-only** (Part 4.6) but is *not yet active*: it takes effect
when the real host profile reads it. Under it, with automatic matching off, every face that has
candidates would abstain and wait for you, and only a face with nobody to compare with would create an
identity. The policy the running development profile uses today is a demo one (threshold 0.9,
ceiling 0.5), labelled uncalibrated.

## 8.5 What you can do to memory (the M5 identity-management features)

All of these are *use cases* in `backend/app/...`, exposed as routes, each one an atomic transaction
that records Evidence and bumps revisions.

| Action | Route (under `/api/v1`) | What happens |
|---|---|---|
| **Name** a person | `POST /people` (+ `assign-identity`), `PATCH /people/{id}` renames | creates the Person and links it atomically; rename writes `PERSON_RENAMED` Evidence |
| **Confirm** a face | `POST /occurrences/{id}/confirm` | you assert "yes, this is that identity"; writes `USER_CORRECTION` |
| **Move / separate** a face | `POST /occurrences/{id}/reassign` | moves a face to another identity, or separates it into a new unknown one. Only *ownership* moves: the vector and its index entry are untouched. The call says which identity you saw the face under; if it has moved since, the correction is refused as stale. There is deliberately no "cannot link" memory: a correction does not stop recognition from choosing the same identity for a similar face again |
| **Place** an unresolved face | `GET /sources/{id}/unresolved-faces`, `POST /representations/{id}/resolve` | the abstained faces (issue #79) |
| **Merge** identities | `POST /identities/merge` | moves everything from one identity into another; the loser stays as a `MERGED` row with lineage |
| **Split** faces off | `POST /identities/{id}/split` | creates a new identity for chosen faces; an Occurrence supported by faces on both sides is a conflict you must resolve (`409 SPLIT_CONFLICT`) |
| **Assign / remove** a person link | `POST /people/{id}/assign-identity`, `.../remove-identity` | |
| **Read** | `GET /identities`, `/people`, `/sources/{id}/occurrences`, `/identities/{id}/occurrences` | authoritative (`ACTIVE`) data only |

**Not built yet [designed]:** `ForgetIdentity` (the *only* operation that removes biometric memory; "forget person" runs it for each
of a Person's identities), historical and name search, face search (query-only; never stores the
query), cross-source recognition on real models, and the M5 real-world gate.

## 8.6 Deleting is not one thing

A common source of confusion. The project distinguishes:

- **Recycle** a source (`DELETE /sources/{id}`, built): it leaves your library view and appears in the
  Recycle bin view, while its bytes and its memory stay and its faces remain in the people it was
  recognised in, marked as coming from a recycled image; `POST /sources/{id}/restore` brings it
  back without reprocessing. A source being processed cannot be recycled until that ends.
- **Delete** a source permanently ([built], `POST /sources/{id}/permanent-delete`, only from the bin): removes its
  files, faces, vectors and runs; *evidence and named people stay* (an unnamed identity left with nothing
  becomes `DELETED`). It records its intent first, so a crash is finished at the next start.
- **Forget** an identity: the only thing that erases its biometric vectors (Part 6.6 erasure).
- **Occurrences from a recycled source** keep showing in identity views, marked as recycled.

## 8.7 Provenance: knowing what produced what

Every Observation and Representation records the **runtime variant that actually executed** (a
foreign key into the catalog), and a run records the frozen **snapshot** of its intent. From any
vector you can ask: which model file, which version, which provider (CPU or CUDA), which policy, which
run produced you? This is why the catalog tables exist, and why the project avoids "just store the
number".

## 8.8 Calibration profiles and the UI notice

A run's snapshot says whether its policy is calibrated. The front end shows a **policy notice** (a
banner) built from the latest run: today "Uncalibrated results" and the policy's version name, because
the thresholds are raw cosine values, never probabilities.

## 8.9 The profiles in code

- `backend/api/development.py`: fake catalog, fake perception (one face in the middle of every image,
  a vector derived from the image's pixels, so identical images are the same person), demo thresholds.
- `backend/api/real.py` [built]: the **real profile**. At startup (`prepare`) it registers every
  installed package in the catalog (a damaged package is skipped, not fatal) and reports three
  capabilities in `/readiness`: `runtime_package` (the package it runs is installed and registered;
  the app is `DEGRADED` when not), `processing_policy` (a usable, abstain-first policy file exists)
  and `ml_worker` (the supervisors' own state, `NOT_STARTED` until a job starts one). A `ClientPool`
  keeps one supervised worker per plan for the life of the process, gives each job a fresh client
  (so every job records its own fallbacks), and stops all workers at shutdown. The
  processing request is built on every "process" command from the registered catalog plus the measured
  policy file `<local state>/policies/<package>.json`, which holds only the `decision_policy` object
  (`version`, `min_detection_score`, `match_threshold`, `margin`, `new_identity_ceiling`); with no
  package or no usable policy it answers `503` and never invents numbers.

---
# Part 9. The front end: what you see

The window shows a web page. If you have never written one, start at 9.1. If you know HTML and
JavaScript, skip to 9.4.

## 9.1 HTML, CSS and JavaScript in five minutes

- **HTML** describes a page's structure with nested **elements** written as tags:
  `<h1>Title</h1>`, `<button>Go</button>`, `<img src="a.png">`, `<div>` (a generic box), `<span>`
  (generic inline text), `<ul><li>` (a list). Elements can have **attributes**:
  `<a href="/library">Library</a>`. The browser parses HTML into a tree called the **DOM**.
- **CSS** describes appearance: colours, sizes, spacing, layout. A rule picks elements and sets
  properties: `button { background: blue; padding: 8px; }`. **Flexbox** and **grid** are the layout systems.
- **JavaScript** (JS) is the programming language of the page: it reacts to clicks, fetches data and
  changes the DOM.

JavaScript, for a reader who knows Part 2 (Python):

```js
const name = "Ada"            // `const`: a name that cannot be reassigned; `let` can be
let count = 0
const faces = ["a", "b"]; faces.push("c")
const policy = { threshold: 0.35, margin: 0.02 }    // an object (like a dict): policy.threshold
if (count > 0) { ... } else { ... }
for (const face of faces) { ... }                   // iterate values
faces.map(f => f.toUpperCase())                     // transform a list (like a comprehension)
faces.filter(f => f !== "b")                        // keep some
const add = (a, b) => a + b                         // arrow function (like a lambda, but full-featured)
const { threshold } = policy                        // destructuring
const copy = { ...policy, margin: 0.05 }            // spread: copy and override
value ?? "default"                                  // "default" only if value is null/undefined
maybe?.property                                     // optional chaining: undefined instead of an error
await fetch(url)                                    // async/await, as in Python
```

A **Promise** is JS's "value that will exist later"; `await` waits for one. `===` is strict equality
(always use it, not `==`). `null` and `undefined` are two kinds of "nothing".

## 9.2 TypeScript

**TypeScript** (TS) is JavaScript plus types, checked before running by `tsc` (like mypy for Python).
Files are `.ts` (logic) and `.tsx` (logic with HTML-like markup, 9.4).

```ts
interface Connection { base_url: string; token: string }        // a shape
type Tone = 'neutral' | 'busy' | 'good' | 'bad'                 // a union of allowed values
const TONES: Record<Tone, string> = { neutral: '...', busy: '...', good: '...', bad: '...' }
function statusLabel(state: string): string { ... }             // typed parameters and result
let id: string | undefined                                      // maybe missing
export class ApiError extends Error { readonly status: number } // a class, like Python's
```

The project's `tsconfig` is strict. The big payoff: **the back end's API description is turned into
TypeScript types automatically** (`frontend/src/api/schema.d.ts`, generated from `openapi.json`). If a
route's shape changes and the front end is not updated, the type check (and CI) fails.

## 9.3 Tooling: Node, npm, Vite, Vitest, oxlint

- **Node.js** runs JavaScript outside a browser (for tools). **npm** installs packages into
  `node_modules/` as listed in `package.json` (`npm install`, `npm ci` for exact lockfile installs).
- **Vite** serves the app during development (`npm run dev`) with instant reload and bundles it for
  production (`npm run build`, which also runs `tsc -b` first).
- **Vitest** runs the tests (`npm test`) in a simulated browser (**jsdom**); **Testing Library**
  renders components and lets a test find them the way a user would (by role and text), **user-event**
  simulates clicks and typing.
- **oxlint** is the linter (`npm run lint`). The project does **not** use Prettier: the style is
  single quotes, no semicolons, and running a formatter over files would rewrite them whole.

## 9.4 React

**React** builds interfaces from **components**: functions that return a description of what to
show. The description is written in **JSX**, HTML-like syntax inside TypeScript.

```tsx
export function StatusBadge({ state }: { state: string }) {        // props: the inputs
  return (
    <span className={`inline-flex rounded-full px-2 ${TONE_CLASSES[statusTone(state)]}`}>
      {statusLabel(state)}
    </span>
  )
}
```

This is the real `frontend/src/features/StatusBadge.tsx` (shortened): given a state string such as
`RUNNING`, it returns a coloured pill labelled for humans. `{...}` embeds a JavaScript expression;
`className` is HTML's `class`; components are used like tags: `<StatusBadge state={run.state} />`.

Key ideas:

- **Props** flow down from parent to child; a component should be a pure description of its props and
  state.
- **State** (`useState`) is data a component remembers; changing it re-renders the component.
  `const [open, setOpen] = useState(false)`.
- **Effects** (`useEffect`) run code *after* rendering to synchronise with the outside world (open a
  WebSocket, set a timer) and clean up when the component goes away.
- **Hooks** are the `use...` functions; they must be called at the top of components, not in
  conditions or loops.
- **Lists** render with `.map` and need a stable `key` on each item.
- **Conditional rendering**: `{ready ? <Page /> : <Spinner />}` or `{error && <Banner />}`.
- **Composition**: components nest; a *layout* component renders its children where
  `<Outlet />` appears.

## 9.5 How this app is structured

```
frontend/src/
  main.tsx            starts React
  app/                App, BackendGate (waits for the backend), BackendProvider, EventsBridge,
                      Layout (shell + policy notice), routes.tsx
  api/                client.ts (typed fetch), endpoints.ts, keys.ts, events.ts (WebSocket),
                      invalidation.ts, types.ts, schema.d.ts (generated)
  native/backend.ts   the bridge to the Tauri shell (asks it where the backend is)
  features/           library/, source/, identities/, processing/ (one folder per screen)
  state/ui.ts         tiny client-only state (Zustand)
  components/         shared UI pieces (shadcn/ui, Part 9.8)
```

### The connection gate

The window starts before the backend is ready. `BackendGate` asks the shell for the backend's status
(`invoke('backend_status')`, Part 10), shows "starting" or an error, and only when `ready` renders the
app with a **connection** `{ base_url, events_url, token }` in a React context. In a plain browser
there is no shell, so the connection can come from `VITE_BACKEND_URL` / `VITE_BACKEND_TOKEN`.

### The API client

`ApiClient` (`api/client.ts`) is a few dozen lines: build the URL (with query parameters), add the
`Authorization: Bearer ...` header, `fetch`, and turn any failure into one `ApiError` carrying the API's
own `code`, `message` and `retryable`. It does no caching; that is the next layer's job.

### Server state with TanStack Query

Most of what is on screen is *server data*: lists of sources, a run's progress, an identity's faces.
**TanStack Query** (`@tanstack/react-query`) manages it.

- `useQuery({ queryKey, queryFn })` fetches, caches and shares data under a **key**, and re-renders
  when it changes; you get `data`, `isLoading`, `error`.
- A **mutation** (`useMutation`) sends a change (merge, rename) and then marks affected queries stale.
- All keys live in one file, `api/keys.ts`, so what a screen reads and what an event invalidates cannot
  drift:

```ts
export const keys = {
  sources: ['sources'] as const,
  source: (id: string) => ['source', id] as const,
  identity: (id: string) => ['identity', id] as const,
  ...
}
```

### Live updates: events invalidate queries

`api/events.ts` opens the WebSocket (offering the token in the `Sec-WebSocket-Protocol` header),
reconnects after a drop, and detects gaps in the event sequence. `api/invalidation.ts` maps an event to
the keys it makes stale:

```ts
if (event.type.startsWith('processing_run.')) {
  return [keys.run(id), keys.runs, keys.sources, keys.identities, ['identity'], ...]
}
```

Events carry a resource id and a little metadata (a run event includes its state and source id), but
the screen never treats that as the truth: it always refetches from REST, so a lost or duplicated
event cannot show wrong data. `EventsBridge` wires the two together.

### Routing

`react-router` with **hash routes** (`#/library`): the app is served from a custom protocol, where a
reload on a normal deep path would ask the file server for a file that does not exist.

```tsx
{ path: 'library', element: <LibraryPage /> },
{ path: 'library/source/:sourceId', element: <SourcePage /> },
{ path: 'identities/:identityId', element: <IdentityPage /> },
{ path: 'processing/:runId', element: <ProcessingPage /> },
```

`:sourceId` is a URL parameter read with `useParams()`.

### Client-only state

`state/ui.ts` uses **Zustand** (a tiny store) for things that are not server data, such as the event
connection's status. The rule (decision 5): server data lives only in the query cache.

## 9.6 The screens

| Route | Screen | What it shows |
|---|---|---|
| `/library` | `LibraryPage` | your sources as cards; import through the native file picker; process |
| `/library/source/:id` | `SourcePage` | the image with face boxes, processing history, people found, process/cancel/retry, and the faces recognition declined to place (`UnresolvedFaces`) |
| `/identities` | `IdentitiesPage` | everyone remembered, with counts |
| `/identities/:id` | `IdentityPage` | one identity's faces, with a name form, merge and split controls (`NameForm`, `MergeControl`, `SplitControl`) and, per face, a correction control (`FaceCorrection`) |
| `/processing/:runId` | `ProcessingPage` | one run's state, policy and outcome |
| (layout) | `Layout` | navigation, and the **policy notice** about uncalibrated results |

`FaceCrop` draws a face by cropping the source image with the observation's box; `StatusBadge` and
`status.ts` translate machine states into labels and colours.

## 9.7 Styling: Tailwind and shadcn/ui

- **Tailwind CSS** styles by composing small utility classes directly in the markup:
  `className="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium"`. Component styling needs
  no separate stylesheet to keep in sync (only shared global styles live in `frontend/src/index.css`);
  the build removes unused classes. `dark:` prefixes give dark mode.
- **shadcn/ui** is a collection of ready-made accessible components (buttons, dialogs, menus) that you
  *copy into your own code* rather than install as a library, so you can edit them. They are built on
  **Radix UI** primitives (behaviour and accessibility, no styling), with `class-variance-authority`
  for style variants and `lucide-react` for icons. The Geist font is bundled.
- **Accessibility** (labels, roles, keyboard use, contrast) is part of "done": tests query by accessible
  role for exactly that reason.

## 9.8 Reading a front-end test

```tsx
it('shows the policy notice for an uncalibrated run', async () => {
  render(<Layout />)                                         // draw the component
  const notice = await screen.findByRole('note')             // find it as a user would
  expect(notice).toHaveTextContent('Uncalibrated results.')  // assert on what is shown
})
```

Tests use a fake backend (never the real one, except `npm run test:e2e` which drives the real Python
host through the whole image workflow).

---
# Part 10. The desktop shell: Rust and Tauri

You will rarely edit this code, but you should be able to read it, because it holds the program's
*secrets and process control*. It is about a thousand lines in `desktop/src-tauri/src/`:
`main.rs` (entry), `lib.rs` (commands and startup), `sidecar.rs` (starting/stopping the backend),
`config.rs` (the saved library location).

## 10.1 Rust in ten minutes

Rust is a compiled language that guarantees memory safety without garbage collection. Compare with
Python (Part 2):

```rust
let name = "Ada";                       // immutable by default
let mut count = 0;                      // `mut`: changeable
count += 1;

fn add(a: i32, b: i32) -> i32 {         // types are mandatory; the last expression (no `;`) is returned
    a + b
}

struct Connection { base_url: String, token: String }     // like a dataclass

enum BackendStatus {                    // an enum whose variants can carry data
    Starting,
    Ready { connection: Connection },
    Failed { error: String },
}

match status {                          // exhaustive pattern matching: you must handle every variant
    BackendStatus::Starting => ...,
    BackendStatus::Ready { connection } => ...,
    BackendStatus::Failed { error } => ...,
}
```

The ideas that make Rust different:

- **Ownership.** Every value has exactly one owner; when the owner goes away, the value is freed.
  Passing a value *moves* it; to let others look, you **borrow** it with `&value` (read-only) or
  `&mut value` (one writer). The compiler rejects programs that could use freed memory or race.
- **`Option<T>`** replaces `None`/null: `Some(x)` or `None`. **`Result<T, E>`** replaces exceptions:
  `Ok(value)` or `Err(error)`. The `?` operator returns early on an error.
  A recoverable failure is a value you must handle or pass on (the compiler warns about an ignored
  `Result`); a `panic!` still exists for unrecoverable bugs.
- **Traits** are interfaces (`impl fmt::Display for SidecarError`); **`#[derive(Debug, Clone,
  Serialize)]`** writes boilerplate for you; **crates** are packages (listed in `Cargo.toml`);
  `cargo build`, `cargo test`, `cargo fmt`, `cargo clippy` (lints).
- `Mutex<T>` is a lock around data shared between threads; `.lock()` gives access.

## 10.2 Tauri

**Tauri** builds desktop apps from a native Rust "core" plus a web view (the operating system's own
browser engine, WebView2 on Windows) that shows your front end. Compared with Electron it ships no
copy of a browser, so it is smaller.

- **Commands** are Rust functions marked `#[tauri::command]` that JavaScript can call:
  `invoke('backend_status')` in `frontend/src/native/backend.ts` calls `fn backend_status(...)` in
  `lib.rs`. The commands here: `backend_status` (where is the backend?), `library_info`,
  `choose_library` (folder picker, saved for the next start), `choose_images` (file picker).
- **Plugins** add abilities: `tauri-plugin-dialog` (file pickers), `tauri-plugin-single-instance`
  (a second launch focuses the first window instead of opening another), `tauri-plugin-log`.
- The shell exposes **only** these commands to the web view; the web view cannot touch the file system or
  start programs on its own. That is the security model.

## 10.3 The sidecar contract

A **sidecar** is a helper program started and owned by the main app. `sidecar.rs` implements the contract
that `backend/api/host.py` documents on the other side:

1. **Generate the token** from the operating system's random source (`getrandom`), base64url-encode it.
2. **Spawn** `python -m backend.api.host --library-root ... --local-state-root ... --parent-pid <me>
   --stdin-lifeline` with the token in the environment variable `FACEIDENTIFY_LAUNCH_TOKEN`, never on
   the command line (command lines are visible to other programs).
3. **Read one line** of JSON from the child's standard output within a time limit: the handshake
   (`host`, `port`, `protocol`, `pid`). A line that is missing, late or malformed is an error with a
   precise variant (`NoHandshake`, `Exited`, `BadHandshake`...).
4. **Build the connection** for the web view: `base_url` (`http://127.0.0.1:<port>`), `events_url`
   (`ws://...`), the token, the protocol name `faceidentify.v1`.
5. **Keep the child's standard input open.** Closing it is how the shell asks for a clean stop (on
   Windows there is no gentle signal). If the shell itself dies, Windows closes the pipe and the
   backend notices and stops too; `--parent-pid` is the second safety net.
6. **On quit**: close stdin, wait up to a grace period for the library to close, then kill the process
   tree if it has not.

The shell also owns *which library folder is used*: it reads and saves the choice in its own config
(outside the library), and passes exactly one resolved root to the backend; changing library means
restarting.

## 10.4 How the Rust code is tested

`cargo test` runs unit tests (token generation, handshake parsing) and tests that start the real Python
backend (`cargo test -- --ignored`); the CI "Desktop shell" job also runs the complete end-to-end
workflow (`npm run test:e2e`): import images, process them, read the results, restart, and see the
memory survive.

---

# Part 11. How this project is run: rules, branches, reviews, decisions

This project has unusually explicit working rules because it is built with an AI assistant and
reviewed by independent tools. Knowing them tells you where to look and what "done" means.

## 11.1 Where the rules live

| File | Contents |
|---|---|
| `AGENTS.md` (and `CLAUDE.md`, which includes it) | the non-negotiable rules, short |
| `.agents/CONTEXT.md` | the current state: milestone, repository map, commands, every dated decision and open question |
| `.agents/rules/*.md` | branches, commits, documentation, scope, testing |
| `docs/specs/` | the authoritative design (architecture, API, persistence, identity model, processing, search, product, ML) |
| `docs/plans/` | implementation plans, the roadmap, the test tracker, `PROJECT_STATUS.md` (one-page status), `M5_PLAN.md` |
| `docs/implementations/` | one dated entry for every change: what, why, how verified |
| `docs/research/` | stack decisions, model selection, licensing, the measured operating point, and this guide |
| `docs/archive/` | superseded documents; ignore |

**Precedence:** the specs are authoritative. If code, a test or a request conflicts with a spec, the
work stops and the owner decides; the decision is recorded as a dated note
(`> **Decision 2026-10-07:** ...`) in the spec, so the document stays true.

## 11.2 The working rules

- **Never commit to `main`.** Every change is a branch named `type/short-kebab` and a pull request.
- **Small commits** in Conventional Commits form, sliced by kind, each passing its own tests.
- **Document everything.** Each change adds an entry in `docs/implementations/`, and updates
  `CONTEXT.md`, `PROJECT_STATUS.md` and the tracker as they are affected.
- **Stay in scope.** No extra features, models or dependencies; the locked stack does not change.
  Every new dependency, model, dataset or tool gets a row in
  `docs/research/licensing-and-commercialization.md`.
- **Verify before claiming.** Run the checks and report real results; never weaken a test to get green.
  The gate for a backend change is `ruff format --check`, `ruff check`, `mypy` (both platforms),
  `pytest --cov` reporting **100%** coverage (the working rule; no automatic threshold); for the front end `npm run typecheck`, `oxlint --deny-warnings`,
  `npm test`, `npm run build`.
- **Ask when unsure.** A question is cheaper than a wrong assumption baked into the codebase.
- **Independent review.** Every PR gets a read-only review by a different tool (Codex) in a disposable
  worktree; the review text and the author's answers are posted on the PR; every finding is fixed or
  answered; then CI must be green *on the exact head commit*; then a rebase merge.

## 11.3 Milestones

| Milestone | Theme | State |
|---|---|---|
| M0 | foundation: repo, tooling, CI, test harness | done |
| M1 | domain: identity, person, evidence, merge/split, property tests | done |
| M2 | persistence: SQLite, migrations, repositories, storage, vector index, erasure, recovery | done |
| M3 | ML worker and the single-image processing pipeline | done (with fake models in tests) |
| M4 | API and desktop shell: the complete image workflow | done on the development profile |
| M5 | **first real recognition**: naming, corrections, merge/split, lifecycle (recycle/delete/forget), search; plus real models (buffalo_l), measured policy, CUDA | in progress: naming, corrections, unplaced faces, merge/split, CUDA and the measured policy done; real host wiring, lifecycle, retrieval and the real-world gate remain |
| M6 | movies | not started |
| M7 | cameras | not started |
| M8 | packaging and distribution (PyInstaller, bootstrapper) | not started |

## 11.4 The test tracker

`docs/plans/TESTING_IMPLEMENTATION_TRACKER.md` lists every planned test as `TST-nnn` with a status
(for example `PASSING`, `COMPLETE`, `IN_PROGRESS`, `BLOCKED`). It is how the project knows what "done" means per feature.
Examples: TST-040 candidate retrieval, TST-043 pipeline killed at each stage then recovered, TST-044
initial ML evaluation, TST-058 merge/split.

## 11.5 GitHub issues

Decided-but-unbuilt work and provisional decisions are tracked as issues (for example #69 model
selection, #80 installation sweep, #137 library-profile guard). When something becomes pending, an
issue is opened for it.

---
# Part 12. Putting it together

## 12.1 Walkthrough: one photograph, from click to person

Every step names the file to open. Read them in this order and the whole system will click.

| # | What happens | Where to look |
|---|---|---|
| 1 | The window starts; the shell makes a token, starts Python, reads the handshake | `desktop/src-tauri/src/sidecar.rs`, `lib.rs`; `backend/api/host.py` |
| 2 | The backend opens the library: lock, migrations, storage, index coordinator, **startup recovery**; then the scheduler starts | `backend/app/lifecycle.py` (`open_library`), `backend/api/startup.py`, `backend/app/recovery/startup.py` |
| 3 | The page asks the shell where the backend is, then polls `/readiness` until `READY` | `frontend/src/app/BackendGate.tsx`, `frontend/src/native/backend.ts` |
| 4 | You pick an image; the shell's file picker returns its path; the page calls `POST /sources/import` | `frontend/src/features/library/LibraryPage.tsx`, `backend/api/routes/sources.py` |
| 5 | Import: inspect and fingerprint the file (SHA-256), record an Artifact and a Source in one transaction | `backend/app/sources/import_source.py`, `artifact_storage.py`, `referenced_artifacts.py` |
| 6 | You press process: `POST /sources/{id}/process`; one transaction writes the Job, the ProcessingRun and the frozen snapshot; answer `202` | `backend/api/routes/processing.py`, `backend/app/processing/process_source.py`, `configuration.py` |
| 7 | The scheduler wakes, claims the job (priority order, with a lease), the runner starts it | `backend/api/scheduler.py`, `backend/app/processing/scheduler.py`, `runner.py` |
| 8 | Decode the pixels; build the plan from installed packages; ask the worker (pipe + shared memory) to detect | `backend/infrastructure/media/image.py`, `backend/app/runtime/worker_config.py`, `perception_client.py`, `backend/ml/worker/perception_handlers.py` |
| 9 | Inside the worker: SCRFD letterbox, ONNX Runtime on CUDA or CPU, decode boxes, NMS | `backend/ml/perception/detection.py`, `backend/ml/worker/onnx_session.py` |
| 10 | Each face is written as a `PENDING` Observation; alignment warps it to 112x112; ArcFace gives 512 numbers; written as a `PENDING` Representation | `backend/ml/perception/alignment.py`, `backend/app/processing/pending_output.py` |
| 11 | Retrieval: this run's own faces (run-local index) plus the global USearch index; candidates revalidated against SQLite and grouped by identity | `backend/app/recognition/retrieval.py`, `assessment.py`, `backend/infrastructure/indexing/` |
| 12 | The reasoner decides `MATCH_EXISTING`, `CREATE_NEW` or `ABSTAIN` with a recorded reason | `backend/app/recognition/reasoner.py` |
| 13 | Decisions are persisted privately; a `FINAL` checkpoint is written; the run becomes `FINALIZING` | `backend/app/processing/execute_job.py`, `repository.py` |
| 14 | **Acceptance**, one transaction: revalidate, activate, write Occurrences and Evidence, create identities, append index `ADD` operations, complete the run | `backend/app/processing/accept_run.py` |
| 15 | After the commit: the coordinator applies the index operations; an event is published | `backend/app/memory/index_coordinator.py`, `backend/api/events.py` |
| 16 | The page receives the event, invalidates the right queries, refetches, and shows the faces and people | `frontend/src/api/events.ts`, `invalidation.ts`, `frontend/src/features/source/SourcePage.tsx` |
| 17 | You rename or correct: `PATCH /people/{id}`, `POST /occurrences/{id}/reassign`, merges and splits; each is one atomic transaction that writes Evidence | `backend/app/people/use_cases.py`, `backend/app/identities/corrections.py`, `use_cases.py`, `backend/api/routes/` |
| 18 | You close the window; stdin closes; the backend stops the scheduler and workers, closes the library; next start recovers whatever was interrupted | `backend/api/host.py`, `backend/api/startup.py`, `backend/app/recovery/startup.py` |

## 12.2 A suggested reading path

1. `AGENTS.md`, then `.agents/CONTEXT.md` (skim), then `docs/plans/PROJECT_STATUS.md`.
2. `docs/research/tech-stack.md` sections 1 to 5, 15, 19. (Why each technology.)
3. `backend/app/recognition/reasoner.py`: small, central, and a good test of your Python.
4. `backend/infrastructure/db/unit_of_work.py` and one use case, for example
   `backend/app/people/use_cases.py`.
5. `backend/app/sources/models.py` and `backend/app/memory/models.py`: the database tables as classes.
6. `backend/app/processing/execute_job.py` top to bottom, then `accept_run.py`.
7. `backend/ml/worker/loop.py`, `backend/ml/supervisor/supervisor.py`.
8. `tests/unit/test_recognition_reasoner.py` (how a unit test reads), then
   `tests/integration/test_migration_0009.py` (how a migration test reads).
9. `frontend/src/app/routes.tsx`, `BackendGate.tsx`, one feature folder.
10. `docs/specs/identity-and-memory-model-v1.md` (long; read the concept sections, not all of it).
11. `docs/research/measured-operating-point.md` and `reference-model-selection.md`.

## 12.3 Exercises

Each has an answer you can verify by running something.

1. In `uv run python`, compute the cosine similarity of `[1, 0]` and `[1, 1]` with NumPy. (Expect
   about 0.707 after normalising.)
2. Open `reasoner.py` and write down, on paper, the outcome and reason for: score 0.2 on a policy with
   ceiling `-1`, threshold `0.35`; then score 0.9 with no runner-up; then no candidates at all.
3. Run `uv run pytest tests/unit/test_recognition_reasoner.py -q`. Break one comparison in
   `reasoner.py` (change `>=` to `>`), run it again, and read which test fails. Restore it. This is
   hand mutation testing.
4. Open the SQLite file of a development-profile library (or a test database) with any SQLite viewer
   and find the `sources`, `observations` and `identities` tables. Count rows by `state`.
5. In `frontend/src/api/invalidation.ts`, explain why a `processing_run.updated` event invalidates the
   identities list as well as the run.
6. Read `docs/research/measured-operating-point.md` and explain, in your own words, why the 100%
   precision on the selection half did not mean the policy was good.
7. Find three places where a function takes `clock` or `new_id` as a parameter and say what that makes
   possible in the tests.
8. Explain what would be lost, and what would not, if `local-models/state/indexes` were deleted while
   the app is closed. (Answer: nothing authoritative; the index is rebuilt at the next start.)

## 12.4 Glossary

**ABSTAIN**: the decision "I am not sure"; no identity is assigned automatically.
**Acceptance**: the single transaction that makes a finished run's private output authoritative.
**ACID**: atomic, consistent, isolated, durable: the guarantees of a transaction.
**ANN / approximate nearest neighbour**: finding vectors close to a query without checking all of them.
**Artifact**: a file the system tracks (original, copy, model export) with a hash and a state.
**ArcFace**: the face-embedding model family used (ResNet-50 variant); trained with an angular margin loss.
**Async / await**: Python and JavaScript syntax for tasks that wait without blocking each other.
**Atomic**: all-or-nothing; used of transactions and of file renames.
**Authoritative**: the truth; not rebuildable. Opposite: derived.
**Bearer token**: a secret sent in the `Authorization` header; here, per launch.
**Branch**: a movable name for a line of Git commits.
**buffalo_l**: the InsightFace model pack (SCRFD-10GF + ArcFace R50) used for real recognition.
**Calibration**: making a score mean a probability. Here "calibrated" only means thresholds were measured.
**Checkpoint**: a saved progress marker of a run; `FINAL` holds the full decision evidence.
**CHECK constraint**: a database rule that refuses values outside a listed set.
**CI**: continuous integration: automated checks on every pull request.
**Closure**: a function that remembers variables from where it was defined.
**Component / ComponentVersion**: a replaceable model role (detector, embedder) and a version of it.
**Conventional Commits**: the `type(scope): summary` commit header format.
**Cosine similarity**: how alike the directions of two vectors are, -1 to 1.
**CUDA / cuDNN / cuBLAS**: NVIDIA's GPU computing platform and its neural-network and matrix libraries.
**Dataclass**: a Python class whose constructor and comparison are generated from its fields.
**Dependency injection**: passing in what a function needs (a clock, an id maker) instead of reaching for it.
**Derived**: can be rebuilt from authoritative data (the vector index, caches).
**Detection**: finding faces and their boxes in an image.
**DOM**: the browser's tree of page elements.
**Embedding**: a vector that represents something (here, a face) so that distance means difference.
**Enum**: a fixed set of named values.
**Evidence**: an immutable record of why a decision was made.
**Execution provider**: an ONNX Runtime back-end for particular hardware (CPU, CUDA, ...).
**Execution segment**: a stretch of a run on one model variant; a new one starts after a real fallback.
**FastAPI**: the Python web framework used for the backend.
**False accept / false reject**: wrongly saying "same person" / wrongly failing to.
**Fixture (pytest)**: reusable test set-up.
**Foreign key**: a column referring to another table's primary key.
**Forget**: the only operation that removes an identity's biometric vectors (designed).
**Frozen (dataclass)**: cannot be changed after creation.
**Generator**: a function that `yield`s values one at a time.
**GIL**: Python's lock letting one thread run Python code at a time.
**Hash (SHA-256)**: a fixed-size fingerprint of data.
**HNSW**: the graph algorithm behind the vector index.
**Hook (git)**: a script run at commit/push time; (React) a `use...` function.
**Identification (1:N)**: who among everyone known is this?
**Identity**: one visual subject, named or unnamed (vs Person: the named human).
**Idempotent**: doing it twice has the same effect as once.
**Index (database)**: a structure that speeds lookups on a column. **Index (vector)**: the USearch structure.
**IndexOperation**: a queued ADD/REMOVE for the vector index (the outbox).
**Inference**: running a trained model. (Training is not done here.)
**Invariant**: something that must always be true.
**JSON**: text format of nested dictionaries, lists, strings, numbers, booleans, null.
**Job**: the scheduling record of work to do (vs ProcessingRun: its history).
**Landmarks**: five face points (eyes, nose, mouth corners) used for alignment.
**Library root**: the folder holding your database and files.
**Lifespan (FastAPI)**: code run at server start and stop.
**Lineage**: structural history of merges and splits between identities.
**Loopback**: `127.0.0.1`, your own machine.
**Margin**: the lead the best candidate must have over the runner-up.
**Metric learning**: training so that distance reflects identity.
**Migration**: a versioned script that changes the database schema.
**Mock / double / fake**: a stand-in used in tests.
**mypy**: the Python type checker. **ruff**: the Python linter/formatter.
**NMS**: non-maximum suppression: removing duplicate overlapping boxes.
**Normalisation (L2)**: scaling a vector to length 1.
**Observation**: a detected face in a source.
**Occurrence**: an appearance of an identity within a source.
**ONNX / ONNX Runtime**: model file format / the engine that runs it.
**Open-set**: strangers are possible; the system may say "nobody I know".
**Optimistic concurrency**: edit only if the row's revision is unchanged.
**ORM**: object-relational mapper (SQLAlchemy).
**Outbox pattern**: record intent in the database, perform the side effect afterwards.
**Person**: the named human, separate from the visual Identity.
**Policy (decision)**: the thresholds and margin that govern recognition.
**Precision / recall**: share of accepted that is right / share of rightable that was accepted.
**Profile (development / real)**: which catalog and perception the host runs with.
**ProcessingRun**: one processing of a source with frozen settings.
**Protocol (Python)**: a structural interface. **Protocol (wire)**: the worker message contract.
**Pull request**: a request to merge a branch, with reviews and checks.
**Pydantic**: validated, typed data models used by FastAPI.
**Query-only**: a search that never stores what it searched with.
**Rebase**: replay a branch's commits on top of a newer base.
**Recycle**: hide a source but keep its bytes and memory (restorable).
**Representation**: the stored face vector with provenance.
**RepresentationSpace**: a family of mutually comparable vectors.
**Repository (pattern)**: a class wrapping the queries of one kind of data.
**Revision**: the version counter used for optimistic updates (also: an Alembic migration id).
**Runtime package**: an installed folder of model files and a manifest.
**Runtime variant**: an export on a specific provider and device.
**SCRFD**: the face detector model used.
**Session (SQLAlchemy)**: a workspace for loading and saving rows.
**Shared memory**: a memory block two processes can both read.
**Sidecar**: a helper program started and owned by the main app (here, the Python backend).
**Snapshot (configuration)**: the frozen settings a run executed under.
**Source**: an imported image (video later).
**Spawn**: start a fresh Python process that re-imports your code.
**State machine**: a thing that moves through a fixed set of states by guarded transitions.
**StrEnum**: an enum whose values are strings.
**Supervisor**: the component that starts, watches, restarts and stops the worker.
**Tauri**: the toolkit for the desktop shell (Rust core + web view).
**Tensor**: an array of any number of dimensions.
**Threshold**: a cut-off number a score is compared with.
**Transaction**: a group of database changes that succeed or fail together.
**Type hint**: a note about a value's type, checked by mypy/tsc.
**Unit of work**: this project's wrapper for a read or write transaction with retry.
**USearch**: the vector-index library.
**uv**: the Python package and environment manager.
**Verification (1:1)**: are these two faces the same person?
**Vector**: an ordered list of numbers.
**WAL (write-ahead log)**: SQLite's mode where changes go to a side log first.
**Wilson interval**: a confidence range for a proportion measured on few samples.
**Worker (ML)**: the separate process that runs the models.
**Worktree (git)**: an extra checkout of the repository in another folder.

## 12.5 Further reading

- Python: the official tutorial (docs.python.org/3/tutorial); *Automate the Boring Stuff with Python*
  for beginners; *Fluent Python* later.
- SQL and SQLite: sqlite.org (especially "Write-Ahead Logging" and "Isolation in SQLite"); SQLAlchemy 2.0
  tutorial; Alembic documentation.
- Web: MDN Web Docs (developer.mozilla.org) for HTML, CSS, JavaScript and HTTP; the FastAPI tutorial;
  the React documentation (react.dev); the TypeScript handbook; TanStack Query docs; Tailwind docs.
- Rust and Tauri: *The Rust Programming Language* ("the book", free online); v2.tauri.app.
- Machine learning: 3Blue1Brown's neural-network series for intuition; the ArcFace paper ("ArcFace:
  Additive Angular Margin Loss for Deep Face Recognition"); the InsightFace repository; the ONNX
  Runtime documentation on execution providers.
- Software practice: *The Pragmatic Programmer*; Martin Kleppmann's *Designing Data-Intensive
  Applications* for transactions, recovery and the outbox pattern.

## 12.6 Keeping this guide true

This guide describes `main` as of 2026-10-08. When the project changes in a way a learner would notice
(a new milestone lands, a layer moves, a decision is reversed), update the affected part and its
**[built]/[designed]** markers in the same pull request, as the documentation rules require for the
other status documents. When this guide and a spec disagree, the spec is right and this guide needs
the fix.
