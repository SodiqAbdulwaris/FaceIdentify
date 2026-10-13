# Python 04 Classes, dataclasses and enums

## 1. What this is and why it exists

A **class** is a blueprint for objects that bundle data with the functions that work on it. Three
special kinds of class carry most of this codebase: **dataclasses** (plain bundles of validated data),
**enums** (a fixed vocabulary, such as the states of an identity) and **protocols** (an interface that
lets a test substitute a fake). A fourth kind, the database model classes, is covered in
[SQLAlchemy](../../02-data-and-storage/05-sqlalchemy-and-repositories.md).

## 2. Where it lives

| Idea | Real example |
|---|---|
| A frozen, validated dataclass | `DecisionPolicy` in `backend/app/recognition/reasoner.py` |
| A property on a class | `DecisionPolicy.automatic_matching` |
| A `StrEnum` | `IdentityState` in `backend/app/identities/models.py` (and `RecognitionOutcome`, `Reason`) |
| A class method that builds an object | `ProcessingRequestV1.parse(...)` in `backend/app/processing/configuration.py` |
| A `Protocol` | `WorkerHandle` in `backend/ml/supervisor/process.py` |
| A class with `__enter__`/`__exit__` | `UnitOfWork` sessions; `open_library` in `backend/app/lifecycle.py` |

## 3. How it works

### Classes

```python
class Person:
    def __init__(self, name):        # runs when you write Person("Ada")
        self.name = name             # `self` is the object being built

    def rename(self, new_name):      # a method: a function that belongs to the object
        self.name = new_name

p = Person("Ada"); p.rename("Grace"); p.name      # 'Grace'
```

- **Attributes** are values on an object (`self.name`); **methods** are functions on it.
- **Inheritance**: `class B(A)` starts as a copy of `A` and adds or replaces parts. The database models
  inherit from a shared `Base`.
- `@property` makes a method look like an attribute (`policy.automatic_matching`, no parentheses).
- **Dunder ("double underscore") methods** customise behaviour: `__init__` (build), `__repr__` (how it
  prints), `__eq__` (what `==` means), `__post_init__` (a dataclass hook).
- `@classmethod` / `@staticmethod` attach a function to the class rather than an object.

### Dataclasses: "make invalid states impossible"

A `@dataclass` writes `__init__`, `__repr__` and `__eq__` for you from a list of fields. The real one:

```python
@dataclass(frozen=True, slots=True)
class DecisionPolicy:
    version: str
    min_detection_score: float
    match_threshold: float
    margin: float
    new_identity_ceiling: float

    def __post_init__(self) -> None:          # runs after construction: validate here
        if not -1.0 <= self.new_identity_ceiling <= self.match_threshold <= 2.0:
            raise ValueError("the thresholds must satisfy ...")
```

`frozen=True` makes instances unchangeable (so they are safe to share and to use as dictionary keys);
`slots=True` saves memory and forbids stray attributes. The pattern, used everywhere in the project, is
**validate once in `__post_init__`, then trust the object**: if you hold a `DecisionPolicy`, its numbers
are consistent, with no need to re-check them in the code that uses it.

### Enums

An `Enum` is a fixed set of named values; a `StrEnum` makes each value a string. The state of nearly
everything in the database (a job, a run, a representation, a source) is one of these:

```python
class IdentityState(StrEnum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    MERGED = "MERGED"
    FORGOTTEN = "FORGOTTEN"
    DELETED = "DELETED"
```

The database stores the text, and a `CHECK` constraint refuses any other text (generated from the
enum).

### Protocols

A **Protocol** (from `typing`) says "anything that has these methods", without inheritance. The
supervisor needs a "worker handle" with `connection`, `is_alive()` and `kill()`; a real process and a
test double both fit. That is how tests simulate a worker that dies without starting a real one.

## 4. Try it

**Works with no models. Verified 2026-10-12.** In `uv run python`:

1. A frozen, validated dataclass in action:

   ```python
   >>> from backend.app.recognition.reasoner import DecisionPolicy
   >>> good = DecisionPolicy("v1", 0.5, 0.6, 0.1, 0.3)
   >>> good.automatic_matching
   True
   >>> DecisionPolicy("off", 0.5, 1.5, 0.1, 0.3).automatic_matching     # threshold above 1: matching is off
   False
   >>> DecisionPolicy("bad", 0.5, 0.2, 0.1, 0.3)                      # ceiling 0.3 is above threshold 0.2
   ValueError: the thresholds must satisfy -1 <= new_identity_ceiling <= match_threshold <= 2
   >>> good.margin = 0.5
   dataclasses.FrozenInstanceError: cannot assign to field 'margin'
   ```

2. An enum:

   ```python
   >>> from backend.app.identities.models import IdentityState
   >>> list(IdentityState)
   [<IdentityState.PENDING: 'PENDING'>, <IdentityState.ACTIVE: 'ACTIVE'>, <IdentityState.MERGED: 'MERGED'>, <IdentityState.FORGOTTEN: 'FORGOTTEN'>, <IdentityState.DELETED: 'DELETED'>]
   >>> IdentityState.ACTIVE == "ACTIVE"
   True
   >>> IdentityState("NOPE")
   ValueError: 'NOPE' is not a valid IdentityState
   ```

3. Make your own frozen dataclass and use it as a dictionary key:

   ```python
   >>> from dataclasses import dataclass
   >>> @dataclass(frozen=True, slots=True)
   ... class P:
   ...     a: int
   >>> P(1) == P(1), {P(1): "key"}
   (True, {P(a=1): 'key'})
   ```

4. Find the protocol: open `backend/ml/supervisor/process.py` and read `class WorkerHandle(Protocol)`.
   Then open `tests/integration/test_ml_supervisor.py` and read `class Scripted` (line 488): a fake
   that satisfies it with a pipe and a thread instead of a process.

## 5. Change it

Add a rule to the policy validation **in a scratch copy**: paste the `DecisionPolicy` class into
`uv run python` with one extra line in `__post_init__`,
`if self.margin > self.match_threshold: raise ValueError("margin too large")`. Construct the valid
policy from step 1: it still works (`0.1 > 0.6` is false). Construct it with `margin=0.7`: it now fails.
In the repository the safe route for a real rule change is a spec decision first (the thresholds are
a recorded owner decision), then the change to `__post_init__`, then the tests:

```bash
uv run pytest tests/unit/test_recognition_reasoner.py tests/unit/test_conservative_policy.py -q
```

Expected: pass. Break a bound (say, change `2.0` to `1.0` in the real validation) and the test that
builds the "matching off" policy with `match_threshold` above 1 fails: that test exists because
disabling automatic matching is a decision of the owner.

## 6. Break it on purpose

Forget `frozen=True` and mutate: nothing stops `policy.margin = 0` later, in some other module, and the
validation in `__post_init__` is silently bypassed. That is the bug class `frozen=True` removes. Or
compare an enum to a misspelled string: `IdentityState.ACTIVE == "ACTVE"` is `False` with no error,
which is why code compares against the enum members, not typed strings.

## 7. Exercises

1. Which two fields of `DecisionPolicy` must satisfy `new_identity_ceiling <= match_threshold`?
2. Why is a `StrEnum` better than the plain strings `"ACTIVE"` scattered through the code?
3. What does `__post_init__` do and when does it run?
4. What is the point of a `Protocol` like `WorkerHandle`?

**Answers**

1. `new_identity_ceiling` and `match_threshold` (also within -1 and 2); `margin` is checked separately.
2. A typo is an immediate `AttributeError`/`ValueError`, the type checker knows the legal values, and the
   same vocabulary generates the database `CHECK` constraint.
3. It validates the fields right after `__init__`; it runs on every construction, so an invalid policy
   cannot exist.
4. It names exactly what a collaborator must offer so a real worker process and a test double are
   interchangeable.

## 8. Related files

- Previous: [03 Functions and errors](03-functions-and-errors.md) · Next: [05 Modules, types, files and hashes](05-modules-types-files.md)
- [`backend/app/recognition/reasoner.py`](../../../../../backend/app/recognition/reasoner.py)
- [Decision policy](../../03-backend/recognition/03-decision-policy.md)
