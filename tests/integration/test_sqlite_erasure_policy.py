"""PER-08: deleted content does not linger in the SQLite file or its write-ahead log.

Decision 2026-10-01 (issue 31): `secure_delete = ON` zeroes deleted content in the database file;
`truncate_wal` removes it from the log. Neither is a guarantee of physical erasure.
"""

from pathlib import Path

from sqlalchemy import Engine, text

from backend.infrastructure.db.engine import create_sqlite_engine, truncate_wal

SECRET = b"FACE-VECTOR-SECRET-0123456789ab" * 8


def _wal(engine: Engine) -> Path:
    path = Path(str(engine.url.database))
    return path.with_name(path.name + "-wal")


def _database(engine: Engine) -> Path:
    return Path(str(engine.url.database))


def _store_and_erase(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE secret (id INTEGER PRIMARY KEY, body BLOB)"))
        connection.execute(text("INSERT INTO secret (body) VALUES (:body)"), {"body": SECRET})
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM secret"))


def test_erased_content_is_gone_from_the_database_file_and_the_log_after_truncation(
    sqlite_engine: Engine,
) -> None:
    _store_and_erase(sqlite_engine)
    assert SECRET in _wal(sqlite_engine).read_bytes()  # the insert's frame is still in the log

    assert truncate_wal(sqlite_engine) is True

    assert _wal(sqlite_engine).stat().st_size == 0
    assert SECRET not in _database(sqlite_engine).read_bytes()


def test_a_reader_holding_an_older_snapshot_blocks_truncation_until_it_ends(
    sqlite_engine: Engine,
) -> None:
    _store_and_erase(sqlite_engine)
    with sqlite_engine.connect() as reader:
        reader.exec_driver_sql("SELECT count(*) FROM secret").all()  # begins its snapshot
        with sqlite_engine.begin() as writer:
            writer.execute(text("INSERT INTO secret (body) VALUES (x'00')"))

        assert truncate_wal(sqlite_engine, busy_timeout_ms=0) is False
        assert _wal(sqlite_engine).stat().st_size > 0
        reader.rollback()

    assert truncate_wal(sqlite_engine) is True
    assert _wal(sqlite_engine).stat().st_size == 0


def test_truncate_wal_leaves_the_pooled_connection_as_it_found_it(sqlite_engine: Engine) -> None:
    with sqlite_engine.connect() as connection:
        before = connection.exec_driver_sql("PRAGMA busy_timeout").scalar()
        raw_before = connection.connection.dbapi_connection.isolation_level  # type: ignore[union-attr]
    assert truncate_wal(sqlite_engine, busy_timeout_ms=0)
    with sqlite_engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA busy_timeout").scalar() == before
        assert connection.connection.dbapi_connection.isolation_level == raw_before  # type: ignore[union-attr]


def test_truncate_wal_reports_failure_when_the_database_is_not_in_wal_mode(
    tmp_path: Path,
) -> None:
    engine = create_sqlite_engine(tmp_path / "memory.db")
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("CREATE TABLE t (id INTEGER)")
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            connection.exec_driver_sql("PRAGMA journal_mode = DELETE")
        assert truncate_wal(engine) is False
    finally:
        engine.dispose()
