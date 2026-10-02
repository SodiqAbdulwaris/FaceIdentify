# M3: planning and the decisions it rests on

Date: 2026-10-02. Documentation only; no code.

## What was done
- Surveyed M3 (tracker TST-033 to TST-044, Roadmap phases 3 to 9, Persistence sections 12 to 16, 23, 28, 30, the API contract, the ML spec) and wrote a 14-step plan, approved by the owner after review.
- Recorded four initial owner decisions as dated notes (more were added the same day: see the Resolution below): the reference models and what identifies a representation space (ML spec 18.1); the headless runtime installer (ML spec 18.1); the three recognition outcomes (Roadmap phase 6); and accepted `ABSTAIN` representations being `ACTIVE` without an identity (Persistence 6.2).
- Updated CONTEXT (M3 started) and the tracker status line.

## Consequences for the code (not built here)
- Migration `0005` relaxes the ACTIVE CHECK to `state != 'ACTIVE' OR ann_key IS NOT NULL`. `ACTIVE` without an `ann_key` stays rejected; tests must prove both halves (including `ACTIVE + identity NULL + ann_key NULL` rejected), the populated-library upgrade, and the downgrade guard.
- Candidate retrieval treats an identity-less candidate as evidence only. A run-local candidate of a PENDING identity must stay distinguishable from an ACTIVE identity's.

## Documents that disagree (resolved)
Persistence wins over the API contract for `previous_job_id` (not `retry_of_job_id`) and for the index returning `ann_key`; the Qdrant text in `processing-architecture-v1.md` is superseded by USearch; Run `COMPLETED` does not wait for index operations to be `APPLIED` (Persistence section 12).

## Resolution (owner, 2026-10-02, issues 71 and 57)
1. No `Occurrence` for `ABSTAIN` (Observation, representation, Evidence only). 2. A later `ResolveUnresolvedRepresentation` Identity Manager use case sets the identity, creates the Occurrence and records resolution Evidence, with no `ann_key` change; tracked separately. 3. Identity forget does not reach identity-less representations. 4. Persisted `ABSTAIN` covers the estimator's `AMBIGUOUS` and `ABSTAIN` and the policy `PRESERVE_UNRESOLVED`. 5. `weights_digest` is the SHA-256 of the exact weight bytes and one component of the space identity (ML spec 18.1). 6. Migration 0005 lands with the acceptance use case. 7. Manifest schema 1 is approved; an unknown schema version fails closed. 8. Installed runtime packages are machine-local, referenced by libraries, never substituted. Issue 57: the existing behaviour is the policy's fallback (the backend cannot truly delete), see Persistence 6.2. Not stated in the owner's list and settled from it: a different export or precision is a different weight artifact, hence a different digest, hence a different space (ML 18.1); the space's `contract_json` records the digest, and registering installed packages in the catalog as referenced artifacts is tracked in issue 80; the resolution use case is tracked in issue 79 and built when needed, not required by M3's tests.

## Open points found by the review (recommendations; resolved above, with the follow-ups in issues 79 and 80)
1. **Occurrence and Evidence for `ABSTAIN`.** `occurrences.identity_id` is non-null and one face makes one occurrence, so an abstained face cannot have one; `EvidenceKind` has no abstention kind. Recommendation: an abstention writes no Occurrence; its candidate evidence is kept in `evidence_candidates` (already allows a NULL identity), so no second schema change.
2. **Resolving an abstained representation later.** `assign_representation_to_identity` needs `PENDING` and allocates a new key; a new path must set the identity on an `ACTIVE` identity-less row, keep its `ann_key` and queue no `ADD`. Recommendation: a separate use case, built after M3.
3. **Identity-level forget.** It works through `identity_id`, so it cannot reach identity-less representations; they are erased through representation or Source erasure. Recommendation: state this in the forget spec.
4. **Two meanings of `ABSTAIN`.** The estimator outcome (ML spec) differs from the persisted outcome. Recommendation: the persisted `ABSTAIN` covers the estimator's AMBIGUOUS and ABSTAIN and the policy action `PRESERVE_UNRESOLVED`.
5. **"Weights digest" in the space identity.** A space has `semantic_key`, `component_version_id`, `dimension`, `contract_json`, `normalization`; the digest lives on `ModelExport.sha256`. Recommendation: the space's `contract_json` records the export digest, and a different export or precision is a different space unless proven equivalent.
6. **Where migration 0005 lands:** with the acceptance use case (step 11 of the plan), because that is the first writer of an identity-less `ACTIVE` row.

7. **Manifest schema version 1** (Architecture section 12.2) is the agent's design within the headless-installer scope, because the specs only say "declarative and versioned". Recommendation: confirm it, or amend it before the installer (plan step 4b) registers catalog rows from it.

8. **Where installed runtime packages live** (Architecture 12.2): the agent chose machine-local `<local state>/runtime/packages/<key>`, staged in `<local state>/installation/`, because the artifact layer refuses to store `RUNTIME_PACKAGE` bytes in the library and API and Contracts section 54 puts runtime artifacts in the runtime package layer. The layout doc says the library holds "every managed byte" and has a `models/` directory, which pulls the other way; the catalog tables also need an `artifacts` row per export and per installation (a REFERENCED artifact pointing at the local path would fit). Recommendation: confirm machine-local; register the catalog rows as REFERENCED artifacts when installed packages are registered.

## Changes migration 0005 will require (from the review)
`backend/app/memory/models.py` (the CHECK) and a new revision (recreate `representations`; downgrade guard first and a refusal while an identity-less `ACTIVE` row exists); `resolve_ann_candidates` (outer join, `RecognitionCandidate.identity_id` optional); `index_coordinator.py` (the four identity joins: `_active_keys`, `_active_entries`, `_apply_one` twice); `assign_representation_to_identity` docstrings; tests: `test_memory_models`, `test_memory_repositories`, `test_ann_candidate_revalidation`, `test_index_coordinator`, `fixtures/consistency.py`, the property test docstring, the head pins (`test_migrations`, `test_library_lifecycle`, `test_downgrade_guard`), and a new `test_migration_0005` (populated upgrade, both CHECK halves, rollback, offline `--sql`, refused downgrade).
