# M2: Identity, Occurrence and Evidence repositories

- **Date:** 2026-10-01
- **Milestone / tracker IDs:** M2 · TST-022; GitHub issue #32 (the third item)
- **Status:** done for Identity/Occurrence/Evidence; RuntimeCatalog/Settings remains in #32
- **Commits:** PR (branch `feat/identity-evidence-repositories`): `feat(identities): identity, occurrence and evidence repositories`

## What changed

- `backend/app/identities/repository.py`:
  - `IdentityRepository`: `add`, `get` (fresh), `lock` (a no-op write first, then the fresh row, as `ProcessingRunRepository.lock`),
    `transition` (the shared optimistic-locked `UPDATE`: expected revision *and* expected states in one statement; sets
    `activated_at` on `ACTIVE`, `forgotten_at` on `FORGOTTEN`, records `merged_into_identity_id`), `add_lineage`.
  - `OccurrenceRepository`: `add` (with its observations in order, `ordinal` 0, 1, ...), `get`, `observation_ids`, keyset
    pages by source and by identity (newest first, ties by id), a guarded `transition` (sets `activated_at` on `ACTIVE`).
  - `EvidenceRepository`: `append` (the evidence, the representations it cites with their roles, and its ranked candidates, one
    flush), `get`, `candidates` (rank order), `links`, a keyset `page_for_identity`, and `mark_superseded` (the explanatory
    marker, set once). There is no update that touches a payload.
- `tests/integration/test_identity_repositories.py` (19): nothing is committed on the caller's behalf; `lock` really holds
  SQLite's write lock and changes nothing; a transition needs the revision and state (stale and wrong-state callers change
  nothing; one winner under contention); a `MERGED` identity must name its target (the schema insists); a bare string is not a
  state list; observations keep their order; pages are newest first and neither skip nor repeat when a row disappears or
  arrives between two page requests, with ties broken by id; evidence is appended whole and marked superseded once.

## Why

PERSISTENCE_IMPLEMENTATION §26 ("lock/get/create and append the semantic links needed by their use cases") and the pattern of
the existing repositories.

## Decisions

- The Identity Manager's existing use cases keep working on the ORM objects; they were not rewritten onto these repositories
  (a refactor outside this task). The repositories are what the forget and occurrence-building use cases will use.
- Evidence immutability is this repository's rule (no payload update), not the database's; a trigger would be a schema change
  nobody asked for. `mark_superseded` is the only change to an existing evidence row, as the model says.
- No state machine was invented: transitions take the expected states from the caller.

## Verification

- `ruff format --check`, `ruff check`, `mypy`, `mypy --platform linux` clean; `HYPOTHESIS_PROFILE=ci pytest --cov -q`: 1033 passed, backend coverage 100%.
  Every guard was broken, shown to fail a test and restored byte-identical (19 mutations). Two did not fail a test, both
  equivalent: an `UPDATE` matching no row still takes SQLite's write lock (so the `lock` test was re-aimed at removing the
  statement, which it catches), and the explicit `ORDER BY rank` of the candidates equals the primary key's order `(evidence_id,
  rank)`; it is kept because the contract should not rest on an index choice.
- **Not verified:** the repositories under real use cases (not wired in yet).

## Open issues / follow-ups

- #32: RuntimeCatalog/Settings repositories.
- Moving the Identity Manager's use cases onto these repositories.
