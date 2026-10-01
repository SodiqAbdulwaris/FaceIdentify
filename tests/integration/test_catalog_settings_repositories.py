"""RuntimeCatalog and Settings repositories against real SQLite (M2: TST-022; persistence §18, §19,
§26).

Proved here: nothing is committed on the caller's behalf; settings are bootstrapped once whatever
races; a setting group changes only at the revision the caller read (one winner under contention)
and never by a name that is not a setting; catalog rows are added whole and read in a stable order,
and only installation records change state, from the state the caller expects.
"""

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from backend.app.runtime.models import (
    Component,
    ComponentVersion,
    InstalledModelExport,
    ModelExport,
    RecognitionCalibrationProfile,
    RuntimePackage,
    RuntimePackageInstallation,
    RuntimeVariant,
    RuntimeVariantRepresentationSpace,
)
from backend.app.runtime.repository import RuntimeCatalogRepository
from backend.app.settings.models import ProcessingSettings, RuntimeSettings, StorageSettings
from backend.app.settings.repository import SettingsGroup, SettingsRepository
from backend.infrastructure.db.engine import create_session_factory
from tests.factories.models import ModelFactory
from tests.fixtures.concurrency import rendezvous_before_write


@pytest.fixture
def factory(sqlite_engine: Engine) -> sessionmaker[Session]:
    return create_session_factory(sqlite_engine)


# --- settings -----------------------------------------------------------------------------------


def test_bootstrap_creates_every_group_at_revision_one_but_does_not_commit(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    now = build.clock()

    with factory() as session:
        repo = SettingsRepository(session)
        assert repo.get(SettingsGroup.PROCESSING) is None  # nothing before bootstrap
        assert repo.bootstrap(now=now) == list(SettingsGroup)
        for group in SettingsGroup:
            row = repo.get(group)
            assert row is not None
            assert (row.id, row.revision, row.updated_at) == (1, 1, now)
        with factory() as other:  # not visible to another connection until the caller commits
            assert other.scalar(select(ProcessingSettings.id)) is None
        session.rollback()
    with factory() as session:
        assert SettingsRepository(session).get(SettingsGroup.STORAGE) is None


def test_bootstrap_creates_only_what_is_missing_and_a_repeat_changes_nothing(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    later = build.clock() + timedelta(hours=1)
    with factory() as session:
        SettingsRepository(session).bootstrap(now=build.clock())
        session.commit()
    with factory() as session:  # one row lost
        session.execute(delete(StorageSettings))
        session.commit()

    with factory() as session:
        repo = SettingsRepository(session)
        assert repo.bootstrap(now=later) == [SettingsGroup.STORAGE]
        assert repo.bootstrap(now=later) == []
        session.commit()
    with factory() as session:
        repo = SettingsRepository(session)
        kept, recreated = repo.get(SettingsGroup.RUNTIME), repo.get(SettingsGroup.STORAGE)
        assert kept is not None
        assert recreated is not None
        assert kept.updated_at == build.clock()  # the existing row was not touched
        assert recreated.updated_at == later


def test_two_racing_bootstraps_create_each_group_exactly_once(
    factory: sessionmaker[Session], sqlite_engine: Engine, build: ModelFactory
) -> None:
    now = build.clock()

    def attempt(_: int) -> list[SettingsGroup]:
        with factory() as session:
            created = SettingsRepository(session).bootstrap(now=now)
            session.commit()
            return created

    with (
        rendezvous_before_write(sqlite_engine, "INSERT INTO processing_settings", parties=2),
        ThreadPoolExecutor(max_workers=2) as pool,
    ):
        outcomes = list(pool.map(attempt, range(2)))

    assert sorted(group for created in outcomes for group in created) == sorted(SettingsGroup)
    with factory() as session:
        counts = [
            len(session.scalars(select(model.id)).all())
            for model in (ProcessingSettings, StorageSettings, RuntimeSettings)
        ]
        assert counts == [1, 1, 1]


def test_an_update_applies_at_the_expected_revision_only(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    now = build.clock()
    later = now + timedelta(minutes=5)
    with factory() as session:
        SettingsRepository(session).bootstrap(now=now)
        session.commit()

    with factory() as session:
        repo = SettingsRepository(session)
        assert repo.update(SettingsGroup.RUNTIME, expected_revision=2, now=later) is False
        assert repo.update(SettingsGroup.RUNTIME, expected_revision=1, now=later)
        session.commit()
    with factory() as session:
        repo = SettingsRepository(session)
        runtime, processing = repo.get(SettingsGroup.RUNTIME), repo.get(SettingsGroup.PROCESSING)
        assert runtime is not None
        assert processing is not None
        assert (runtime.revision, runtime.updated_at) == (2, later)
        assert (processing.revision, processing.updated_at) == (1, now)  # another group: untouched


def test_updating_a_group_that_was_never_bootstrapped_changes_nothing(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    with factory() as session:
        assert not SettingsRepository(session).update(
            SettingsGroup.STORAGE, expected_revision=1, now=build.clock()
        )


def test_a_name_that_is_not_a_setting_is_refused_not_dropped(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    with factory() as session:
        SettingsRepository(session).bootstrap(now=build.clock())
        session.commit()

    for name in ("typo", "revision", "id", "updated_at"):  # the managed columns are not settings
        with factory() as session, pytest.raises(ValueError, match=f"no setting named {name}"):
            SettingsRepository(session).update(
                SettingsGroup.PROCESSING, expected_revision=1, now=build.clock(), **{name: 1}
            )
    with factory() as session:
        row = SettingsRepository(session).get(SettingsGroup.PROCESSING)
        assert row is not None
        assert row.revision == 1


def test_only_one_of_two_concurrent_updates_at_the_same_revision_wins(
    factory: sessionmaker[Session], sqlite_engine: Engine, build: ModelFactory
) -> None:
    now = build.clock()
    with factory() as session:
        SettingsRepository(session).bootstrap(now=now)
        session.commit()

    def attempt(_: int) -> bool:
        with factory() as session:
            done = SettingsRepository(session).update(
                SettingsGroup.STORAGE, expected_revision=1, now=now
            )
            session.commit()
            return done

    with (
        rendezvous_before_write(sqlite_engine, "UPDATE storage_settings", parties=2),
        ThreadPoolExecutor(max_workers=2) as pool,
    ):
        outcomes = list(pool.map(attempt, range(2)))

    assert sorted(outcomes) == [False, True]
    with factory() as session:
        assert session.scalar(select(StorageSettings.revision)) == 2


# --- catalog ------------------------------------------------------------------------------------


def new_export(build: ModelFactory, version_id: uuid.UUID, **kw: Any) -> ModelExport:
    fields: dict[str, Any] = dict(
        id=build.new_id(), component_version_id=version_id, format="ONNX", precision="FP16",
        artifact_id=build.artifact().id, sha256=bytes(32), input_contract_json={},
        created_at=build.clock(),
    )  # fmt: skip
    return ModelExport(**(fields | kw))


def new_variant(build: ModelFactory, export_id: uuid.UUID, key: str, **kw: Any) -> RuntimeVariant:
    fields: dict[str, Any] = dict(
        id=build.new_id(), model_export_id=export_id, provider="CUDA", device_kind="GPU",
        variant_key=key, requirements_json={}, state="AVAILABLE",
    )  # fmt: skip
    return RuntimeVariant(**(fields | kw))


def test_a_catalog_row_is_added_whole_and_flushed_but_not_committed(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    version = build.component_version()
    build.session.commit()
    export = new_export(build, version.id)
    build.session.commit()  # (its artifact too: no write lock held while the repository writes)

    with factory() as session:
        RuntimeCatalogRepository(session).add(export)
        with factory() as other:
            assert other.get(ModelExport, export.id) is None
        session.rollback()


def test_a_catalog_row_that_breaks_a_constraint_fails_at_the_add(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    version = build.component_version()
    component = build.session.get(Component, version.component_id)
    assert component is not None
    short = new_export(build, version.id, sha256=bytes(31))
    build.session.commit()

    with factory() as session, pytest.raises(IntegrityError, match="sha256_length"):
        RuntimeCatalogRepository(session).add(short)
    with factory() as session, pytest.raises(IntegrityError, match="UNIQUE"):
        RuntimeCatalogRepository(session).add(
            Component(
                id=build.new_id(),
                key=component.key,
                kind="FACE_DETECTOR",
                display_name="x",
                state="ACTIVE",
            )
        )


def test_components_versions_and_exports_are_read_oldest_first(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    version = build.component_version()
    start = build.clock()
    exports = [
        new_export(build, version.id, created_at=start + timedelta(seconds=i)) for i in (2, 0, 1)
    ]
    other_version = build.component_version()
    other_export = new_export(build, other_version.id)
    for export in (*exports, other_export):
        build.add(export)
    build.session.commit()
    component = build.session.get(Component, version.component_id)
    assert component is not None

    with factory() as session:
        repo = RuntimeCatalogRepository(session)
        found = repo.component_by_key(component.key)
        assert found is not None
        assert found.id == component.id
        assert repo.component_by_key("no-such-key") is None
        assert [v.id for v in repo.versions_of(component.id)] == [version.id]
        assert [e.id for e in repo.exports_of(version.id)] == [
            exports[1].id, exports[2].id, exports[0].id
        ]  # fmt: skip
        assert repo.exports_of(uuid.UUID(int=9)) == []
        assert repo.versions_of(uuid.UUID(int=9)) == []


def test_variants_are_found_through_the_validated_mapping_in_a_stable_order(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    version = build.component_version()
    space, other_space = build.representation_space(), build.representation_space()
    export = build.add(new_export(build, version.id))
    cuda, cpu, unvalidated = (
        build.add(new_variant(build, export.id, key)) for key in ("b-cuda", "a-cpu", "c-trt")
    )
    for variant, target, state in (
        (cuda, space, "VALIDATED"), (cpu, space, "VALIDATED"), (unvalidated, space, "PENDING"),
        (cuda, other_space, "VALIDATED"),
    ):  # fmt: skip
        build.add(
            RuntimeVariantRepresentationSpace(
                runtime_variant_id=variant.id,
                representation_space_id=target.id,
                validation_json={},
                state=state,
            )
        )
    build.session.commit()

    with factory() as session:
        repo = RuntimeCatalogRepository(session)
        assert [v.id for v in repo.variants_for_space(space.id, states=["VALIDATED"])] == [
            cpu.id, cuda.id
        ]  # fmt: skip
        assert [v.id for v in repo.variants_for_space(space.id, states=["PENDING"])] == [
            unvalidated.id
        ]  # fmt: skip
        assert [v.id for v in repo.variants_for_space(other_space.id, states=["VALIDATED"])] == [
            cuda.id
        ]  # fmt: skip
        assert repo.variants_for_space(space.id, states=[]) == []
        with pytest.raises(TypeError, match="not a single string"):
            repo.variants_for_space(space.id, states="VALIDATED")


def test_calibration_profiles_are_listed_newest_first_per_space(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    space, other_space = build.representation_space(), build.representation_space()
    start = build.clock()
    profiles = [
        build.add(
            RecognitionCalibrationProfile(
                id=build.new_id(), representation_space_id=space.id, version=f"v{i}",
                state="ACTIVE", parameters_json={}, schema_version=1,
                created_at=start + timedelta(minutes=i),
            )
        )
        for i in range(3)
    ]  # fmt: skip
    build.add(
        RecognitionCalibrationProfile(
            id=build.new_id(), representation_space_id=other_space.id, version="v0",
            state="ACTIVE", parameters_json={}, schema_version=1, created_at=start,
        )
    )  # fmt: skip
    build.session.commit()

    with factory() as session:
        repo = RuntimeCatalogRepository(session)
        assert [p.id for p in repo.calibration_profiles(space.id)] == [
            profiles[2].id, profiles[1].id, profiles[0].id
        ]  # fmt: skip
        assert repo.calibration_profiles(uuid.UUID(int=9)) == []


def test_packages_are_found_by_key(factory: sessionmaker[Session], build: ModelFactory) -> None:
    package = build.add(
        RuntimePackage(
            id=build.new_id(),
            key="core-models",
            manifest_schema_version=1,
            manifest_json={},
            state="TRUSTED",
            created_at=build.clock(),
        )
    )
    build.session.commit()

    with factory() as session:
        repo = RuntimeCatalogRepository(session)
        found = repo.package_by_key("core-models")
        assert found is not None
        assert found.id == package.id
        assert repo.package_by_key("other") is None


def installation_fixture(
    build: ModelFactory,
) -> tuple[InstalledModelExport, RuntimePackageInstallation]:
    version = build.component_version()
    export = build.add(new_export(build, version.id))
    package = build.add(
        RuntimePackage(
            id=build.new_id(),
            key="core-models",
            manifest_schema_version=1,
            manifest_json={},
            state="TRUSTED",
            created_at=build.clock(),
        )
    )
    installed_export = build.add(
        InstalledModelExport(
            id=build.new_id(),
            model_export_id=export.id,
            artifact_id=build.artifact().id,
            state="INSTALLING",
        )
    )
    installed_package = build.add(
        RuntimePackageInstallation(
            id=build.new_id(),
            runtime_package_id=package.id,
            artifact_id=build.artifact().id,
            state="INSTALLING",
        )
    )
    build.session.commit()
    return installed_export, installed_package


def test_installations_are_listed_for_their_export_and_package(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    installed_export, installed_package = installation_fixture(build)

    with factory() as session:
        repo = RuntimeCatalogRepository(session)
        assert [i.id for i in repo.export_installations(installed_export.model_export_id)] == [
            installed_export.id
        ]  # fmt: skip
        assert [i.id for i in repo.package_installations(installed_package.runtime_package_id)] == [
            installed_package.id
        ]  # fmt: skip
        assert repo.export_installations(uuid.UUID(int=9)) == []
        assert repo.package_installations(uuid.UUID(int=9)) == []


@pytest.mark.parametrize("kind", ["export", "package"])
def test_an_installation_changes_state_only_from_a_state_the_caller_expects(
    kind: str, factory: sessionmaker[Session], build: ModelFactory
) -> None:
    installed_export, installed_package = installation_fixture(build)
    row_id = installed_export.id if kind == "export" else installed_package.id
    model: Any = InstalledModelExport if kind == "export" else RuntimePackageInstallation
    stamp = build.clock()

    def transition(repo: RuntimeCatalogRepository, **kw: Any) -> bool:
        method = (
            repo.transition_export_installation
            if kind == "export"
            else repo.transition_package_installation
        )
        return method(row_id, **kw)

    with factory() as session:
        repo = RuntimeCatalogRepository(session)
        assert (
            transition(repo, from_states=["INSTALLED"], to_state="FAILED") is False
        )  # wrong state
        assert transition(
            repo, from_states=["INSTALLING"], to_state="INSTALLED", installed_at=stamp,
            verified_at=stamp,
        )  # fmt: skip
        session.commit()
    with factory() as session:
        row = session.get(model, row_id)
        assert row is not None
        assert (row.state, row.installed_at, row.verified_at, row.failure_detail) == (
            "INSTALLED", stamp, stamp, None
        )  # fmt: skip
        assert transition(
            RuntimeCatalogRepository(session), from_states=["INSTALLED"], to_state="FAILED",
            failure_detail="checksum mismatch",
        )  # fmt: skip
        session.commit()
    with factory() as session:
        row = session.get(model, row_id)
        assert row is not None
        assert (row.state, row.installed_at, row.verified_at, row.failure_detail) == (
            "FAILED", None, None, "checksum mismatch"
        )  # fmt: skip
        with pytest.raises(TypeError, match="not a single string"):
            transition(
                RuntimeCatalogRepository(session), from_states="FAILED", to_state="INSTALLING"
            )


def test_installation_changes_leave_the_catalog_rows_alone(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    installed_export, _ = installation_fixture(build)
    export_before = build.session.get(ModelExport, installed_export.model_export_id)
    assert export_before is not None
    snapshot = (export_before.format, export_before.precision, export_before.sha256)

    with factory() as session:
        RuntimeCatalogRepository(session).transition_export_installation(
            installed_export.id, from_states=["INSTALLING"], to_state="INSTALLED"
        )
        session.commit()
    with factory() as session:
        export = session.get(ModelExport, installed_export.model_export_id)
        assert export is not None
        assert (export.format, export.precision, export.sha256) == snapshot


def test_versions_of_a_component_are_read_oldest_first_not_in_version_string_order(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    """The unique index orders by the version string; "oldest first" is by creation time, so the
    dates here run against the strings."""
    newest = build.component_version()  # "1.0.0", created now
    start = build.clock()
    older = [
        build.add(
            ComponentVersion(
                id=build.new_id(),
                component_id=newest.component_id,
                semantic_version=version,
                contract_schema_version=1,
                contract_json={},
                created_at=start - timedelta(days=days),
            )
        )
        for version, days in (("3.0.0", 1), ("2.0.0", 2))
    ]
    build.session.commit()

    with factory() as session:
        versions = RuntimeCatalogRepository(session).versions_of(newest.component_id)
        assert [v.id for v in versions] == [older[1].id, older[0].id, newest.id]


# --- findings of the review ---------------------------------------------------------------------


def test_a_catalog_row_that_is_already_persistent_is_refused_not_updated(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    version = build.component_version()
    export = new_export(build, version.id)
    build.session.add(export)
    build.session.commit()

    with factory() as session:
        stored = session.get(ModelExport, export.id)
        assert stored is not None
        stored.precision = "INT8"  # a change a flush would turn into an UPDATE
        with pytest.raises(ValueError, match="immutable"):
            RuntimeCatalogRepository(session).add(stored)
        session.rollback()
    with factory() as session:
        row = session.get(ModelExport, export.id)
        assert row is not None
        assert row.precision == "FP16"


def test_ties_are_broken_by_id_in_every_ordered_read(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    first = build.component_version()
    space = build.representation_space()
    when = build.clock()
    ids = [uuid.UUID(int=n) for n in (3, 1, 2)]  # added out of id order
    versions = [
        build.add(
            ComponentVersion(
                id=row_id, component_id=first.component_id, semantic_version=f"9.0.{n}",
                contract_schema_version=1, contract_json={}, created_at=when,
            )
        )
        for n, row_id in enumerate(ids)
    ]  # fmt: skip
    exports = [build.add(new_export(build, first.id, id=row_id, created_at=when)) for row_id in ids]
    variants = [build.add(new_variant(build, exports[0].id, "same-key", id=i)) for i in ids]
    for variant in variants:
        build.add(
            RuntimeVariantRepresentationSpace(
                runtime_variant_id=variant.id, representation_space_id=space.id,
                validation_json={}, state="VALIDATED",
            )
        )  # fmt: skip
    profiles = [
        build.add(
            RecognitionCalibrationProfile(
                id=row_id, representation_space_id=space.id, version=f"v{n}", state="ACTIVE",
                parameters_json={}, schema_version=1, created_at=when,
            )
        )
        for n, row_id in enumerate(ids)
    ]  # fmt: skip
    build.session.commit()
    ascending = sorted(ids)

    with factory() as session:
        repo = RuntimeCatalogRepository(session)
        same_time = [v.id for v in repo.versions_of(first.component_id) if v.id in ids]
        assert same_time == ascending
        assert [e.id for e in repo.exports_of(first.id)] == ascending
        assert [v.id for v in repo.variants_for_space(space.id, states=["VALIDATED"])] == ascending
        assert [p.id for p in repo.calibration_profiles(space.id)] == sorted(ids, reverse=True)
    assert len(versions) == len(exports) == len(profiles) == 3


def test_installations_of_one_export_or_package_are_listed_by_id(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    installed_export, installed_package = installation_fixture(build)
    ids = [uuid.UUID(int=n) for n in (3, 1, 2)]
    for row_id in ids:
        build.add(
            InstalledModelExport(
                id=row_id, model_export_id=installed_export.model_export_id,
                artifact_id=build.artifact().id, state="INSTALLING",
            )
        )  # fmt: skip
        build.add(
            RuntimePackageInstallation(
                id=row_id, runtime_package_id=installed_package.runtime_package_id,
                artifact_id=build.artifact().id, state="INSTALLING",
            )
        )  # fmt: skip
    build.session.commit()

    with factory() as session:
        repo = RuntimeCatalogRepository(session)
        exports = [i.id for i in repo.export_installations(installed_export.model_export_id)]
        packages = [i.id for i in repo.package_installations(installed_package.runtime_package_id)]
    assert exports == sorted([installed_export.id, *ids])
    assert packages == sorted([installed_package.id, *ids])


def test_a_transition_writes_what_it_is_given_so_an_omitted_time_is_lost_and_a_detail_clears(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    installed_export, _ = installation_fixture(build)
    stamp = build.clock()

    def row_state() -> tuple[object, ...]:
        with factory() as session:
            row = session.get(InstalledModelExport, installed_export.id)
            assert row is not None
            return (row.state, row.installed_at, row.failure_detail)

    steps: list[tuple[str, str, dict[str, Any]]] = [
        ("INSTALLING", "FAILED", {"failure_detail": "checksum mismatch"}),
        ("FAILED", "INSTALLED", {"installed_at": stamp}),  # a success clears the old detail
        ("INSTALLED", "VERIFYING", {}),  # installed_at was not passed again: it is cleared
    ]
    expected = [
        ("FAILED", None, "checksum mismatch"),
        ("INSTALLED", stamp, None),
        ("VERIFYING", None, None),
    ]
    for (source, target, values), after in zip(steps, expected, strict=True):
        with factory() as session:
            assert RuntimeCatalogRepository(session).transition_export_installation(
                installed_export.id, from_states=[source], to_state=target, **values
            )
            session.commit()
        assert row_state() == after


def test_only_one_of_two_concurrent_installation_transitions_wins(
    factory: sessionmaker[Session], sqlite_engine: Engine, build: ModelFactory
) -> None:
    installed_export, _ = installation_fixture(build)

    def attempt(to_state: str) -> bool:
        with factory() as session:
            done = RuntimeCatalogRepository(session).transition_export_installation(
                installed_export.id, from_states=["INSTALLING"], to_state=to_state
            )
            session.commit()
            return done

    with (
        rendezvous_before_write(sqlite_engine, "UPDATE installed_model_exports", parties=2),
        ThreadPoolExecutor(max_workers=2) as pool,
    ):
        outcomes = list(pool.map(attempt, ["INSTALLED", "FAILED"]))

    assert sorted(outcomes) == [False, True]
