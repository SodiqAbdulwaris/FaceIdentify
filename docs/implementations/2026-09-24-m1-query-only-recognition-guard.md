# M1 PR 6: query-only recognition guard

- **Date:** 2026-09-24
- **Milestone / tracker IDs:** M1 (TST-019)
- **Status:** done
- **Commits:** PR #9: `feat(identities): add query-only recognition guard`,
  `test(identities): add query-only recognition tests`, `docs: record m1 query-only recognition guard`

## What changed

- `backend/app/identities/use_cases.py`: `resolve_recognition_candidates(session,
  candidate_identity_ids)`. Given a list of identity ids (as if returned by an upstream ANN
  candidate search — no ANN/USearch wiring exists yet at M1), it resolves each one against
  authoritative SQLite state: following `merged_into_identity_id` through any merge chain,
  dropping a candidate that resolves to nothing or to a non-`ACTIVE` identity, preserving input
  order, and de-duplicating candidates that resolve to the same identity. It performs no writes
  at all — no `session.add`, no `update()`, nothing.
- `tests/integration/test_query_only_recognition.py`: 13 tests.

## Why

M1 plan step 7 (`TESTING_IMPLEMENTATION_TRACKER.md` TST-019; `Roadmap-Plan.md` §60/§61 Phase B).
`API and Contracts.md` §12.2 (face search) specifies the flow `... -> ANN candidate retrieval ->
authoritative SQLite revalidation -> ...` and that by default the endpoint "creates no Source,
Observation, Identity, Evidence, persistent memory." `IMPLEMENTATION_ARCHITECTURE.md` §32 rule 7
("never allow query-only recognition to silently become ingest") and
`TESTING_STRATEGY.md`'s SEARCH-01 state the same invariant. This PR implements the one piece of
that flow that is domain-level and testable without an ML pipeline: the authoritative-revalidation
step.

## Decisions

- **Scope is the revalidation step only, not the whole face-search endpoint.** Detection,
  embedding, and ANN retrieval are ML/index infrastructure that doesn't exist yet (M1's own goal
  is "verify identity and observation behaviour independently of actual ML inference"). The
  function takes already-retrieved candidate identity ids as input, matching where "authoritative
  SQLite revalidation" sits in the documented pipeline — after ANN retrieval, before ranking.
- **The guarantee is structural, not merely tested.** The function contains no `session.add`,
  `session.execute(update(...))`, or `session.flush()` of new state — it only calls `session.get`.
  There is no code path inside it that could create persistent memory, by construction, matching
  the "never...silently become ingest" rule directly rather than relying on a runtime check.
- **A merged candidate resolves through the chain to its current identity**, reusing the same
  `merged_into_identity_id` field `merge_identities` (PR #8) already writes — this is the reverse
  direction of the same data: forward for merge composition, backward for recognition revalidation.
- **`populate_existing=True` on every `session.get`.** Revalidation is the function's entire
  purpose; without it, a session that just merged, forgot, or deleted an identity moments earlier
  would answer from its own stale ORM cache instead of authoritative state. Caught directly by a
  test that merges an identity in the same session and then queries it, with no `expire_all()`
  call in between — the fix without this line was found first, then reverted mutation-test-style
  to confirm the test actually needs it.
- **A candidate that resolves to `PENDING`, `MERGED` (terminal, chain exhausted), `SPLIT`,
  `FORGOTTEN`, or `DELETED` is dropped, not returned as-is.** Only `ACTIVE` identities are valid
  recognition results — a `PENDING` identity has no confirmed observations, and the other states
  are all no-longer-current.

## Verification

- `HYPOTHESIS_PROFILE=ci uv run pytest --cov --cov-report=term-missing -q`: 236 passed (13 new,
  no regressions in the prior 223); `backend/` coverage 100%; strict mypy and ruff clean.
- Mutation checks (each reverted immediately afterwards, confirmed byte-identical to the original
  via `diff`), all caught:
  - dropping the `state != ACTIVE` filter → 4 tests fail;
  - dropping the de-duplication guard → 1 test fails;
  - removing the merge-chain walk (`while` loop) entirely → 2 tests fail;
  - dropping `populate_existing=True` from both `session.get` calls → 4 tests fail.

## Independent review

Not yet run at the time of writing this entry; see the PR for the review outcome and any
follow-up this entry doesn't yet reflect.

## Open issues / follow-ups

- Wiring `resolve_recognition_candidates` into an actual `POST /api/v1/search/face` endpoint,
  ANN retrieval, and the rest of §12.2's pipeline is out of scope until the ML/index
  infrastructure exists (post-M1).
- Hypothesis property tests over operation sequences (TST-020) is the last remaining M1 slice.
