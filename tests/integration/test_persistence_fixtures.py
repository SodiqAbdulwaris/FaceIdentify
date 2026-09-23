"""M0 smoke tests: real SQLite, filesystem and USearch fixtures."""

from collections.abc import Callable
from pathlib import Path

import numpy as np
import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from usearch.index import Index

from tests.fixtures.persistence import AppDirs

# Test-local tables only: these are not production models.
PARENT_CHILD_DDL = (
    "CREATE TABLE parent (id INTEGER PRIMARY KEY)",
    "CREATE TABLE child (id INTEGER PRIMARY KEY, parent_id INTEGER NOT NULL REFERENCES parent(id))",
)


def test_production_pragmas_are_applied(sqlite_engine: Engine) -> None:
    with sqlite_engine.connect() as conn:

        def pragma(name: str) -> object:
            return conn.exec_driver_sql(f"PRAGMA {name}").scalar()

        assert pragma("foreign_keys") == 1
        assert pragma("journal_mode") == "wal"
        assert pragma("synchronous") == 1  # NORMAL
        assert pragma("busy_timeout") == 5000
        assert pragma("temp_store") == 2  # MEMORY


def test_foreign_keys_are_enforced(db_session: Session) -> None:
    for ddl in PARENT_CHILD_DDL:
        db_session.execute(text(ddl))
    with pytest.raises(IntegrityError, match="FOREIGN KEY"):
        db_session.execute(text("INSERT INTO child (id, parent_id) VALUES (1, 999)"))


def test_foreign_keys_are_enforced_on_every_pooled_connection(sqlite_engine: Engine) -> None:
    # foreign_keys is per-connection in SQLite; a fresh connection must get it too.
    connections = [sqlite_engine.connect() for _ in range(3)]
    try:
        assert [c.exec_driver_sql("PRAGMA foreign_keys").scalar() for c in connections] == [1, 1, 1]
    finally:
        for connection in connections:
            connection.close()


def test_session_commits_are_durable_across_connections(
    sqlite_engine: Engine, db_session: Session
) -> None:
    db_session.execute(text(PARENT_CHILD_DDL[0]))
    db_session.execute(text("INSERT INTO parent (id) VALUES (42)"))
    db_session.commit()
    with sqlite_engine.connect() as other:
        assert other.exec_driver_sql("SELECT id FROM parent").scalars().all() == [42]


@pytest.mark.parametrize("run", ["first", "second"])
def test_each_test_gets_a_fresh_database(run: str, sqlite_engine: Engine, tmp_path: Path) -> None:
    with sqlite_engine.begin() as conn:
        tables = conn.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'").all()
        assert tables == []  # nothing left behind by the other parametrised run
        conn.exec_driver_sql(PARENT_CHILD_DDL[0])
    assert sqlite_engine.url.database is not None
    database = Path(sqlite_engine.url.database)
    assert database.is_relative_to(tmp_path)


def test_app_dirs_are_isolated_under_tmp_path(app_dirs: AppDirs, tmp_path: Path) -> None:
    for path in (app_dirs.library_root, app_dirs.local_state, app_dirs.indexes, app_dirs.temp):
        assert path.is_dir()
        assert path.is_relative_to(tmp_path)
    (app_dirs.temp / "scratch.bin").write_bytes(b"\x00\x01")
    assert list(app_dirs.temp.iterdir()) == [app_dirs.temp / "scratch.bin"]


def test_usearch_index_add_search_save_restore_remove(
    make_usearch_index: Callable[..., Index], app_dirs: AppDirs, np_rng: np.random.Generator
) -> None:
    ndim = 16
    vectors = np_rng.standard_normal((10, ndim)).astype(np.float32)
    keys = np.arange(1, 11, dtype=np.uint64)  # ann_key is a positive integer (Persistence §1)

    index = make_usearch_index(ndim)
    index.add(keys, vectors)
    assert len(index) == 10
    assert index.search(vectors[3], 1).keys[0] == 4

    index.save()
    saved = app_dirs.indexes / "index.usearch"
    assert saved.is_file()

    restored = Index.restore(str(saved))
    assert restored is not None
    try:
        assert len(restored) == 10
        assert restored.search(vectors[3], 1).keys[0] == 4
    finally:
        restored.reset()

    index.remove(4)
    assert 4 not in index
    assert index.search(vectors[3], 1).keys[0] != 4
