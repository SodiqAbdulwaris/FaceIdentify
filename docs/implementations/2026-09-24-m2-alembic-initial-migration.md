# M2: Alembic and the initial migration

- **Date:** 2026-09-24
- **Milestone / tracker IDs:** M2 (TST-032, in progress; first M2 slice)
- **Status:** done (the slice); TST-032's populated-schema criterion is deferred to the second revision
- **Commits:** PR #11: `build(backend): add alembic and the initial schema migration`,
  `test(persistence): run persistence tests on the migrated schema`,
  `docs: record m2 alembic initial migration`

## What changed

- `pyproject.toml`/`uv.lock`: `alembic` added as a **runtime** dependency (migrations run at
  application startup, so it is not a dev-only tool). Also a ruff per-file ignore for `E501` in
  `backend/alembic/versions/*.py` (see Decisions).
- `alembic.ini` + `backend/alembic/` (`env.py`, `script.py.mako`, `README`, `versions/`), as
  PERSISTENCE_IMPLEMENTATION.md §27 specifies. The `alembic.ini` has no `sqlalchemy.url`; its
  post-write hooks run `ruff format` and `ruff check --fix` on every generated revision.
- `backend/alembic/versions/0001_initial_schema.py`: the baseline revision, generated with
  `alembic revision --autogenerate --rev-id 0001` against an empty database and then reviewed: all
  33 tables, every index (including the partial ones) and every CHECK/FK/UNIQUE constraint, and
  nothing from §27's exclusion list. Reversible (`downgrade` drops everything).
- `backend/alembic/env.py`: target metadata is the full model registry (`backend.app.models`); the
  online engine is the production `create_sqlite_engine` (same pragmas and transaction hooks as the
  application); `render_as_batch=True`; the engine is disposed
  afterwards; logging is only reconfigured for CLI use (`attributes["configure_logger"]`).
- `tests/fixtures/persistence.py`: `sqlite_engine` no longer calls `Base.metadata.create_all`. A
  session-scoped `migrated_template_db` runs `alembic upgrade head` once and every test copies that
  file, so **every persistence test now runs on the real migration's schema**.
- `tests/integration/test_migrations.py`: 11 tests (TST-032).
- `tests/property/test_identity_lifecycle_invariants.py` uses the same migrated template.
- Two existing test functions updated for legitimate reasons (below).

## Why

M2's first slice, and the one `.agents/CONTEXT.md` had deferred since M0: Roadmap-Plan §37 (LOCKED)
"Alembic is the sole production schema evolution mechanism... Fresh databases also run Alembic",
and PERSISTENCE_IMPLEMENTATION.md §27 ("Never use `create_all()` in production startup", first
revision `0001_initial_schema`, test a fresh database, verify foreign keys and partial indexes after
upgrade).

## Decisions

- **The database path comes from `FACEIDENTIFY_DATABASE_PATH`, and `env.py` refuses to run without
  it.** No Storage Manager or app-data resolver exists yet, and no spec defines a default library
  location. Inventing one would be scope creep into the Storage Manager (TST-025), so the path is an
  explicit input. Offline (`--sql`) mode and autogenerate comparisons need only the metadata.
  Recorded as CONTEXT open question 17.
- **Session-scoped template copy, not a migration per test.** Running Alembic for each of ~250 tests
  would be slow; migrating once and `shutil.copyfile`-ing the (small) file keeps each test isolated
  and fast (full suite still ~18 s).
- **Constraint order differs between Alembic and `create_all`; the comparison test is
  order-insensitive.** Both list the same named constraints in different orders inside the same
  `CREATE TABLE` (23 of 33 tables). A naive DDL string comparison fails on that alone. The
  equivalence test therefore compares columns in order and constraints as a set, and indexes
  (single statements) exactly, including their `WHERE` clauses.
- **One existing test was order-sensitive, and was fixed rather than the migration reordered.**
  `test_spec_defined_value_sets_reject_unknown_literals[artifact-storage_mode]` expected
  `ck_artifacts_storage_mode` to be the CHECK SQLite reports, but `ck_artifacts_location` also
  rejects an unknown `storage_mode`, and SQLite reports whichever is listed first. It now accepts
  either for that one case (with a comment); the exact existence of both constraints is proven by
  the schema-equivalence test, so no coverage is lost. Hand-reordering 23 tables in a generated
  migration to match `create_all`'s incidental order would have been the wrong trade.
- **`test_each_test_gets_a_fresh_database` now expects `alembic_version`** in the table set. The
  schema legitimately gained Alembic's own table.
- **Failure atomicity comes from the engine's `BEGIN` hooks, not from Alembic.** Alembic assumes
  SQLite DDL is non-transactional, so a revision failing midway could leave a half-applied schema
  with no version stamp — the opposite of "existing databases are never destroyed because migration
  failed". Checked empirically: a deliberately failing migration rolls back completely, because
  `create_sqlite_engine`'s explicit-`BEGIN` hooks make DDL transactional. Alembic's
  `transactional_ddl=True` was tried and found to add nothing observable (see Verification), so it
  is **not** set: a flag claiming a safeguard it doesn't provide would mislead. The failure-safety
  test pins the behavior instead, and fails if the hooks regress.
- **`render_as_batch=True` from the first revision.** SQLite can only change most constraints by
  recreating the table (§27), so every future ALTER-shaped revision needs batch mode. It has no
  effect on `0001` (create-only), so **it is exercised by no test yet** (CONTEXT open question 18).
- **`E501` ignored for generated revisions only.** The migration bakes in the literal SQL that
  `enum_check` builds at runtime from the `StrEnum`s (some CHECK literals exceed the 100-column limit); wrapping
  generated SQL by hand makes diffs harder to read, not easier.
- **Revision id `0001`** (`--rev-id 0001`), giving the file `0001_initial_schema.py`, matching the
  spec's name, rather than Alembic's random hex default.
- **TST-032 is `IN_PROGRESS`, not `PASSING`.** With one revision there is no earlier schema to
  upgrade from, so "supported populated schemas migrate correctly" cannot be tested yet.

## Verification

- `HYPOTHESIS_PROFILE=ci uv run pytest --cov --cov-report=term-missing -q`: 249 passed (11 new; the
  238 existing tests all pass on the migrated schema; 3 test items (2 test functions) needed the legitimate updates above);
  `backend/` coverage 100% including `env.py` and every line of the migration; strict mypy and ruff
  clean.
- Manual, outside the suite: `alembic upgrade head` on a fresh file, `alembic check` ("No new upgrade
  operations detected"), `alembic downgrade base`, and the failing-migration probe (existing table and
  row survive, no partial schema, no `alembic_version`).
- Mutation checks (each reverted, restore confirmed byte-identical via `diff`):
  - dropping a CHECK constraint from the migration → caught (`test_migrated_tables_match_create_all`
    and the existing `test_artifact_hash_must_be_32_bytes`);
  - dropping a partial unique index → caught by 7 tests;
  - changing a foreign key's `ON DELETE` rule → caught (equivalence test, the existing
    `test_foreign_keys_and_delete_rules_match_the_spec`);
  - leaving a table behind in `downgrade` → caught by the round-trip test;
  - dropping the missing-path guard in `env.py` → caught; ignoring the `configure_logger` flag →
    caught; removing the engine `dispose()` → caught (leaked connections error across the suite);
  - removing the engine's `BEGIN` hooks → caught by
    `test_a_failed_migration_leaves_an_existing_database_exactly_as_it_was`, **with or without**
    `transactional_ddl=True` set; and with the hooks intact that test passes without the flag. So
    the hooks are load-bearing and the flag is redundant (hence removed).
  - `alembic check` alone does **not** notice a missing CHECK constraint (a known Alembic
    limitation); that is why the equivalence test compares DDL rather than relying on it.

## Independent review

Not yet run at the time of writing this entry; see the PR for the outcome.

## Open issues / follow-ups

- CONTEXT open questions 17 (where the database path really comes from) and 18 (batch-mode
  migrations unproven until revision 0002).
- The rest of M2: TST-021 to TST-031.
