"""A downgrade must not silently destroy a populated library (M2: TST-032; persistence section 27,
decision 2026-10-01, CONTEXT open question 19, issue 35).

Proved here: a library with no user or domain data downgrades freely, internal bookkeeping and
re-creatable metadata do not count as data, a library with data is refused at every revision
*before* anything changes, only the exact override lets it through, an unknown table counts as
data, and a revision that forgets the guard fails the build.
"""

import ast
import io
import sqlite3
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy.orm import Session

from backend.app.memory.repository import RepresentationRepository
from backend.app.models import Base
from backend.app.runtime.models import (
    InstalledModelExport,
    ModelExport,
    RecognitionCalibrationProfile,
    RuntimePackage,
    RuntimePackageInstallation,
    RuntimeVariant,
    RuntimeVariantRepresentationSpace,
)
from backend.app.settings.app_state import AppStateRepository
from backend.app.settings.repository import SettingsRepository
from backend.infrastructure.db.downgrade_guard import (
    ALLOW_DESTRUCTIVE_DOWNGRADE_ENV,
    INTERNAL_TABLES,
    DestructiveDowngradeRefused,
)
from backend.infrastructure.db.engine import create_sqlite_engine
from tests.factories.models import ModelFactory
from tests.fixtures.deterministic import FrozenClock, SeededUUIDs
from tests.fixtures.migrations import downgrade, dump, migrate, version
from tests.fixtures.persistence import alembic_config

VERSIONS = Path(__file__).parents[2] / "backend" / "alembic" / "versions"
REVISION_FILES = sorted(VERSIONS.glob("*.py"))  # every revision, including future ones
REVISIONS = [file.stem.split("_")[0] for file in REVISION_FILES]


def insert_identity(path: Path) -> None:
    """A row of user/domain data that every schema from `0001` can hold."""
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO identities (id, state, revision, created_at, updated_at)"
            " VALUES (X'00000000000000000000000000000001', 'ACTIVE', 1,"
            " '2026-01-01 00:00:00.000000', '2026-01-01 00:00:00.000000')"
        )


# --- a library without data -----------------------------------------------------------------------


def test_a_library_without_data_downgrades_all_the_way_without_the_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "library.db"
    migrate(monkeypatch, path, "head")

    downgrade(monkeypatch, path, "base", allow_destructive=False)

    assert sqlite_tables(path) <= {"alembic_version"}  # everything was dropped


def sqlite_tables(path: Path) -> set[str]:
    with sqlite3.connect(path) as connection:
        return {
            name
            for (name,) in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }


# --- a library with data --------------------------------------------------------------------------


@pytest.mark.parametrize("revision", REVISIONS)
def test_a_populated_library_is_refused_at_every_revision_before_anything_changes(
    revision: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "library.db"
    migrate(monkeypatch, path, revision)
    insert_identity(path)
    before = dump(path)
    previous = REVISIONS[REVISIONS.index(revision) - 1] if revision != REVISIONS[0] else "base"

    with pytest.raises(DestructiveDowngradeRefused, match=r"holds data \(identities\)"):
        downgrade(monkeypatch, path, previous, allow_destructive=False)

    assert version(path) == revision  # the revision was not undone
    assert dump(path) == before  # and no row, table or constraint changed


def test_the_refusal_names_the_override_and_says_it_is_for_development(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "library.db"
    migrate(monkeypatch, path, "0004")
    insert_identity(path)

    with pytest.raises(DestructiveDowngradeRefused) as refused:
        downgrade(monkeypatch, path, "0003", allow_destructive=False)

    assert ALLOW_DESTRUCTIVE_DOWNGRADE_ENV in str(refused.value)
    assert "development" in str(refused.value)
    assert "forward" in str(refused.value)  # recovery moves forward, it does not roll back


@pytest.mark.parametrize("value", ["", "0", "true", "yes", "11", " 1"])
def test_only_the_exact_override_lets_a_populated_library_through(
    value: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "library.db"
    migrate(monkeypatch, path, "0004")
    insert_identity(path)
    monkeypatch.setenv(ALLOW_DESTRUCTIVE_DOWNGRADE_ENV, value)

    with pytest.raises(DestructiveDowngradeRefused):
        downgrade_with_current_environment(monkeypatch, path, "0003")

    assert version(path) == "0004"


def downgrade_with_current_environment(
    monkeypatch: pytest.MonkeyPatch, path: Path, revision: str
) -> None:
    """The helper would overwrite the variable under test, so call Alembic directly."""
    from alembic import command

    from tests.fixtures.migrations import DATABASE_PATH_ENV
    from tests.fixtures.persistence import alembic_config

    monkeypatch.setenv(DATABASE_PATH_ENV, str(path))
    command.downgrade(alembic_config(), revision)


def test_the_override_set_to_one_lets_it_through_and_the_rows_survive_a_safe_step(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "library.db"
    migrate(monkeypatch, path, "0004")
    insert_identity(path)
    monkeypatch.setenv(ALLOW_DESTRUCTIVE_DOWNGRADE_ENV, "1")

    downgrade_with_current_environment(monkeypatch, path, "0003")

    assert version(path) == "0003"
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT count(*) FROM identities").fetchone() == (1,)


def test_a_table_the_guard_does_not_know_counts_as_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "library.db"
    migrate(monkeypatch, path, "head")
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE mystery (id INTEGER)")
        connection.execute("INSERT INTO mystery VALUES (1)")

    with pytest.raises(DestructiveDowngradeRefused, match=r"holds data \(mystery\)"):
        downgrade(monkeypatch, path, "0003", allow_destructive=False)


# --- no revision can forget the guard ------------------------------------------------------


@pytest.mark.parametrize("revision_file", REVISION_FILES, ids=lambda p: p.stem[:4])
def test_every_revision_starts_its_downgrade_with_the_guard_on_its_own_connection(
    revision_file: Path,
) -> None:
    module = ast.parse(revision_file.read_text(encoding="utf-8"))
    (downgrade_function,) = [
        node
        for node in module.body
        if isinstance(node, ast.FunctionDef) and node.name == "downgrade"
    ]
    statements = [
        statement
        for statement in downgrade_function.body
        if not (isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant))
    ]  # the docstring is not a statement that runs

    first = statements[0]
    assert isinstance(first, ast.Expr)
    assert ast.unparse(first.value) == "require_destructive_downgrade_allowed(op.get_bind())"


# --- the list of internal tables ------------------------------------------------------------------


def test_the_internal_tables_all_exist_and_the_ones_a_library_starts_with_are_all_seeded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    """A table named by mistake would only make the guard stricter, silently; and a table the
    guard does not count must be one a freshly initialised library really holds rows in. So seed
    every one, downgrade to the bottom without the override, and fail if the seeding and the list
    ever differ."""
    path = tmp_path / "library.db"
    migrate(monkeypatch, path, "head")
    engine = create_sqlite_engine(path)
    try:
        with Session(engine) as session:
            build = ModelFactory(session, clock, new_id)
            seed_every_internal_table(build, clock)
            session.commit()
    finally:
        engine.dispose()
    with sqlite3.connect(path) as connection:
        seeded = {
            name
            for name in INTERNAL_TABLES
            if connection.execute(f'SELECT 1 FROM "{name}" LIMIT 1').fetchone() is not None
        }
    assert seeded == INTERNAL_TABLES
    assert INTERNAL_TABLES - {"alembic_version"} <= set(Base.metadata.tables)

    downgrade(monkeypatch, path, "base", allow_destructive=False)  # none of it counts as data


def seed_every_internal_table(build: ModelFactory, clock: FrozenClock) -> None:
    version_row = build.component_version()
    space = build.representation_space()
    export = build.add(
        ModelExport(
            id=build.new_id(), component_version_id=version_row.id, format="ONNX",
            precision="FP16", artifact_id=build.artifact().id, sha256=bytes(32),
            input_contract_json={}, created_at=clock(),
        )
    )  # fmt: skip
    build.add(
        InstalledModelExport(
            id=build.new_id(), model_export_id=export.id, artifact_id=build.artifact().id,
            state="INSTALLED",
        )
    )  # fmt: skip
    variant = build.add(
        RuntimeVariant(
            id=build.new_id(), model_export_id=export.id, provider="CPU", device_kind="CPU",
            variant_key="cpu", requirements_json={}, state="AVAILABLE",
        )
    )  # fmt: skip
    build.add(
        RuntimeVariantRepresentationSpace(
            runtime_variant_id=variant.id, representation_space_id=space.id,
            validation_json={}, state="VALIDATED",
        )
    )  # fmt: skip
    build.add(
        RecognitionCalibrationProfile(
            id=build.new_id(), representation_space_id=space.id, version="v1", state="ACTIVE",
            parameters_json={}, schema_version=1, created_at=clock(),
        )
    )  # fmt: skip
    package = build.add(
        RuntimePackage(
            id=build.new_id(), key="core", manifest_schema_version=1, manifest_json={},
            state="TRUSTED", created_at=clock(),
        )
    )  # fmt: skip
    build.add(
        RuntimePackageInstallation(
            id=build.new_id(), runtime_package_id=package.id, artifact_id=build.artifact().id,
            state="INSTALLED",
        )
    )  # fmt: skip
    SettingsRepository(build.session).bootstrap(now=clock())
    AppStateRepository(build.session).set("wal_truncation_owed", "token", now=clock())


def test_a_setting_column_added_later_forces_a_review_of_the_guard() -> None:
    """The settings tables are internal because they hold only defaults today (id, revision,
    updated_at). Once a group has a value column it holds user choices, and a row no longer proves
    the library is empty: whoever adds one must revisit the guard, and this test says so."""
    managed = {"id", "revision", "updated_at"}
    for table in ("processing_settings", "storage_settings", "runtime_settings"):
        assert {column.name for column in Base.metadata.tables[table].columns} == managed, (
            f"{table} now has a setting column: decide whether the downgrade guard still treats"
            " its rows as internal (backend/infrastructure/db/downgrade_guard.py)"
        )


# --- an offline run -------------------------------------------------------------------------------


def test_an_offline_downgrade_prints_its_script_and_is_not_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(ALLOW_DESTRUCTIVE_DOWNGRADE_ENV, raising=False)
    config = alembic_config()
    config.output_buffer = io.StringIO()

    command.downgrade(config, "0004:0003", sql=True)

    assert "DROP TABLE app_state" in config.output_buffer.getvalue()


def test_only_an_artifact_no_catalog_row_uses_counts_as_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    """Installed models and packages keep their bytes as artifacts (so a fresh library has such
    rows); a source original or any other artifact is the user's."""
    path = tmp_path / "library.db"
    migrate(monkeypatch, path, "head")
    engine = create_sqlite_engine(path)
    try:
        with Session(engine) as session:
            build = ModelFactory(session, clock, new_id)
            seed_every_internal_table(build, clock)  # the artifacts it creates are the catalog's
            session.commit()
            build.artifact()  # one that nothing in the catalog references
            session.commit()
    finally:
        engine.dispose()

    with pytest.raises(DestructiveDowngradeRefused, match=r"holds data \(artifacts\)"):
        downgrade(monkeypatch, path, "0003", allow_destructive=False)


def test_the_key_allocator_is_data_because_a_key_must_never_be_handed_out_twice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    path = tmp_path / "library.db"
    migrate(monkeypatch, path, "head")
    engine = create_sqlite_engine(path)
    try:
        with Session(engine) as session:
            space = ModelFactory(session, clock, new_id).representation_space()
            RepresentationRepository(session).allocate_ann_key(space.id)
            session.commit()
    finally:
        engine.dispose()

    with pytest.raises(DestructiveDowngradeRefused, match=r"holds data \(ann_key_sequences\)"):
        downgrade(monkeypatch, path, "0003", allow_destructive=False)


def test_a_table_name_with_a_quote_does_not_break_the_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "library.db"
    migrate(monkeypatch, path, "head")
    with sqlite3.connect(path) as connection:
        connection.execute('CREATE TABLE "odd""name" (id INTEGER)')
        connection.execute('INSERT INTO "odd""name" VALUES (1)')

    with pytest.raises(DestructiveDowngradeRefused, match="odd"):
        downgrade(monkeypatch, path, "0003", allow_destructive=False)
