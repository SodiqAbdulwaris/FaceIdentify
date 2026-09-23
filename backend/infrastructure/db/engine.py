"""SQLite engine and session factory (PERSISTENCE_IMPLEMENTATION.md §24, §25)."""

from pathlib import Path

from sqlalchemy import Connection, Engine, MetaData, create_engine, event
from sqlalchemy.engine.interfaces import DBAPIConnection
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import ConnectionPoolEntry

# Executed on every new DBAPI connection. foreign_keys is per-connection in SQLite,
# so it must never be set only once at startup.
SQLITE_PRAGMAS = (
    "PRAGMA foreign_keys = ON",
    "PRAGMA journal_mode = WAL",
    "PRAGMA synchronous = NORMAL",
    "PRAGMA busy_timeout = 5000",
    "PRAGMA temp_store = MEMORY",
)


# Deterministic constraint names. SQLite can only change constraints by recreating the table
# (Alembic batch mode), which needs every constraint to have a stable name.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """The single declarative registry for persistence models (PERSISTENCE_IMPLEMENTATION.md §1).

    Feature packages define their models against this Base; `backend.app.models` imports them
    all so the metadata is complete.
    """

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def _apply_pragmas(
    dbapi_connection: DBAPIConnection, _connection_record: ConnectionPoolEntry
) -> None:
    cursor = dbapi_connection.cursor()
    try:
        for pragma in SQLITE_PRAGMAS:
            cursor.execute(pragma)
    finally:
        cursor.close()


def _disable_driver_transactions(
    dbapi_connection: DBAPIConnection, _connection_record: ConnectionPoolEntry
) -> None:
    # sqlite3 defers BEGIN until the first DML statement, so a leading SAVEPOINT would open the
    # outer transaction itself and its RELEASE would commit. Autocommit mode lets SQLAlchemy
    # emit BEGIN explicitly instead (SQLAlchemy's documented pysqlite recipe).
    dbapi_connection.isolation_level = None


def _begin(connection: Connection) -> None:
    connection.exec_driver_sql("BEGIN")


def create_sqlite_engine(database_path: Path) -> Engine:
    engine = create_engine(
        f"sqlite+pysqlite:///{database_path}",
        pool_pre_ping=False,
        connect_args={"check_same_thread": False, "timeout": 5},
    )
    event.listen(engine, "connect", _disable_driver_transactions)
    event.listen(engine, "connect", _apply_pragmas)
    event.listen(engine, "begin", _begin)
    return engine


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, autoflush=False, expire_on_commit=False)
