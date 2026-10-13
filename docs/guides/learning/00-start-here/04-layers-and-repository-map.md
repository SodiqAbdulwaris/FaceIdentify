# 04 Layers and the repository map

## 1. What this is and why it exists

The backend is organised in **layers**. A layer may use the layers below it and never the ones above.
Why? So that a rule such as "a merge must be atomic" lives in exactly one place
(`backend/app/identities/`) and is not scattered across routes; and so that tests can exercise each
layer on its own.

```
 backend/api/            HTTP and WebSocket: routes, errors, events, the sidecar host, the scheduler loop
    |  calls
 backend/app/            application logic grouped by topic ("use cases"): sources, processing,
    |                    recognition, identities, people, memory, jobs, recovery, runtime, settings
    |  uses
 backend/infrastructure/ technical plumbing: database engine and unit of work, storage on disk,
    |                    the vector index, media decoding, shared memory
    |
 backend/ml/             everything about the model worker: the message contract, the supervisor
                         that starts and stops the worker, the worker itself, the face maths
```

Two clarifications the code enforces by habit rather than by tooling:

- `backend/app` never imports `backend.api`, `backend/infrastructure` never imports `backend.app`, and
  `backend/ml` imports neither. You can check this yourself (below).
- The application layer *uses* `backend/ml` to talk to the worker (`perception_client.py`,
  `execute_job.py`); the worker side never knows about the database. This is a hard rule:
  **the ML worker never touches SQLite.**

## 2. Where it lives: the repository map

| Path | Contents |
|---|---|
| `AGENTS.md`, `CLAUDE.md` | The short non-negotiable rules (`CLAUDE.md` includes `AGENTS.md`) |
| `.agents/CONTEXT.md`, `.agents/rules/` | Current state, decisions, and the mandatory rules |
| `docs/specs/` | **Authoritative** architecture and contracts. The schema comes from `PERSISTENCE_IMPLEMENTATION.md` |
| `docs/plans/` | Plans, roadmap, the test tracker, and `PROJECT_STATUS.md` (the one-page status) |
| `docs/implementations/` | One dated entry for every change that was made |
| `docs/guides/`, `docs/strategy/`, `docs/research/` | How-tos, test strategy, stack and model research |
| `docs/guides/learning/` | This guide |
| `backend/api/` | Routes (`routes/`), `host.py`, `startup.py` (lifespan), `scheduler.py`, `events.py`, `errors.py` |
| `backend/app/` | Use cases by topic (see below) |
| `backend/infrastructure/` | `db/`, `storage/`, `indexing/`, `media/`, `resources/` (shared memory) |
| `backend/ml/` | `contracts/` (messages), `supervisor/`, `worker/`, `perception/` (detection and alignment maths) |
| `backend/alembic/` | Database migrations (`versions/0001` to `0010`) |
| `frontend/src/` | `app/`, `api/`, `features/`, `components/`, `native/`, `state/` |
| `desktop/src-tauri/` | The Rust shell |
| `tests/` | Python tests; the folder decides the marker (`unit/`, `contracts/`, `integration/`, `recovery/`, `property/`, `security/`, `concurrency/`, `e2e/`) |
| `evaluation/` | Scripts that measure recognition quality; `evaluation/datasets/` is Git-ignored |
| `scripts/` | `install_reference_models.py`, `smoke_real_models.py` |
| `benchmarks/`, `runtime/`, `packaging/` | Empty scaffolds for later milestones |
| `local-models/` | **Git-ignored**: model weights and local evidence. Never committed |
| `.githooks/` | `commit-msg`, `pre-commit`, `pre-push`, `check-branch-name` |
| `.github/` | CI workflow and the ruleset that protects `main` |

### Inside `backend/app/`

| Folder | What it does |
|---|---|
| `sources/` | Importing images, artifacts (files), recycle / restore / permanent delete, storage cleanup |
| `processing/` | Requesting, claiming, executing, accepting, cancelling, retrying a processing run |
| `recognition/` | Retrieval, assessment, the reasoner (the decision), the face query |
| `identities/` | Identity use cases: create, assign, merge, split, corrections, forget |
| `people/` | Persons: naming, renaming, linking |
| `memory/` | The memory models, the index coordinator, the eraser |
| `jobs/` | The job table and its repository |
| `runtime/` | Runtime packages, the model catalog, planning, the perception client |
| `recovery/` | Startup recovery |
| `settings/` | Small key/value state (`app_state`) |
| `lifecycle.py` | `open_library`: lock, migrate, build engine and storage, recover |

## 3. How it works: a route, a use case, a repository

Read one concrete chain: `POST /people` names an identity.

1. `backend/api/routes/people.py` (`name_an_identity`) validates the body and calls the use case. It
   does not decide anything.
2. `backend/app/people/use_cases.py` (`name_identity`) creates the Person, links it and writes
   Evidence, inside one transaction handed to it as a `session`.
3. `backend/infrastructure/db/unit_of_work.py` (`UnitOfWork.write`) opened that transaction with
   `BEGIN IMMEDIATE`.

That is why routes are called **thin**: they translate between HTTP and a use case.

## 4. Try it

**Works with no models. Verified 2026-10-12.**

1. Look at the layers on disk:

   ```bash
   ls backend backend/api backend/app backend/infrastructure backend/ml
   ```

   Expected: the folders in the table above.
2. Check the layering rule yourself. Each command should print **nothing**:

   ```bash
   grep -rln "from backend.api" backend/app backend/infrastructure backend/ml --include=*.py
   grep -rln "from backend.app" backend/infrastructure backend/ml --include=*.py
   ```

   PowerShell: `Select-String -Path backend\app\*,backend\infrastructure\*,backend\ml\* -Pattern "from backend.api" -Recurse`
   is *unverified here*; any text search tool works.
3. See who uses the worker side: `grep -rln "from backend.ml" backend/app --include=*.py`.
   Expected: `perception_client.py`, `pending_output.py`, `execute_job.py` (the application talks to
   the worker; the reverse never happens).
4. Count the lines of code per layer:

   ```bash
   uv run python -c "
   import pathlib
   for d in ['backend/api','backend/app','backend/infrastructure','backend/ml','frontend/src','desktop/src-tauri/src']:
       n = sum(len(p.read_text(encoding='utf-8').splitlines()) for p in pathlib.Path(d).rglob('*') if p.suffix in {'.py','.ts','.tsx','.rs'})
       print(d, n)"
   ```

   Expected: six lines, each a count (on 2026-10-12: `backend/api` 4959, `backend/app` 14517,
   `backend/infrastructure` 2196, `backend/ml` 2281, `frontend/src` 10126, `desktop/src-tauri/src`
   996, comments and tests included). The application layer is the biggest; that is where the rules live.

## 5. Change it

Rule of thumb before you add code: *what does it decide?* A rule or a decision belongs in
`backend/app/<topic>/`. A new URL belongs in `backend/api/routes/` and calls a use case. Anything about
files, SQLite, the index or images belongs in `backend/infrastructure/`. If your change makes a
lower layer import a higher one, stop: that is the sign it is in the wrong place. The tests that
protect the contracts between layers are in `tests/contracts/`:

```bash
uv run pytest tests/contracts -q
```

Expected: all pass.

## 6. Break it on purpose

In a scratch branch, add `from backend.api.errors import ApiError` at the top of
`backend/app/people/use_cases.py` and run `uv run ruff check .` and `uv run pytest tests/integration/test_person_use_cases.py -q`.
`ruff` complains only about the housekeeping (an unused import and unsorted imports, 2 errors) and the
31 tests still pass: **nothing mechanical forbids the import itself**. The layering is a convention
kept by review and by the habit above. That is exactly why your `grep` check in step 2 is worth running
after a big change. (Revert it with `git restore backend/app/people/use_cases.py`; this was run on
2026-10-12 and reverted.)

## 7. Exercises

1. A new rule: "a person's name may not be empty". Which layer holds the rule, and which layer shows
   the error to the user?
2. Which layer would a function `sha256_of_file(path)` live in?
3. Where would you look first to see how a source is imported?
4. What does `grep -rln "from backend.ml" backend/app` tell you about the dependency direction?

**Answers**

1. The rule is in the use case (`backend/app/people/`); the route (`backend/api/routes/people.py`)
   turns the failure into the one API error shape. (Today the route also constrains the name length with
   `StringConstraints(min_length=1, max_length=200)`.)
2. `backend/infrastructure/storage/` (it touches files).
3. `backend/api/routes/sources.py` (`import_source`) then `backend/app/sources/import_source.py`.
4. The application layer depends on the worker contract, never the reverse.

## 8. Related files

- Previous: [03 Authoritative and derived](03-authoritative-and-derived.md) · Next: [05 One request, end to end](05-one-request-end-to-end.md)
- [Layers and rules](../03-backend/architecture/01-layers-and-rules.md)
- [`docs/specs/IMPLEMENTATION_ARCHITECTURE.md`](../../../specs/IMPLEMENTATION_ARCHITECTURE.md)
