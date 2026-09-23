# M1 PR 1: core persistence models

- **Date:** 2026-09-23
- **Milestone / tracker IDs:** M1 (groundwork for TST-011–020); partial persistence for M2 (TST-021/022)
- **Status:** done
- **Commits:** PR #4: `feat(db): add utc datetime type and constraint naming`, `feat(sources): add artifact and source models`, `feat(processing): add run provenance and job models`, `feat(runtime): add component catalog and settings models`, `test(db): add constraint tests for core models`, `docs: record m1 core persistence models`

## What changed

- `backend/infrastructure/db/types.py`: `UTCDateTime` stores naive UTC and returns aware UTC,
  rejecting naive input. `uuid_pk()` gives a uuid4 `Uuid` key (CHAR(32)). `enum_check()` makes a
  CHECK whose literals match a `StrEnum`.
- `backend/infrastructure/db/engine.py`: `Base.metadata` gets a constraint **naming convention**,
  so every constraint is named, as Alembic batch mode on SQLite requires.
- Models for 20 of the `0001_initial_schema` tables (PERSISTENCE_IMPLEMENTATION.md §4, §6.1,
  §12–§19), one module per feature:
  - `sources/models.py`: `Artifact`, `Source`
  - `processing/models.py`: `ProcessingConfigurationSnapshot`, `ProcessingRun`,
    `ExecutionSegment`, `ProcessingCheckpoint`
  - `jobs/models.py`: `Job`
  - `runtime/models.py`: `Component`, `ComponentVersion`, `ModelExport`, `InstalledModelExport`,
    `RuntimeVariant`, `RuntimeVariantRepresentationSpace`, `RecognitionCalibrationProfile`,
    `RuntimePackage`, `RuntimePackageInstallation`
  - `memory/models.py`: `RepresentationSpace`
  - `settings/models.py`: the three singleton settings tables
- `backend/app/models.py`: a registry that imports every feature's models so `Base.metadata` is
  complete. The `sqlite_engine` fixture now builds the full schema from it.
- `tests/integration/test_core_models.py`: constraint tests that match the exact failing
  constraint by name, or the exact UNIQUE column set, via `check()`/`unique()`.
- `tests/integration/test_schema_contract.py`: reads the built schema back from SQLite (PRAGMA)
  and asserts every foreign key's target and ON DELETE rule (§20), the §21 indexes, the partial
  indexes and the `DEFAULT 1` columns.
- `tests/integration/test_persistence_fixtures.py`: the fresh-database test now asserts that
  exactly the schema's tables exist (previously: no tables).

## Why

This is the first slice of the M1 plan in `.agents/CONTEXT.md`. Identity and observation models
(PR 2) need these tables through their foreign keys.

## Decisions

- CHECK constraints are added **only where a spec defines the complete value set**. Unconstrained
  strings, recorded as open questions: `Component.kind` (API §73 lists its kinds as "Examples:"),
  every runtime-catalog `state`, `ModelExport.format`/`precision`,
  `RuntimeVariant.provider`/`device_kind` and `RepresentationSpace.normalization`.
  `RuntimeVariant.variant_key` is **not** unique, because §18 marks uniqueness explicitly
  elsewhere and not here.
- Nullability follows the spec's explicit "nullable" markers. For example,
  `execution_segments.runtime_details_json` is NOT NULL (§14 does not mark it nullable).
- `revision` and `jobs.attempt_number` have a database `DEFAULT 1` (§2), as well as the ORM default.
- Integrity checks the spec implies but does not state, listed here because nothing is meant to
  be invented silently: `revision >= 1`, `attempt_number >= 1`, segment/checkpoint
  `ordinal >= 0`, and `display_name` not blank after `trim()`.
- Not built yet: the package-membership association tables (§18 adds them only "when the trusted
  manifest needs relational querying"), and typed settings columns (no settings are defined yet).
- Circular foreign keys (`sources` ↔ `processing_runs`, `processing_runs` ↔
  `processing_checkpoints`) use `use_alter=True`. On SQLite they are still emitted inline
  (verified with `PRAGMA foreign_key_list`).
- `UNIQUE(processing_runs.configuration_snapshot_id)` enforces the spec's "one snapshot per run".
- The `(state, created_at DESC, id DESC)` and `(run, ordinal DESC)` indexes are ascending. SQLite
  scans an index in either direction, so they serve the same queries. The unique
  `(run, ordinal)` index serves both the uniqueness rule and the checkpoint lookup.
- Transient run states (for the partial index): `PENDING`, `RUNNING`, `PAUSING`, `PAUSED`,
  `CANCELLING`, `FINALIZING`, `INTERRUPTED`. This is inferred from the recovery table in §28; the
  spec does not list them.
- Timestamps have no defaults: they are "produced by the application" (§2), and use cases supply
  a clock.

## Verification

- The full schema builds with warnings treated as errors (20 tables, 3 partial indexes).
- `uv run pytest`: 60 passed (41 new across the two test files). `uv run mypy` (strict): no
  issues in 46 files. ruff clean.
- Coverage for the new model and type modules is 100%.
- Mutation checks (each reverted afterwards). Each broken constraint made its own test fail:
  - dropping the one-running-segment filter failed `test_only_one_running_segment_per_run`;
  - disabling the artifact location CHECK failed both location tests;
  - accepting naive datetimes failed `test_utc_datetime_rejects_naive_values`;
  - dropping `ondelete="RESTRICT"` on `sources.original_artifact_id` failed the FK contract test.
    A behavioural delete test cannot catch this, because SQLite's default `NO ACTION` also
    blocks the delete;
  - dropping the `jobs.lease_expires_at` index failed the index test;
  - dropping the `server_default` on `sources.revision` failed the DEFAULT test. An earlier
    insert-based test did **not** catch it (Core inserts apply the Python default), so it was
    replaced.
- Independent review (subagent, disposable worktree): changes requested, 10 findings, all
  addressed. See the PR #4 comments.

## Open issues / follow-ups

- The value sets for the unconstrained columns above need a spec decision before release (M2
  migration at the latest).
- The transient-run-state list is an inference; confirm when recovery is implemented.
- **Job claim order:** `priority` is a string, so `ORDER BY priority` sorts alphabetically
  (HIGH, INTERACTIVE, LOW, MAINTENANCE, NORMAL), and the `(state, priority, created_at)` index
  cannot serve the intended INTERACTIVE-first claim order (§15). Decide when the scheduler is
  built (M6): an integer rank column, or one equality probe per priority.
- The review noted that the PR's feat commits carry no tests of their own (tests arrive in a
  separate commit) and that one commit subject names two changes. The published history is not
  rewritten; later PRs put tests in the same commit as the behaviour.
