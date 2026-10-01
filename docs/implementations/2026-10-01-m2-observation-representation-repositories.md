# M2: Observation and Representation repositories

- **Date:** 2026-10-01
- **Milestone / tracker IDs:** M2 · TST-022; GitHub issue #32 (the second item)
- **Status:** done for Observation/Representation; Identity/Occurrence/Evidence and RuntimeCatalog/Settings remain in #32
- **Commits:** PR (branch `feat/observation-representation-repositories`): `feat(memory): observation and representation repositories`

## What changed

- `backend/app/memory/repository.py`:
  - `ObservationRepository`: `add_batch` (one flush), `get` (the row as the database has it now), `page_for_run`
    (keyset on `sequence_in_run`), `transition` (one guarded `UPDATE`; records `superseded_by_run_id`).
  - `RepresentationRepository`: `add_batch`, `get`, `page_for_run` (a projection, `RepresentationSummary`, without the
    vector; keyset on `(created_at, id)`; optional state filter), `by_ann_keys` (per space, any state, 500 keys per
    statement), `transition` (guarded; sets `activated_at` when it becomes `ACTIVE`; **refuses `ERASING` and `ERASED` on
    either side**, because erasure is `RepresentationEraser`), `allocate_ann_key`.
- `allocate_ann_key` moved into the repository (§26 lists it there); `identities/use_cases.allocate_ann_key` is now a
  one-line delegate, so its callers and tests are unchanged.
- `tests/integration/test_memory_repositories.py` (21): nothing is committed on the caller's behalf; pages do not shift
  or repeat when a row is added between two page requests; a page is a projection; ties are broken by id; a key lookup is
  per space and sees every state; guarded transitions and one winner under contention (`rendezvous_before_write`);
  erasure refused as a plain state change; `active_eligible` still enforced by the schema; keys are allocated one at a time
  per space, a rolled-back allocation is handed out again, four concurrent allocations never collide.

## Why

PERSISTENCE_IMPLEMENTATION §26 ("batch add, explicit pages/streams, candidate lookup by ann keys, ann-key allocation,
lifecycle transition") and the pattern of the existing repositories.

## Decisions

- Allocation stays at ANN-eligibility time and run-local indexes keep their own labels (open question 21, finalised by the
  owner on 2026-10-01).
- `candidates by ann keys` is `by_ann_keys`, a plain lookup of facts. `resolve_ann_candidates`
  (`identities/use_cases.py`, which also checks the identity) is left where it is: moving it is a refactor outside this task.
- A `page_for_run` read inside one transaction sees one snapshot (SQLite WAL), so the no-shift guarantee holds between page
  requests, which is how the API pages; the tests use one session per page for that reason.
- No new state machine was invented: `transition` takes the expected states from the caller, as `JobRepository.transition`
  does.

## Verification

- `ruff format --check`, `ruff check`, `mypy`, `mypy --platform linux`, `HYPOTHESIS_PROFILE=ci pytest --cov -q`: 1011 tests passed, backend coverage 100%. Every new guard was broken, shown to fail a test and restored byte-identical (14 mutations; one survivor,
  the key chunking, was made observable by counting bound parameters). The racy tests ran 5 times.
- **Not verified:** the repositories under the real use cases (they are not wired in yet).

## Open issues / follow-ups

- #32: Identity/Occurrence/Evidence and RuntimeCatalog/Settings repositories.
- `resolve_ann_candidates` could be rebuilt on `by_ann_keys`; not done here.
