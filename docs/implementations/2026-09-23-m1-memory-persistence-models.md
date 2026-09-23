# M1 PR 2: memory, identity and people models, plus shared factories

- **Date:** 2026-09-23
- **Milestone / tracker IDs:** M1 (groundwork for TST-011–020); completes TST-008 (factories)
- **Status:** done
- **Commits:** PR #5: `feat(db): add memory, identity and people models`, `docs(specs): record memory model decisions`, `docs: record m1 memory persistence models`

## What changed

- Models for the remaining 13 `0001_initial_schema` tables (PERSISTENCE_IMPLEMENTATION.md §5–§11,
  §17), so all 33 now exist:
  - `memory/models.py`: `AnnKeySequence`, `Observation`, `Representation`, `Occurrence`,
    `OccurrenceObservation`, `IndexOperation`
  - `identities/models.py`: `Identity`, `IdentityLineage`, `Evidence`, `EvidenceRepresentation`,
    `EvidenceCandidate`
  - `people/models.py`: `Person`, `IdentityPersonAssociation`
- **Shared factories** `tests/factories/models.py` (`ModelFactory`, exposed as the `build`
  fixture). They build a deterministic, valid row for every domain model, creating parents on
  demand. Per-run state lets repeated observations share one execution segment and number
  themselves. This completes TST-008 and pulls planned PR 3 into this PR.
- `tests/fixtures/constraints.py`: `check()`/`unique()`/`rejected()`, shared by the model tests.
  `rejected()` now runs the failing write in a **SAVEPOINT**. The earlier full rollback discarded
  rows the test had created before the check, so a later check could fail for the wrong reason.
  This happened in the lineage test.
- `tests/integration/test_memory_models.py`: constraint tests and spec value-set tests for the
  new models. `test_schema_contract.py` now covers all 33 tables (foreign keys and delete rules,
  §21 indexes, partial indexes, DDL defaults).
- `docs/specs/PERSISTENCE_IMPLEMENTATION.md`: five `Decision 2026-09-23` notes (below).

## Why

Slice 2 of the M1 plan. The Identity Manager use cases (next PR) operate on these tables.

## Decisions (owner, 2026-09-23, recorded in the spec)

| Question | Decision |
|---|---|
| `representations.vector`: table says non-null, text says NULL once ERASED | Nullable **only** for ERASED, enforced by the `ck_representations_erasure` CHECK |
| Columns the spec doesn't mark nullable but whose value only exists after an event | Nullable (listed below); everything else NOT NULL |
| `evidence_candidates.decision` values; observation landmark/quality JSON | `decision` is unconstrained; two nullable JSON columns, `landmarks_json` and `quality_json` |
| Occurrence "lifecycle timestamps" | `created_at` + `activated_at` |

Event-only nullable columns: `index_operations.last_attempt_at`, `applied_at`, `failure_code`,
`failure_detail`; `identities.activated_at`, `forgotten_at`; `representations.activated_at`,
`erased_at`; `occurrences.activated_at`; `identity_person_associations.ended_at`;
`evidence.superseded_at`.

My own choices, listed because nothing is meant to be invented silently:
- **Implied integrity checks:**
  - observation `frame_index`/`timestamp_ms` are both NULL or both set, and non-negative;
  - `sequence_in_run >= 0`;
  - `length(vector) = 4 * vector_dimension` (float32);
  - an ACTIVE representation has an identity and an `ann_key` (spec §6.2; the identity's *own*
    state is a cross-row rule for the use case);
  - `state = MERGED` if and only if `merged_into_identity_id` is set, and not merged into itself;
  - a lineage edge has two distinct identities;
  - an association's `ended_at` is set exactly when it is not ACTIVE;
  - an APPLIED index operation has `applied_at`;
  - `rank`, `ordinal`, `attempt_count >= 0`;
  - a Person's `display_name` is not blank.
- **Delete rules the spec leaves implicit:**
  - `evidence_representations.representation_id`, `evidence_candidates.*_id`,
    `occurrence_observations.observation_id` and `index_operations.representation_id` are
    RESTRICT (history);
  - the owning side (`evidence_id`, `occurrence_id`) is CASCADE (§20);
  - the `evidence_candidates.details_json` payload is NOT NULL.
- The partial index `uq_identity_person_active` uses the exact name from §9. The
  one-pending-operation index is `uq_index_operations_one_pending_per_representation_operation`.
- No §21 index is listed for `identities` or `identity_lineage`, so none was added.

## Verification

- `HYPOTHESIS_PROFILE=ci uv run pytest --cov`: 130 passed; `backend/` coverage 100%; strict mypy
  and ruff are clean. The full schema (33 tables) builds with warnings treated as errors.
- Mutation checks (each reverted afterwards), all caught:
  - disabling the erasure CHECK;
  - neutering `uq_identity_person_active` (caught by the behaviour test *and* the schema contract);
  - changing representation→observation from CASCADE to RESTRICT (behaviour test and FK contract);
  - disabling `ck_identities_merged_target`.
- SAVEPOINT support with the pysqlite driver was verified by the lineage test, which creates
  rows, has one write rejected, and then uses the earlier rows.

## Open issues / follow-ups

- `evidence_candidates.decision` value set and the observation JSON contents: open questions in
  CONTEXT.
- Cross-row rules (active representation → active identity; active occurrence → active
  identity; source's current run is completed) are enforced by the use cases from PR 3 on.
