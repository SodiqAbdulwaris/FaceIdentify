# M3: candidate retrieval over the global and run-local pools (step 8; TST-040)

- **Date:** 2026-10-03
- **Milestone / tracker IDs:** M3 · TST-040 (in progress); CONTEXT open question 21 (the run-local index)
- **Status:** partial: retrieval and the run-local index are done. Opening the global index for a run (the wiring) and the recognition service are step 9 and 10.
- **Commits:** PR (this branch): `feat(recognition): retrieve candidates from global and run-local pools`

## What changed
- `backend/infrastructure/indexing/run_local_index.py`: `RunLocalIndex`, the pending representations of one run in one space, in memory (USearch, never written to disk). Its labels are a per-index counter mapped to the representation id, **never an `ann_key`** (decision 2026-10-02, open question 21: a pending representation is not ANN-eligible and an `ann_key` belongs to a transaction that might roll back). Adding an id twice keeps the first (a vector never changes). A vector of another dimension or a non-finite one is refused.
- `backend/app/recognition/retrieval.py`: `retrieve(session, *, representation_space_id, dimension, vector, k, global_index, processing_run_id, run_local=None) -> Retrieval`.
  - **Compatibility is enforced, not trusted:** the global index and the run-local index must be this space's, this dimension and the cosine metric (the only one a space may have; a `similarity` is derived from the distance, so it is never a mislabelled one), or `IncompatibleSpaceError` is raised before anything is searched; the query's dimension is checked by the index.
  - **SQLite revalidates what either pool returns.** Global: `resolve_ann_candidates` (same space, `ACTIVE`, `ACTIVE` identity). Run-local: still a `PENDING` representation **of this run in this space**. A stale or foreign candidate is dropped, and the number dropped is reported (`Retrieval.dropped`), so a short shortlist can be told from a complete one.
  - The result is the nearest `k` over both pools, nearest first, ties broken by pool (global first) and then representation id (deterministic). A candidate carries its pool, representation id, identity id (a global candidate's `ACTIVE` identity; a run-local one's `PENDING` identity that this run gave it, so the same new person is recognised again within the run, or None when it carries no settled identity), distance and a derived cosine `similarity`.
  - `rebuild_run_local_index(session, ...)` rebuilds the pool from the run's `PENDING` representations after a crash; a vector that cannot be decoded is an error, never skipped.
- `backend/app/memory/index_coordinator.py`: `_vector` is now the public `decode_vector` (the retrieval module needed the same canonical decoding; no behaviour change).

## Decisions (the agent's)
- The caller supplies the opened global index (via `open_or_rebuild`, which is the coordinator's/writer's concern). A missing or unusable index is the caller's failure to report, never an empty answer here: an empty library has an empty index, and "no candidates" must not be confused with "could not look" (ML spec: no automatic new identity without functioning retrieval).
- `k` is the caller's: each pool is asked for `k` and the merge is cut to `k`; nothing is over-fetched to hide stale candidates, `dropped` makes them visible instead.
- Retrieval excludes nothing by source or observation (a face of the same image can be returned for another face of it); that is the recognition policy's rule (step 9), and each candidate carries its representation id so the caller can apply it.
- Global candidates still need an identity: `resolve_ann_candidates` joins `identities`. The outer join for accepted `ABSTAIN` representations (no identity) is part of migration 0005's change list (step 11).

## Verification
- `tests/unit/test_run_local_index.py` (8) and `tests/integration/test_recognition_retrieval.py` (28, real SQLite and real USearch indexes), 100% coverage of both modules: identity and similarity on global candidates, nearest-first merge over both pools cut to `k`, the tie order whatever order candidates were indexed, stale candidates counted in both pools at once, a global-only query, an empty library; dropped and counted: not-active global states (`ERASING`, `SUPERSEDED`, `DELETED`), an identity that is gone, another space's representation under the same key, a run-local candidate that is no longer pending (four states), pending representations of another run or space; chunked revalidation; refused: a global or run-local index of another space or dimension, a query of the wrong dimension, `k` below one; the rebuilt pool holds exactly this run's pending representations of this space, answers retrieval like the original, and refuses an undecodable vector.
- Review fix: the review found that the dropped count was never tested with stale candidates in both pools at once (turning `+=` into `=` survived), now tested; and that the metric of the two pools was never compared, now both must be cosine.
- Mutation pass: 29 mutations (every guard and filter, the sort, the distances, the pools, the counts); first run had five survivors: two guards no test could observe were deleted (`retrieve`'s own `k` check, which the global index repeats, and the run-local rebuild's ordering, which affects no result; the run-local index keeps its own `k` check and its test), the tie-break order got a test in both directions (pool, then id, whatever the indexing order), and one mutant was equivalent. None survive.
- Full gate: see the PR.

## Open issues / follow-ups
- Step 9: `RecognitionService`, `RecognitionAssessment`, `IdentityReasoner` (MATCH_EXISTING / CREATE_NEW / ABSTAIN) consume a `Retrieval`.
- The wiring that opens the global index (and holds the run-local index) for a run is step 10's orchestration.
