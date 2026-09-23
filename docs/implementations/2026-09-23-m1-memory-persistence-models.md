# M1 PR 2: memory, identity and people models, plus shared factories

- **Date:** 2026-09-23
- **Milestone / tracker IDs:** M1 (groundwork for TST-011–020); completes TST-008 (factories)
- **Status:** done
- **Commits:** PR #5: `feat(db): add memory, identity and people models`, `docs(specs): record memory model decisions`, `docs: record m1 memory persistence models`, then the review fixes `fix(db): make savepoints safe on the sqlite driver`, `feat(db): add bounded to-one relationships`, `fix(db): relax the merged-identity check to the spec` (which also closes the review's test gaps), `docs: record memory model review outcomes`

## What changed

- Models for the remaining 13 `0001_initial_schema` tables (PERSISTENCE_IMPLEMENTATION.md §5–§11,
  §17), so all 33 now exist:
  - `memory/models.py`: `AnnKeySequence`, `Observation`, `Representation`, `Occurrence`,
    `OccurrenceObservation`, `IndexOperation`
  - `identities/models.py`: `Identity`, `IdentityLineage`, `Evidence`, `EvidenceRepresentation`,
    `EvidenceCandidate`
  - `people/models.py`: `Person`, `IdentityPersonAssociation`
- **Shared factories** `tests/factories/models.py` (`ModelFactory`, exposed as the `build`
  fixture). They build deterministic, valid rows for the domain models tests need (link
  and catalog rows are built inline), creating parents on demand. Per-run state lets repeated
  observations share one execution segment and number themselves. This completes TST-008 and pulls planned PR 3 into this PR.
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
  - a MERGED identity must set `merged_into_identity_id`, and not to itself. The first
    version also forbade the pointer on other states; the review showed §7 doesn't say
    that, so it was relaxed;
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

- `HYPOTHESIS_PROFILE=ci uv run pytest --cov`: 138 passed after the review fixes (130 before);
  `backend/` coverage 100%; strict mypy and ruff are clean. The full schema (33 tables) builds with warnings treated as errors.
- Mutation checks (each reverted afterwards), all caught:
  - disabling the erasure CHECK;
  - neutering `uq_identity_person_active` (caught by the behaviour test *and* the schema contract);
  - changing representation→observation from CASCADE to RESTRICT (behaviour test and FK contract);
  - disabling `ck_identities_merged_target`.
- SAVEPOINTs: the lineage test (create rows, reject one write, reuse the earlier rows) passed
  first time, but only because earlier writes had already opened the transaction. The review
  found the leading-SAVEPOINT case, where RELEASE committed. That is now fixed in the engine and
  covered by `test_engine_transactions.py` (see the Review table).

## Review (subagent, disposable worktree): 11 findings, all addressed

| # | Finding | Resolution |
|---|---|---|
| 1 | §22 to-one relationships missing (also from PR #4) | Added for Representation, Observation, Occurrence, ProcessingRun, ExecutionSegment and IdentityPersonAssociation; no collections. A contract test pins the exact set |
| 2 | Testing guide still said "factories not yet created" | Rewritten: `build` factory and `rejected()` usage |
| 3 | "Factory for every domain model" overstated | Wording fixed; `lineage` and `index_operation` builders added |
| 4 | Large feat commit mixes refactor | Acknowledged. The body explains the FK cycle; history is not rewritten |
| 5 | Savepoint semantics: pysqlite's deferred BEGIN made a leading SAVEPOINT's RELEASE **commit** | **Production fix** in `create_sqlite_engine` (SQLAlchemy's pysqlite recipe: driver autocommit + explicit `BEGIN`). `test_engine_transactions.py` failed before the fix (`assert 1 == 0`). The `ended_reason` test now mutates inside the savepoint |
| 6 | `_parent` treated explicit None as missing | An explicit None is kept |
| 7 | Cached segment could be stale after a savepoint rollback | Reused only if still persistent |
| 8 | MERGED-pointer CHECK stricter than §7 | Relaxed to "MERGED requires a target" |
| 9 | Several constraints untested | Tests for revisions, sequence/rank/ordinal/attempt_count, role, lineage kind, index operation value sets, timestamp-only IMAGE range, membership PK and CASCADE, and evidence link/candidate CASCADE |
| 10 | The association value-set case broke two rules | Now supplies `ended_at` |
| 11 | Decision notes lacked a source | "(Owner decision, M1 PR #5.)" added to each |

Mutation checks on the fixes: removing the explicit `BEGIN` hook fails
`test_released_savepoint_is_undone_by_outer_rollback`; dropping a relationship fails the
relationship contract. Removing only the driver-autocommit half of the recipe fails no test:
it is kept as the documented recipe's safeguard against the driver's own transaction
handling, and is **not independently tested**.

## Open issues / follow-ups

- `evidence_candidates.decision` value set and the observation JSON contents: open questions in
  CONTEXT.
- Cross-row rules (active representation → active identity; active occurrence → active
  identity; source's current run is completed) are enforced by the use cases from PR 3 on.
