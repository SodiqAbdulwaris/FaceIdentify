# Architecture 01 Layers and rules

## 1. What this is and why it exists

[Start-here lesson 04](../../00-start-here/04-layers-and-repository-map.md) introduced the four layers. This lesson goes
one level deeper: the **rules** that keep them clean, where each rule is enforced (by tests, by types, or only by
review), and how to check them yourself. The rules are what make a codebase this size safe to change: a rule such as "a
merge must be atomic" lives in exactly one place, so fixing or auditing it is one place too.

## 2. Where it lives

| Rule | Source of the rule | Enforced by |
|---|---|---|
| `api` calls `app`, `app` uses `infrastructure`; never the other way | `docs/specs/IMPLEMENTATION_ARCHITECTURE.md`, `AGENTS.md` | review and the `grep` checks below (no tool forbids it) |
| Routes are thin: validate, call a use case, shape the answer | `.agents/rules/scope.md`, route module docstrings | review; `tests/integration/test_api_*.py` |
| Use cases flush but never commit; the caller owns the transaction | `PERSISTENCE_IMPLEMENTATION.md` section 26 | `tests/integration/test_transaction_rollback.py` |
| The ML worker never touches SQLite | `.agents/rules/scope.md` | the worker imports nothing from `backend.app` (grep) |
| USearch never decides identity truth; SQLite revalidates every candidate | `PERSISTENCE_IMPLEMENTATION.md` section 23 | `tests/integration/test_ann_candidate_revalidation.py` |
| ML runs outside database transactions | `backend/app/processing/execute_job.py` | `tests/integration/test_execute_processing_job.py` |
| Each side effect is recorded as intent first (outbox) | `PERSISTENCE_IMPLEMENTATION.md` section 17 | `tests/integration/test_index_coordinator.py` |
| Time and ids are injected (`clock`, `new_id`) | `.agents/rules/testing.md` | tests use `FrozenClock` and `SeededUUIDs` |
| Fail closed at trust boundaries | module docstrings (`validate_launch_token`, `require_abstain_first`, safe storage keys) | the tests named in each |

## 3. How it works

The dependency direction (an arrow means "may import"):

```text
backend/api  ──►  backend/app  ──►  backend/infrastructure
                      │
                      └──►  backend/ml   (only the contracts and the client side; the worker side never imports app)
```

Why each rule exists:

- **Thin routes** keep HTTP details (status codes, JSON, headers) out of the rules, so the same use case can be called by
  a route, by startup recovery and by a test.
- **Use cases take a `session` and never commit** so several can compose into one atomic `UnitOfWork.write` and so a
  retry of the whole transaction is safe ([transactions](../../02-data-and-storage/03-transactions-and-unit-of-work.md)).
- **The worker is a separate process that never reads the database** so a crash in native model code can only cost one
  request and a restart, never corrupt your data. It receives pixels over shared memory and returns boxes and vectors;
  the backend writes them.
- **ML outside transactions**: a slow model call must never hold SQLite's one write lock.
- **Injected clock and ids** make tests deterministic: no assertion ever depends on the real time.
- **Fail closed**: a malformed checkpoint, an unknown policy field, an unrecognised token, a storage key that is not
  `<managed dir>/<32 hex>` is refused, not repaired or guessed.

## 4. Try it

**Works with no models. Verified 2026-10-12.**

1. The layering, as three `grep`s that must print nothing (from the repository root; bash):

   ```bash
   grep -rln "from backend.api" backend/app backend/infrastructure backend/ml --include=*.py
   grep -rln "from backend.app" backend/infrastructure backend/ml --include=*.py
   grep -rn "sqlalchemy\|sqlite3" backend/ml --include=*.py
   ```

   Expected: nothing for all three. The third is the "worker never touches SQLite" rule: the whole `backend/ml` tree does
   not import SQLAlchemy or `sqlite3`.
2. Who talks to the worker side? `grep -rln "from backend.ml" backend/app --include=*.py` lists exactly
   `perception_client.py`, `pending_output.py` and `execute_job.py` (the only application files that know the worker
   exists).
3. Routes are thin: open any `backend/api/routes/*.py` and count what they import from `backend.app`: use cases and models
   only. No route contains the merge algorithm; `identity_changes.py` calls `merge_identities`.
4. See a rule enforced: `uv run pytest tests/integration/test_transaction_rollback.py tests/integration/test_ann_candidate_revalidation.py -q`.
   Expected: pass.
5. The architecture spec itself: `docs/specs/IMPLEMENTATION_ARCHITECTURE.md` section 8 (module layout). Skim its table of
   packages and compare with `ls backend/app`. A few packages in the spec (`cameras`, `search`, `core`, `api`) are empty
   scaffolds today.

## 5. Change it

When you are about to add code, ask the three placing questions and write down the answer in your implementation entry:
*What does it decide?* (rule: `backend/app/<topic>/`) *What does it touch?* (files, SQLite, the index: `infrastructure`)
*Who calls it?* (HTTP: `api`). Then check with step 1 after. If a rule must change (for example allowing a route to
write directly), that is an owner decision recorded in the specs, not an edit.

## 6. Break it on purpose

Add `import sqlite3` to any file in `backend/ml` and run step 1's third `grep`: it now prints that file. Nothing fails
automatically; the rule is kept by this check and by review. That is why it is documented here and why reviewers are told
to read `AGENTS.md` and the rules. (Revert with `git restore`.)

## 7. Exercises

1. Which layer would a function that hashes a file belong to?
2. Why can a use case not call `session.commit()`?
3. Why does the ML worker not read the database?
4. A route needs the same logic as startup recovery. Where does the logic go?

**Answers**

1. `backend/infrastructure/storage/` (it touches files and knows no business rule).
2. The unit of work owns the transaction and may retry the whole function; a commit inside would repeat committed work.
3. Isolation: a crash or hang in native model code must not be able to corrupt or lock the database.
4. In `backend/app/<topic>/` as a use case; both the route and recovery call it.

## 8. Related files

- Previous: [Architecture index](README.md) · Next: [02 HTTP and FastAPI](02-http-and-fastapi.md)
- [`docs/specs/IMPLEMENTATION_ARCHITECTURE.md`](../../../specs/IMPLEMENTATION_ARCHITECTURE.md), [`.agents/rules/scope.md`](../../../../.agents/rules/scope.md)
- [Layers and the repository map](../../00-start-here/04-layers-and-repository-map.md)
