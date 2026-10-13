# Python 03 Functions and errors

## 1. What this is and why it exists

A **function** is a named, reusable block of code. An **exception** is Python's way of saying "this
cannot continue". Together they are most of what a use case looks like: a function that takes what it
needs, does one job, and either returns a result or raises a precise error the caller can handle.
This project also uses functions in an unusual way, as *values you pass in*, to make time and ids
predictable in tests. You will see that on nearly every page.

## 2. Where it lives

| Idea | Real example |
|---|---|
| Keyword-only parameters | `name_identity(session, identity_id, display_name, *, new_id, clock)` in `backend/app/people/use_cases.py` line 169 |
| Functions as values | `clock: Callable[[], datetime]` and `new_id: Callable[[], uuid.UUID]` in the same signature |
| Test stand-ins | `FrozenClock` and `SeededUUIDs` in `tests/fixtures/deterministic.py` |
| A closure | `prepare` defined inside `development_processing` in `backend/api/development.py` (it uses `settings`) |
| Custom errors | `StaleRevisionError`, `IdentityManagerError`, `DatabaseBusyError`, `ApiError` |
| Fail closed | `validate_launch_token` in `backend/api/app.py` refuses anything that is not a canonical 256-bit token |

## 3. How it works

### Defining and calling

```python
def accepted_at(queries, threshold, margin):
    taken = [q for q in queries if q[2] >= threshold and q[2] - q[3] >= margin]
    return len(taken), sum(1 for q in taken if q[4] and q[0] == q[1])

accepted, correct = accepted_at(queries, 0.3544, 0.02)    # the returned tuple is unpacked
```

`def` defines; `return` hands back a value (without `return` the result is `None`). This function is
a simplified version of the idea in `evaluation/measure_operating_point.py`: of the queries a policy
would accept, how many were correct?

### Parameters

```python
def f(x, k=5): ...        # k has a default
f(1, k=3)                 # passed by name
def g(x, *, k): ...       # `*` forces k to be named: g(1, k=3), never g(1, 3)
```

This repository uses keyword-only parameters heavily so a call reads clearly:
`rename_person(session, person_id, "Ada", expected_revision=1, new_id=new_id, clock=clock)`. You never
have to guess which number is which.

### Functions are values (dependency injection)

You can pass a function to another function. Instead of calling `datetime.now()` inside a use case,
the use case **takes a `clock` function**; production passes one that returns the real time, the test
passes one that always says 2026-01-01 00:00 UTC. The same trick makes ids predictable (`new_id` is
`uuid.uuid4` in production and a seeded counter in tests).

```python
def stamp(clock):            # clock is any function returning "now"
    return clock()
stamp(lambda: "frozen")      # lambda: a one-line function with no name
```

This is called **dependency injection**: pass in what a function needs rather than letting it reach
for it. It is why tests in this project can say exactly what time and id a row should have.

### Scope and closures

A name assigned inside a function is local to it. A function defined *inside* another can read the
outer function's variables and keeps them alive: a **closure**.

```python
def make(prefix):
    def label(x): return f"{prefix}-{x}"    # remembers `prefix`
    return label
make("Person")("A1")                        # 'Person-A1'
```

### Exceptions

When something cannot continue, Python **raises** an exception that unwinds the call stack until
something **catches** it. If nothing does, the program stops and prints a *traceback*. Read it from the
**bottom**: the last line says what happened, the lines above say where.

```python
try:
    value = int(text)
except ValueError:
    value = 0                  # handle one specific kind of error
else:
    ...                        # only if no exception
finally:
    cleanup()                  # ALWAYS runs
```

- `raise ValueError("a policy has a version")` creates and throws one.
- `raise Other(...) from error` throws a clearer exception and remembers the original cause.
- Define your own with `class StaleRevisionError(Exception): ...`. The code defines dozens so a caller
  can catch exactly the situation it can handle and let the rest propagate.
- **Fail closed**: when input is invalid or unknown, refuse rather than guess (a malformed checkpoint
  is refused, an unknown policy field is refused).
- `assert condition, "message"` states something that must be true; in tests it is the whole point.

## 4. Try it

**Works with no models. Verified 2026-10-12.**

1. Functions, keyword-only parameters and their errors, in `uv run python`:

   ```python
   >>> def f(a, b=2, *, k): return (a, b, k)
   >>> f(1, k=3)
   (1, 2, 3)
   >>> f(1, 2, 3)
   TypeError: f() takes from 1 to 2 positional arguments but 3 were given
   >>> f(1)
   TypeError: f() missing 1 required keyword-only argument: 'k'
   ```

2. The project's own test clock and id maker:

   ```python
   >>> from tests.fixtures.deterministic import FrozenClock, SeededUUIDs
   >>> c = FrozenClock(); n = SeededUUIDs()
   >>> c(), c.advance(seconds=90)
   (datetime.datetime(2026, 1, 1, 0, 0, tzinfo=datetime.timezone.utc), datetime.datetime(2026, 1, 1, 0, 1, 30, tzinfo=datetime.timezone.utc))
   >>> n(), n()
   (UUID('5ec56e42-4afe-4267-bf21-6f8f586d16bb'), UUID('6bdc8897-3eee-4356-b717-8bc3c9249946'))
   >>> SeededUUIDs()() == SeededUUIDs()()
   True
   ```

   The clock moves only when told to; two id makers with the same seed make the same ids. Nothing
   about a test depends on the real time.
3. Chaining errors:

   ```python
   >>> class StaleRevisionError(Exception): ...
   >>> try:
   ...     try: int("x")
   ...     except ValueError as e: raise StaleRevisionError("revision moved") from e
   ... except StaleRevisionError as e: print(repr(e), "| cause:", repr(e.__cause__))
   StaleRevisionError('revision moved') | cause: ValueError("invalid literal for int() with base 10: 'x'")
   ```

4. See a real function being tested for an error:

   ```bash
   uv run pytest tests/integration/test_person_use_cases.py -k stale -q
   ```

   Expected: `1 passed`. Open that test (`test_rename_rejects_a_stale_revision`, line 267): it calls
   `rename_person` with the wrong `expected_revision` inside `pytest.raises(StaleRevisionError, match="expected 1")`.
   The use case raised exactly the error the API route turns into `409 PERSON_REVISION_CONFLICT`
   (you saw that response in [lesson 07](../../00-start-here/07-run-it-and-see-it-work.md)).

## 5. Change it

Safe change to a **copy**: write your own tiny `rename(name, *, clock)` that returns
`(name, clock())`, call it with `lambda: "t1"` and `lambda: "t2"`, and observe the result depends only
on what you inject. That is the whole benefit. In the repository the corresponding test is
`test_rename_rejects_a_stale_revision`; if you edited `rename_person` so it ignored `expected_revision`,
that test and the property tests in `tests/property/` would fail.

## 6. Break it on purpose

Forget a keyword-only argument, as above (`f(1)`): `TypeError: ... missing 1 required keyword-only
argument: 'k'`. Or catch too much: `except Exception: pass` hides every bug, including typos. The
project catches the narrowest error it can handle and lets everything else propagate to the single
handler in `backend/api/errors.py`, which logs it with a diagnostic id and answers a generic `500`.

## 7. Exercises

1. In `name_identity`'s signature, which parameters can only be passed by name?
2. Why does `rename_person` take `clock` instead of calling `datetime.now(UTC)`?
3. What does `raise X from error` add compared with `raise X`?
4. Why is the traceback read from the bottom?
5. Find another function in `backend/app` with a `*,` in its signature and say what each keyword
   parameter is for.

**Answers**

1. `new_id` and `clock` (everything after the bare `*`).
2. So tests give it a fixed time and can assert exact timestamps; production passes the real clock.
3. It keeps the original error as `__cause__`, so the log shows both what failed and why.
4. The last line is the actual error; the frames above it show the path that led there, outermost first.
5. For example `ProcessSourceUseCase.process(...)` in `backend/app/processing/process_source.py` takes
   `processing_request`, `priority` and `created_by_user_action` by name; each is a decision the caller
   must state, not a position to remember.

## 8. Related files

- Previous: [02 Conditions and loops](02-conditions-and-loops.md) · Next: [04 Classes, dataclasses and enums](04-classes-dataclasses-enums.md)
- [`tests/fixtures/deterministic.py`](../../../../../tests/fixtures/deterministic.py)
- [pytest](../tools/03-pytest.md) for how fixtures hand `clock` and `new_id` to tests
