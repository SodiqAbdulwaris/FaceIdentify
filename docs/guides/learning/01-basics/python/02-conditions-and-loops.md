# Python 02 Conditions and loops

## 1. What this is and why it exists

Programs make decisions (`if`) and repeat work (`for`, `while`). Almost every important rule in this
project is an `if` chain: the recognition policy is a dozen of them, and the "try the transaction again
if the database is busy" logic is a `while` loop. Reading those two shapes fluently gets you through
most of the backend.

## 2. Where it lives

| Idea | Real example |
|---|---|
| A chain of `if` returns | `IdentityReasoner.decide` in `backend/app/recognition/reasoner.py` |
| A chained comparison | `DecisionPolicy.__post_init__`: `-1.0 <= self.new_identity_ceiling <= self.match_threshold <= 2.0` |
| A `while True` with `try`/`break` | `UnitOfWork.write` in `backend/infrastructure/db/unit_of_work.py` (lines about 105 to 120) |
| `enumerate` | `backend/app/jobs/models.py` line 48: `{priority.value: rank for rank, priority in enumerate(JobPriority)}` |
| `zip(..., strict=True)` | `backend/infrastructure/indexing/representation_index.py` line 349 |
| `next(generator, default)` | `backend/app/runtime/package_store.py` line 130 |

## 3. How it works

### `if`, `elif`, `else`

The block of code under an `if` is whatever is **indented** under it. Indentation is not decoration in
Python; it is the grammar.

```python
score = 0.42
if score >= 0.35:
    print("match")
elif score >= 0.20:
    print("unsure")
else:
    print("different")
```

**What counts as false:** `False`, `None`, `0`, `0.0`, `""`, `[]`, `{}`, `()`, `set()`. Everything else is
true. So `if items:` means "if the list is not empty". A one-line conditional (a *ternary*):
`label = "yes" if ok else "no"`. A **chained comparison** reads like mathematics:
`-1.0 <= ceiling <= threshold <= 2.0` is exactly the validity check on a decision policy.

### `for`

```python
for face in faces: ...                       # each item
for i in range(3): ...                       # 0, 1, 2
for index, face in enumerate(faces): ...     # (0, 'a'), (1, 'b')
for name, score in zip(names, scores): ...   # two lists together
```

`break` leaves the loop now; `continue` skips to the next item. **Never change a list while looping
over it**; build a new one.

### `while`

```python
failed = 0
while True:
    try:
        result = do_the_work()
        break                  # leave the loop
    except Busy:
        failed += 1
        if failed >= 3:
            raise              # give up
```

This is nearly the real shape of `UnitOfWork.write`: run the whole transaction; if SQLite says "busy",
roll back and run it again, up to a limit, then raise `DatabaseBusyError`. Consequence worth
remembering: **the function you pass to `write` may run more than once**, so it must only touch the
database session.

### Comprehensions and friends

```python
squares = [n * n for n in range(5)]            # [0, 1, 4, 9, 16]
big     = [n for n in numbers if n > 10]       # filter
lookup  = {p.key: p for p in packages}         # dict comprehension
unique  = {q.person for q in queries}          # set comprehension
sum(1 for q in queries if q.known)             # count without building a list
any(x > 2 for x in xs); all(x > 0 for x in xs) # does some / every item satisfy a test?
next((e for e in exports if e.file == f), None)  # the first match, or None
```

## 4. Try it

**Works with no models. Verified 2026-10-12.**

1. The truth table, in `uv run python`:

   ```python
   >>> bool([]), bool(0.0), bool("x"), bool(None)
   (False, False, True, False)
   >>> -1.0 <= 0.2 <= 0.35 <= 2.0
   True
   ```

2. A retry loop of your own (paste the whole block; it mimics `UnitOfWork.write`):

   ```python
   failed, attempts = 0, []
   def flaky():
       attempts.append(1)
       if len(attempts) < 3:
           raise RuntimeError("busy")
       return "done"

   while True:
       try:
           result = flaky()
           break
       except RuntimeError:
           failed += 1
           if failed >= 3:
               raise
   print(result, "after", len(attempts), "attempts")
   ```

   Expected: `done after 3 attempts`: it failed twice, was retried, and succeeded on the third try.
3. Comprehensions: `[n * n for n in range(5)]` gives `[0, 1, 4, 9, 16]`; `[n for n in [5, 12, 30] if n > 10]`
   gives `[12, 30]`; `next(x for x in ["a", "bb", "ccc"] if len(x) == 2)` gives `'bb'`.
4. Read the real loop: open `backend/infrastructure/db/unit_of_work.py`, find `def write` and read the
   `while True`. Find where `DatabaseBusyError` is raised and the line that sleeps between attempts.

## 5. Change it

Make the retry give up sooner, **in your scratch copy**, not in the repository: in step 2 change
`failed >= 3` to `failed >= 2` and run it again. Expected: it re-raises `RuntimeError: busy` because the
second failure now ends the loop before the third attempt succeeds. In the real code the limit is the
caller's `TransactionRetry(max_attempts=3, ...)` (`PROVISIONAL_TRANSACTION_RETRY` in
`backend/api/host.py`), and the test that proves exhaustion becomes `DatabaseBusyError` is:

```bash
uv run pytest tests/integration/test_unit_of_work.py -q
```

Expected: pass. If you changed the real code so exhaustion did not raise, tests there would fail.

## 6. Break it on purpose

Remove the indentation under an `if`:

```python
if score >= 0.35:
print("match")
```

Expected: `IndentationError: expected an indented block after 'if' statement`. Mix tabs and spaces and you
get `TabError`. The project formats all code with `ruff format`, so this rarely happens; if you use an
editor, set it to insert four spaces.

## 7. Exercises

1. What does `if items:` mean when `items = []`? What about `items = [0]`?
2. Rewrite `[n for n in nums if n > 10]` as a loop with `append`.
3. In `reasoner.py`, which `if` is checked first and what does it return? Why first?
4. What would happen in `UnitOfWork.write` if `work` committed on its own and was then retried?
5. Open `backend/app/jobs/models.py` and explain what `PRIORITY_RANK` contains and why a rank number is
   better than the priority text for ordering.

**Answers**

1. `[]` is false: the block does not run. `[0]` is true (a non-empty list), even though its item is 0.
2. `out = []` / `for n in nums:` / `if n > 10: out.append(n)`.
3. `if assessment.quality.detection_score < policy.min_detection_score: return abstain(LOW_QUALITY)`. A
   face too poorly detected must neither match nor create anything.
4. The retry would repeat a commit that already happened, so work could be applied twice. That is why `work`
   must be a function of the session only and never commit.
5. A dict of priority text to integer (lowest number = most urgent). Text sorts alphabetically
   (`HIGH` before `INTERACTIVE`), which is wrong; integers sort correctly.

## 8. Related files

- Previous: [01 Values and collections](01-values-and-collections.md) · Next: [03 Functions and errors](03-functions-and-errors.md)
- [`backend/infrastructure/db/unit_of_work.py`](../../../../../backend/infrastructure/db/unit_of_work.py)
- [Transactions and the unit of work](../../02-data-and-storage/03-transactions-and-unit-of-work.md)
