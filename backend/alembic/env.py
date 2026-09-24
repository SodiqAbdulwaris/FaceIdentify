"""Alembic environment (PERSISTENCE_IMPLEMENTATION.md §27: "Use a normal Alembic environment at
`backend/alembic/`... The first revision is `0001_initial_schema`").

No Storage Manager / app-data path resolver exists yet (a later milestone), so the database path
for 'online' mode comes from the `FACEIDENTIFY_DATABASE_PATH` environment variable rather than a
fixed `alembic.ini` URL or an invented default location. 'offline' mode (`--sql`) and autogenerate
comparisons only need `target_metadata`, so they work without it.
"""

import os
from logging.config import fileConfig
from pathlib import Path

from alembic import context

from backend.app.models import Base
from backend.infrastructure.db.engine import create_sqlite_engine

config = context.config

# Programmatic callers (tests, application startup) set `attributes["configure_logger"] = False`:
# fileConfig would otherwise replace the host process's logging configuration.
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Emit SQL to stdout without a live database connection (`alembic upgrade head --sql`)."""
    context.configure(
        url="sqlite:///offline",
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    database_path = os.environ.get("FACEIDENTIFY_DATABASE_PATH")
    if not database_path:
        raise RuntimeError(
            "FACEIDENTIFY_DATABASE_PATH is not set. Alembic needs the library database's file "
            "path to run migrations online (see backend/alembic/env.py)."
        )
    connectable = create_sqlite_engine(Path(database_path))
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
                connection=connection, target_metadata=target_metadata, render_as_batch=True
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        # Releases the file (and its WAL) so a caller can copy or delete the database afterwards.
        connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
