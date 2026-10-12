# Python 06 Iterators, decorators and concurrency

## 1. What this is and why it exists

Three ideas that look strange the first time and then appear on every page. A **generator** produces
items one at a time instead of building a whole list. A **decorator** (`@something`) registers or
modifies the function written under it; it is how a Python function becomes a web route or a test
fixture. And **concurrency**, doing several things at once, comes in three forms (threads, processes,
async), and this project uses all three for different reasons.

## 2. Where it lives

| Idea | Real example |
|---|---|
| Generator in a test fixture | `tests/fixtures/persistence.py`: `yield engine` hands the engine to the test, then cleans up after it |
| Decorator that makes a route | `@router.post("/{source_id}/process", status_code=202)` in `backend/api/routes/processing.py` |
| Decorator that makes a fixture | `@pytest.fixture` (`clock`, `new_id`, `app_dirs`) |
| Decorator that builds a context manager | `@contextmanager` on `open_library` in `backend/app/lifecycle.py` |
| A thread so the web server stays responsive | `anyio.to_thread.run_sync(self._run_once)` in `backend/api/scheduler.py` |
| A separate process | `multiprocessing.get_context("spawn")` in `backend/ml/supervisor/process.py` |
| Async | the scheduler loop (`async def _run`), the face-search route (`async def search_face`), the WebSocket |

## 3. How it works

### Iterators and generators

An **iterator** produces one item at a time. A **generator function** uses `yield` instead of `return`
and pauses between items, so a huge sequence never sits in memory.

```python
def numbers():
    n = 0
    while True:
        yield n
        n += 1

g = numbers()
next(g), next(g), next(g)       # (0, 1, 2)
```

A **test fixture** uses the same pause: code before `yield` sets something up, the value after `yield`
goes to the test, and code after the test finishes runs as cleanup.

### Decorators

A decorator is a function that wraps another function, written with `@` above it.

```python
def shout(fn):
    def wrapper(*args, **kwargs):
        return fn(*args, **kwargs).upper()
    return wrapper

@shout
def hello(name):
    return f"hello {name}"

hello("ada")       # 'HELLO ADA'
```

You can use decorators long before you can write one. Read `@something(...)` as *"register or modify
the function below with these settings"*: `@dataclass(frozen=True)` wraps a class,
`@router.post("/import", status_code=201)` registers the function as the handler of `POST /import`,
`@pytest.fixture` tells pytest "this builds a test dependency".

### Concurrency: threads, processes, async

| Tool | What it is | Why this project uses it |
|---|---|---|
| **Threads** (`threading`) | Several lines of execution in one process, sharing memory. Python's *global interpreter lock* lets only one run Python code at a time, so threads help with *waiting* (disk, database), not heavy computing. Danger: two threads changing the same data; fix it with a `Lock` | The scheduler runs the blocking processing work in a thread so the web server answers requests while an image is being processed |
| **Processes** (`multiprocessing`, `subprocess`) | Separate programs with separate memory. They truly run in parallel and a crash in one cannot corrupt another | The ML worker is a separate process started with **spawn** (a fresh interpreter that re-imports your code; on Windows this is why a script that starts workers needs an `if __name__ == "__main__":` guard) |
| **Async** (`async def` / `await`, `asyncio`) | One thread switching between many tasks at the points where each says `await` ("I am waiting; run someone else") | FastAPI, the WebSocket server and the scheduler loop |

```python
async def handler():
    data = await fetch()        # pause here, let other tasks run
    return data
```

**Rule:** never run a slow, blocking call directly inside an `async def`; hand it to a thread
(`await anyio.to_thread.run_sync(slow_function)`). Startup does exactly that to open the library, and the
scheduler does it for each `run_once` call. The route functions in `backend/api/routes/` are plain
`def`, not `async def`, for the same reason: FastAPI then runs them in a worker thread itself, so a slow
database query cannot freeze the event loop.

The processes talk through **pipes** (messages) and **shared memory** (the pixels of an image are put in a
block both processes can read, so large arrays are not copied through the pipe).

## 4. Try it

**Works with no models. Verified 2026-10-12.** In `uv run python`:

1. A generator and a decorator:

   ```python
   >>> def numbers():
   ...     n = 0
   ...     while True:
   ...         yield n
   ...         n += 1
   >>> g = numbers(); next(g), next(g), next(g)
   (0, 1, 2)
   >>> def shout(fn):
   ...     def wrapper(*a, **k): return fn(*a, **k).upper()
   ...     return wrapper
   >>> @shout
   ... def hello(name): return f"hello {name}"
   >>> hello("ada")
   'HELLO ADA'
   ```

2. Threads share memory, so they need a lock (paste as one block):

   ```python
   import threading
   count = 0
   lock = threading.Lock()
   def work():
       global count
       for _ in range(10000):
           with lock:
               count += 1
   threads = [threading.Thread(target=work) for _ in range(4)]
   for t in threads: t.start()
   for t in threads: t.join()
   print(count)
   ```

   Expected: `40000`. Remove the `with lock:` line (and indent `count += 1` back) and the number may come
   out lower: that is a *race*.
3. Async tasks wait together (paste as one block):

   ```python
   import asyncio, time
   async def fetch(n):
       await asyncio.sleep(0.1)
       return n
   async def main():
       start = time.perf_counter()
       print(await asyncio.gather(fetch(1), fetch(2), fetch(3)), round(time.perf_counter() - start, 1))
   asyncio.run(main())
   ```

   Expected: `[1, 2, 3] 0.1`. Three waits of 0.1 s finished in about 0.1 s in total, not 0.3 s,
   because while one waited the others ran.
4. See each form in this repository:

   ```bash
   grep -n "run_sync" backend/api/startup.py backend/api/scheduler.py
   grep -n "get_context" backend/ml/supervisor/process.py
   grep -n "^async def\|^def " backend/api/routes/face_search.py
   ```

   Expected: threads (`anyio.to_thread.run_sync`) in `startup.py` and `scheduler.py`; `"spawn"` in
   `process.py`; and in `face_search.py` an `async def search_face` that reads the request body without
   blocking and then hands the heavy work to a thread (`anyio.to_thread.run_sync(run)` at the end).

## 5. Change it

Observe the scheduler's design through its test rather than editing it:

```bash
uv run pytest tests/integration/test_api_scheduler.py -q
```

Expected: pass (the tests drive the loop with a fake `run_once` and an explicit wake, with no
`sleep`-based coordination: see the 2026-10-07 entry about the scheduler-degrade test race in
`docs/implementations/`). If you changed `_run` to call `self._run_once()` directly instead of in a
thread, the loop would still pass most tests but would block the event loop during real processing
(requests would stall). That is a bug a unit test cannot see; the rule above is how it is avoided.

## 6. Break it on purpose

In the threads example above, delete the `with lock:` line. Run it several times; sometimes the count is
below `40000`. Real code cannot afford that, which is why shared state in the backend sits behind locks
(`SchedulerService` uses one `asyncio.Event`), is made immutable (`frozen=True`), or lives in the
database where every change is a transaction.

Or call a coroutine without `await`: `fetch(1)` instead of `await fetch(1)` gives
`RuntimeWarning: coroutine 'fetch' was never awaited` (and `filterwarnings = ["error"]` in this
repository's pytest settings would turn that warning into a failing test).

## 7. Exercises

1. What does a fixture's `yield` do?
2. Why does the ML worker use a process and not a thread?
3. Why are most route functions plain `def`?
4. In the async example, why did three waits of 0.1 s take about 0.1 s?
5. Find where the code starts the worker with `spawn` and say what `spawn` means.

**Answers**

1. It hands the set-up value to the test, then resumes after the test to clean up.
2. A crash, hang or memory leak in native model code must not corrupt the backend's data; only a separate
   process gives that isolation (and real parallelism).
3. FastAPI runs a plain `def` route in a worker thread, so blocking database and file work cannot freeze
   the event loop that serves everyone else.
4. `await asyncio.sleep` gives control back to the event loop, which ran the other two meanwhile.
5. `backend/ml/supervisor/process.py` line 58, `multiprocessing.get_context("spawn")`: start a fresh
   Python process that re-imports the code, instead of copying the parent.

## 8. Related files

- Previous: [05 Modules, types, files and hashes](05-modules-types-files.md) · Next: [07 Read a real function](07-read-a-real-function.md)
- [`backend/api/scheduler.py`](../../../../backend/api/scheduler.py)
- [Scheduler and runner](../../03-backend/architecture/05-scheduler-and-runner.md), [the ML worker](../../03-backend/runtime-and-worker/01-worker-and-messages.md)
