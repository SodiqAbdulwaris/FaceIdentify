"""Alembic environment (PERSISTENCE_IMPLEMENTATION.md §27: "Use a normal Alembic environment at
`backend/alembic/`... The first revision is `0001_initial_schema`").

The database path for 'online' mode derives from the library root (CONTEXT open question 17): the
application passes the one resolved path as `config.attributes["database_path"]`; the command line
uses `FACEIDENTIFY_LIBRARY_ROOT` (`<root>/database/library.db`). `FACEIDENTIFY_DATABASE_PATH`, a
bare file path, is the old way and is deprecated: it still works so existing scripts and tests do,
but nothing in the application reads it. There is deliberately no default location. 'offline' mode
(`--sql`) and autogenerate comparisons only need `target_metadata`, so they work without any of it.
"""

import os
from collections.abc import Collection, Mapping
from logging.config import fileConfig
from pathlib import Path
from typing import Any

from alembic import context
from alembic.runtime.migration import MigrationContext, MigrationInfo
from sqlalchemy import Connection

from backend.app.models import Base
from backend.infrastructure.db.engine import create_sqlite_engine
from backend.infrastructure.storage.layout import database_path_for
from backend.infrastructure.storage.library_root import LIBRARY_ROOT_ENV, validate_library_root

config = context.config

# Programmatic callers (tests, application startup) set `attributes["configure_logger"] = False`:
# fileConfig would otherwise replace the host process's logging configuration.
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Emit SQL to stdout without a live database connection (`alembic upgrade head --sql`).

    The script is for review: it does not contain the online procedure's `PRAGMA foreign_keys = OFF`
    or `foreign_key_check`, so replaying it by hand against a populated database with enforcement on
    fails where a table is recreated. Use `alembic upgrade`.
    """
    context.configure(
        url="sqlite:///offline",
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _disable_foreign_keys(connection: Connection) -> None:
    """`PRAGMA foreign_keys` is a no-op inside a transaction, so it is issued on the driver's own
    connection (the sqlite3 module is in autocommit mode, see `create_sqlite_engine`) while no
    transaction is open."""
    connection.connection.driver_connection.execute(  # type: ignore[union-attr]
        "PRAGMA foreign_keys = OFF"
    )


def _require_no_foreign_key_violations(
    ctx: MigrationContext, step: MigrationInfo, heads: Collection[Any], run_args: Mapping[str, Any]
) -> None:
    """The last step of SQLite's table-recreation procedure: with enforcement off, a revision
    could leave a row pointing at nothing. Alembic calls this (`on_version_apply`) inside the
    revision's own transaction, after its statements and the version stamp and before the commit
    (SQLite has no transactional DDL for Alembic, so each revision is its own transaction), so a
    violation rolls that revision back."""
    assert ctx.connection is not None
    violations = ctx.connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
    if violations:
        table, rowid, parent, _ = violations[0]
        tables = sorted({row[0] for row in violations})
        raise RuntimeError(
            f"{len(violations)} foreign key violation(s) in {tables}"
            f" (first: a row of {table} with rowid {rowid} points at a missing row of {parent}); "
            "the database may have been inconsistent before this migration"
        )


def _database_path() -> Path:
    """The library database to migrate: an explicit path, else the library root's, else the
    deprecated bare path. Nothing is guessed."""
    explicit = config.attributes.get("database_path")
    if explicit:
        return Path(explicit)  # the caller resolved and validated it; nothing is created
    root = os.environ.get(LIBRARY_ROOT_ENV)
    if root and root.strip():
        path = database_path_for(validate_library_root(Path(root)))  # as the application does
        path.parent.mkdir(parents=True, exist_ok=True)  # at most the root and `database`: validated
        return path
    legacy = os.environ.get("FACEIDENTIFY_DATABASE_PATH")  # deprecated
    if legacy and legacy.strip():
        return Path(legacy)
    raise RuntimeError(
        f"no library to migrate: set {LIBRARY_ROOT_ENV} (or pass the database path to Alembic as "
        "config.attributes['database_path']); see backend/alembic/env.py."
    )


def run_migrations_online() -> None:
    connectable = create_sqlite_engine(_database_path())
    try:
        with connectable.connect() as connection:
            # render_as_batch: SQLite can only change most constraints by recreating the table
            # (PERSISTENCE_IMPLEMENTATION.md §27 rule 8); batch mode is required for every future
            # ALTER-shaped revision, so it is on from the first revision onward, not added later.
            # A failed revision must leave an existing database exactly as it was. That atomicity
            # comes from create_sqlite_engine's explicit BEGIN hooks (Python's sqlite3 module would
            # not open a transaction for DDL on its own; Alembic's `transactional_ddl` flag does
            # not change that), and test_migrations.py pins it.
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                render_as_batch=True,
                on_version_apply=_require_no_foreign_key_violations,
            )
            # Recreating a table that other tables reference (every batch revision does it) drops
            # it, and with enforcement on that fails as soon as a child row exists. SQLite's own
            # procedure: enforcement off outside the transaction, the revision, then a foreign key
            # check before that revision commits (`on_version_apply`). A failure at any point, the
            # check included, rolls back the revision that was running; earlier ones stay applied.
            # This connection is private to the migration and is closed afterwards, so enforcement
            # needs no turning back on.
            _disable_foreign_keys(connection)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        # Releases the file (and its WAL) so a caller can copy or delete the database afterwards.
        connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
