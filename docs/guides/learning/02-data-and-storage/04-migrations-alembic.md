# Data 04 Migrations with Alembic

## 1. What this is and why it exists

The schema changes over time. A **migration** is a small versioned script that moves a database from one schema
version to the next. **Alembic** runs them; the database remembers its version in a table called
`alembic_version`. In this project Alembic is the **only** way the production schema is created or changed
(`Base.metadata.create_all()` is never called outside a test comparing against it). This lesson shows how to read
the history, run it on a scratch library, and, step by step, how a new column would be added. It **describes** the
procedure; the guide's pull request deliberately commits no revision.

## 2. Where it lives

| Thing | Where |
|---|---|
| The revisions | `backend/alembic/versions/0001_initial_schema.py` to `0010_deleted_artifacts_and_source_deleted_evidence.py` |
| The environment | `backend/alembic/env.py` (reads `FACEIDENTIFY_LIBRARY_ROOT`; batch mode; foreign-key check) |
| The how-to | `backend/alembic/README` |
| The config and the post-write hooks | `alembic.ini` (`ruff format` and `ruff check --fix` run on every new revision) |
| The downgrade guard | `backend/infrastructure/db/downgrade_guard.py` |
| Migration tests | `tests/integration/test_migrations.py`, `test_migration_0002.py` to `test_migration_0010.py`, `test_downgrade_guard.py`, `test_schema_contract.py`, `tests/fixtures/migrations.py` |

The history (use `uv run alembic history`): `0001` initial schema (33 tables) · `0002` the `ERASING` representation state ·
`0003` `ann_key` unique per space, immutable snapshots · `0004` the `app_state` table · `0005` abstain provenance,
snapshot-replace trigger · `0006` the `RECOGNITION_ABSTAINED` evidence kind · `0007` the integer job priority rank
· `0008` the `PERSON_RENAMED` evidence kind · `0009` the unused `SPLIT` identity state removed · `0010` a deleted
artifact may have no location, the `SOURCE_PERMANENTLY_DELETED` evidence kind.

## 3. How it works

- Each revision has `upgrade()` and `downgrade()`. SQLite cannot change most constraints in place, so migrations
  use **batch mode** (`op.batch_alter_table`): create a new table with the new shape, copy the rows, drop the
  old, rename. With foreign keys on that is dangerous, so `env.py` follows SQLite's documented procedure:
  enforcement off outside the transaction, the revision, then `PRAGMA foreign_key_check` **before** that revision
  commits. A violation rolls the revision back. Each revision is its own transaction, so a failing revision
  leaves the database at the revision before it.
- Rules the tests enforce: a migration must work on a **populated** database; a refused migration leaves the
  database untouched; **`downgrade()` is refused on a populated library** unless
  `FACEIDENTIFY_ALLOW_DESTRUCTIVE_DOWNGRADE=1` (production only moves forward, with corrective revisions); every
  revision's `downgrade()` must start with `require_destructive_downgrade_allowed(op.get_bind())`; a library
  stamped with a revision newer than the program knows is refused (`DatabaseNewerThanApplicationError`).
- The application upgrades the library itself on every start (`open_library` migrates, then recovers). The command
  line is for development and review, and it **does not take the library lock**: never migrate a library a
  running backend holds.

## 4. Try it

**Works with no models. Verified 2026-10-12.** Use a scratch library folder (not one you care about).

1. Create a brand-new database at head. bash first, PowerShell below:

   ```bash
   export FACEIDENTIFY_LIBRARY_ROOT=~/faceidentify-play/alembic-lib
   mkdir -p "$FACEIDENTIFY_LIBRARY_ROOT"
   uv run alembic upgrade head
   ```

   ```powershell
   $env:FACEIDENTIFY_LIBRARY_ROOT = "$HOME\faceidentify-play\alembic-lib"     # (unverified here)
   New-Item -ItemType Directory -Force $env:FACEIDENTIFY_LIBRARY_ROOT | Out-Null
   uv run alembic upgrade head
   ```

   Expected: ten log lines `Running upgrade  -> 0001, initial schema` through
   `Running upgrade 0009 -> 0010, a deleted artifact may have no location; add the source-deleted Evidence kind`,
   and a new file `database/library.db` under that folder.
2. Where are we? `uv run alembic current` prints `0010 (head)`. `uv run alembic history` lists the chain from
   `<base> -> 0001` to `0009 -> 0010 (head)`.
3. Does the code match the migrations? `uv run alembic check`. Expected: `No new upgrade operations detected.`
4. Read what a revision does without running it: `uv run alembic upgrade head --sql | head -30`. Expected: SQL text
   starting `CREATE TABLE alembic_version (...)` then `-- Running upgrade  -> 0001` and the `CREATE TABLE` statements.
   It is for review only; it has no transaction or foreign-key handling, so never pipe it into a database.
5. **The downgrade guard.** On the empty library, `uv run alembic downgrade -1` works (`Running downgrade 0010 ->
   0009`; `alembic current` then says `0009`); `uv run alembic upgrade head` puts it back. On a **populated**
   library it is refused. Make a populated scratch library from a safe copy:

   ```bash
   mkdir -p ~/faceidentify-play/dg-lib/database
   cp ~/faceidentify-play/copy.db ~/faceidentify-play/dg-lib/database/library.db      # copy.db: a backup-API copy (lesson 02)
   FACEIDENTIFY_LIBRARY_ROOT=~/faceidentify-play/dg-lib uv run alembic downgrade -1
   ```

   Expected (observed): a traceback ending `DestructiveDowngradeRefused: refusing to downgrade a library that
   holds data (ann_key_sequences, artifacts, evidence, ... sources): a downgrade can destroy it and production
   recovery moves forward with a new revision. For development only, set
   FACEIDENTIFY_ALLOW_DESTRUCTIVE_DOWNGRADE=1.` `alembic current` still says `0010 (head)`: nothing changed.

## 5. Change it: add a column (describe it, do not commit it)

This is the real procedure. In the verified dry run for this guide the steps were followed with a throwaway
`nickname` column on `Person`, the generated file was inspected, and everything was discarded.

1. **Get the decision first.** A new column is a schema change. The rules (`.agents/rules/scope.md`) forbid
   inventing tables, models or contracts the specs do not define, and specs are not edited without the owner's
   approval. Record the decision, update `docs/specs/PERSISTENCE_IMPLEMENTATION.md` (with a dated `Decision` note),
   and have a plan or implementation entry for it.
2. **Edit the model**, e.g. in `backend/app/people/models.py`:
   `nickname: Mapped[str | None] = mapped_column(String)`.
3. **See the drift.** With `FACEIDENTIFY_LIBRARY_ROOT` pointing at a scratch library at head,
   `uv run alembic check` now fails: `New upgrade operations detected: [('add_column', None, 'people', Column('nickname', String(), table=<people>))]`.
   (Observed.) `uv run pytest tests/integration/test_migrations.py -q` also fails: models and migrations disagree.
4. **Generate the revision**:

   ```bash
   uv run alembic revision --autogenerate --rev-id 0011 -m "add person nickname"
   ```

   Expected: `backend/alembic/versions/0011_add_person_nickname.py` and the post-write hooks running `ruff format`
   and `ruff check --fix` on it. It contains `with op.batch_alter_table("people", schema=None) as batch_op:
   batch_op.add_column(sa.Column("nickname", sa.String(), nullable=True))` and a `downgrade()` that drops it.
5. **Read and finish it.** Autogenerate does not detect CHECK-constraint changes and does not know about data.
   You must: write a docstring saying why; start `downgrade()` with `require_destructive_downgrade_allowed(op.get_bind())`
   (copy the import from `0007_job_priority_rank.py`); backfill data if the column is `NOT NULL`; use a frozen table
   definition (`copy_from`, see `0002`) when you must recreate a table, so `upgrade --sql` keeps working.
6. **Tests.** Update the pins in `tests/integration/test_migrations.py` (lines near 162 and 181 name the head `0010`);
   add `tests/integration/test_migration_0011.py` following `test_migration_0007.py` (migrate a database to `0010`,
   fill it with the `build` factory, upgrade, assert the column exists and old rows survived, then the downgrade
   path). Run `test_migrations.py`, `test_downgrade_guard.py`, `test_schema_contract.py` and your new file. In the
   dry run, with the untouched generated file, four tests failed for exactly these reasons: the head pins
   (`test_the_revision_history_is_one_linear_chain_starting_at_0001`, `test_upgrade_stamps_the_head_revision_and_is_idempotent`)
   and the missing guard in `downgrade()` (`test_every_revision_starts_its_downgrade_with_the_guard_on_its_own_connection[0011]`,
   `test_a_populated_library_is_refused_at_every_revision_before_anything_changes[0011]`).
7. **Use the column**: the use case, the route's response model, `npm run generate:api`
   ([OpenAPI and the contract](../03-backend/api/03-openapi-and-contract.md)), tests, docs.
8. **Record it**: implementation entry, `CONTEXT.md`, and (if status moves) `PROJECT_STATUS.md`. The revision and
   its model change go in **one commit**.

## 6. Break it on purpose

Edit a model without writing a revision (step 3 above): `alembic check` fails with the exact missing operation, and
the migration tests fail. Or write a revision whose `downgrade()` forgets the guard: the guard tests fail for that
revision id. Both are the project telling you the schema and its history disagree.

## 7. Exercises

1. Which command shows the current revision of a library? Which lists all of them?
2. Why must `downgrade()` start with a guard?
3. Why can `alembic upgrade head --sql` not be piped into a database?
4. What does `alembic check` tell you?
5. A teammate wants a new `NOT NULL` column. What do they have to think about that autogenerate will not do?

**Answers**

1. `uv run alembic current`; `uv run alembic history`.
2. A downgrade can destroy data; the guard refuses on a populated library, and production only moves forward.
3. The offline SQL has no transaction, no `foreign_keys` handling and no foreign-key check; it is for review.
4. Whether the models and the migrations agree (it reports operations a new revision would need).
5. Existing rows: a backfill or a default, since the column cannot be `NULL` for rows that already exist.

## 8. Related files

- Previous: [03 Transactions](03-transactions-and-unit-of-work.md) · Next: [05 SQLAlchemy and repositories](05-sqlalchemy-and-repositories.md)
- [`backend/alembic/README`](../../../../backend/alembic/README), [`backend/alembic/env.py`](../../../../backend/alembic/env.py)
- [`docs/specs/PERSISTENCE_IMPLEMENTATION.md`](../../../specs/PERSISTENCE_IMPLEMENTATION.md) section 27
- [Add a route](../03-backend/api/02-add-a-route.md)
