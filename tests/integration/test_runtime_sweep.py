"""Installation records follow the disk (issue 80; ML 18.1, Architecture 12.2).

Real SQLite and a real package store. Proved here: a package or model file that leaves this
machine is marked `MISSING` (by existence alone) and the planner then refuses it, never
substituting another; only a re-registration, which verifies every byte, brings a record back; a
swapped file is refused and the record stays `MISSING`; and a file that cannot be examined is not
treated as gone.
"""

import shutil
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.runtime.models import InstalledModelExport, RuntimePackageInstallation
from backend.app.runtime.package_store import InstalledPackage, RuntimePackageStore
from backend.app.runtime.registration import (
    INSTALLED,
    MISSING,
    InstallationSweep,
    RegisteredPackage,
    RegistrationError,
    mark_missing_installations,
    missing_dependencies,
    register_package,
)
from backend.app.runtime.worker_config import (
    RuntimeUnavailableError,
    plan_perception,
)
from backend.app.sources.models import Artifact, ArtifactState
from backend.infrastructure.db.engine import create_session_factory
from backend.infrastructure.storage.layout import StorageRoots
from tests.factories.models import ModelFactory
from tests.fixtures.catalog_packages import manifest_dict, package_files
from tests.fixtures.deterministic import FrozenClock, SeededUUIDs

CPU = "CPUExecutionProvider"


@pytest.fixture
def factory(sqlite_engine: Engine) -> sessionmaker[Session]:
    return create_session_factory(sqlite_engine)


@pytest.fixture
def store(storage_roots: StorageRoots, new_id: SeededUUIDs) -> RuntimePackageStore:
    return RuntimePackageStore(storage_roots, new_id=new_id)


class World:
    def __init__(
        self,
        factory: sessionmaker[Session],
        store: RuntimePackageStore,
        tmp_path: Path,
        new_id: SeededUUIDs,
        clock: FrozenClock,
    ) -> None:
        self.factory, self.store, self.tmp_path = factory, store, tmp_path
        self.new_id, self.clock = new_id, clock
        self.package: InstalledPackage = store.install(
            package_files(tmp_path / "source", manifest_dict()), {}
        )

    def register(self) -> RegisteredPackage:
        with self.factory() as session:
            result = register_package(session, self.package, new_id=self.new_id, clock=self.clock)
            session.commit()
        return result

    def sweep(self) -> InstallationSweep:
        with self.factory() as session:
            report = mark_missing_installations(session)
            session.commit()
        return report

    def states(self) -> tuple[list[str], list[str]]:
        with self.factory() as session:
            return (
                [r.state for r in session.scalars(select(RuntimePackageInstallation))],
                sorted(r.state for r in session.scalars(select(InstalledModelExport))),
            )

    def plan(self, result: RegisteredPackage) -> Any:
        detector = next(e for e in result.exports if e.component_key == "detector")
        embedder = next(e for e in result.exports if e.component_key == "embedder")
        assert embedder.representation_space_id is not None
        with self.factory() as session:
            return plan_perception(
                session,
                self.store,
                detector_component_version_id=detector.component_version_id,
                representation_space_id=embedder.representation_space_id,
                providers=(CPU,),
            )


@pytest.fixture
def world(
    factory: sessionmaker[Session],
    store: RuntimePackageStore,
    tmp_path: Path,
    new_id: SeededUUIDs,
    clock: FrozenClock,
) -> World:
    return World(factory, store, tmp_path, new_id, clock)


def test_nothing_changes_while_everything_is_on_disk(world: World) -> None:
    world.register()

    assert world.sweep() == InstallationSweep(0, 0)
    assert world.states() == ([INSTALLED], [INSTALLED, INSTALLED])


def test_a_model_file_that_left_the_machine_is_missing_and_the_planner_refuses_it(
    world: World,
) -> None:
    result = world.register()
    (world.package.path / "models" / "embedder.onnx").unlink()

    assert world.sweep() == InstallationSweep(0, 1)  # only that file's record
    assert world.states() == ([INSTALLED], [INSTALLED, MISSING])
    with pytest.raises(RuntimeUnavailableError):
        world.plan(result)  # never another package's weights instead


def test_a_package_that_left_the_machine_is_missing_with_its_files(world: World) -> None:
    result = world.register()
    shutil.rmtree(world.package.path)

    assert world.sweep() == InstallationSweep(1, 2)
    assert world.states() == ([MISSING], [MISSING, MISSING])
    with world.factory() as session:
        detail = session.scalars(select(RuntimePackageInstallation.failure_detail)).one()
        assert detail == "the package is not on this machine"
    with pytest.raises(RuntimeUnavailableError):
        world.plan(result)


def test_the_sweep_is_repeatable_and_only_ever_moves_installed_to_missing(world: World) -> None:
    world.register()
    shutil.rmtree(world.package.path)
    world.sweep()

    assert world.sweep() == InstallationSweep(0, 0)  # already missing: nothing to do
    assert world.states() == ([MISSING], [MISSING, MISSING])


def test_registering_the_restored_package_reinstates_every_record_and_artifact(
    world: World, tmp_path: Path
) -> None:
    result = world.register()
    shutil.rmtree(world.package.path)
    world.sweep()
    world.package = world.store.install(
        package_files(tmp_path / "again", manifest_dict()), {}
    )  # the same bytes, restored

    again = world.register()

    assert again == result  # the same catalog rows, not new ones
    assert world.states() == ([INSTALLED], [INSTALLED, INSTALLED])
    with world.factory() as session:
        record = session.scalars(select(RuntimePackageInstallation)).one()
        assert record.failure_detail is None
        assert record.verified_at is not None
        artifact_states = {a.state for a in session.scalars(select(Artifact))}
        assert artifact_states == {ArtifactState.AVAILABLE}
    assert world.plan(again)  # and the planner offers it again


def test_a_file_that_came_back_changed_is_refused_and_the_record_stays_missing(
    world: World,
) -> None:
    world.register()
    (world.package.path / "models" / "embedder.onnx").unlink()
    world.sweep()
    (world.package.path / "models" / "embedder.onnx").write_bytes(b"not the weights")

    with pytest.raises(RegistrationError):
        world.register()

    assert world.states() == ([INSTALLED], [INSTALLED, MISSING])


def test_an_artifact_the_startup_check_already_marked_missing_is_swept_too(world: World) -> None:
    world.register()
    with world.factory() as session:  # startup recovery found the file gone, then it came back
        for artifact in session.scalars(select(Artifact)):
            artifact.state = ArtifactState.MISSING
        session.commit()

    assert world.sweep() == InstallationSweep(1, 2)  # present on disk, but not trusted
    world.register()  # verified again
    assert world.states() == ([INSTALLED], [INSTALLED, INSTALLED])
    with world.factory() as session:
        assert {a.state for a in session.scalars(select(Artifact))} == {ArtifactState.AVAILABLE}
        assert {a.failure_code for a in session.scalars(select(Artifact))} == {None}


def test_a_file_that_cannot_be_examined_is_not_treated_as_gone(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    world.register()
    original = Path.stat

    def locked(self: Path, *args: Any, **kwargs: Any) -> Any:
        if self.name == "embedder.onnx":
            raise PermissionError("denied")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", locked)

    assert world.sweep() == InstallationSweep(0, 0)
    assert world.states() == ([INSTALLED], [INSTALLED, INSTALLED])


def test_the_same_package_at_another_place_leaves_the_old_record_missing_not_replaced(
    world: World, tmp_path: Path, storage_roots: StorageRoots, new_id: SeededUUIDs
) -> None:
    world.register()
    other = RuntimePackageStore(
        StorageRoots(storage_roots.library_root, tmp_path / "another-machine"), new_id=new_id
    )
    shutil.rmtree(world.package.path)
    world.package = other.install(package_files(tmp_path / "elsewhere", manifest_dict()), {})

    world.register()  # this machine's package, at its own place
    world.sweep()  # the first place is gone

    packages, exports = world.states()
    assert sorted(packages) == [INSTALLED, MISSING]
    assert exports.count(INSTALLED) == 2
    assert exports.count(MISSING) == 2


def test_registering_only_reinstates_a_missing_record_never_another_state(world: World) -> None:
    world.register()
    with world.factory() as session:
        record = session.scalars(select(InstalledModelExport)).first()
        assert record is not None
        record.state = "FAILED"
        record.failure_detail = "the copy was interrupted"
        session.commit()

    world.register()

    with world.factory() as session:
        states = sorted(r.state for r in session.scalars(select(InstalledModelExport)))
        assert states == ["FAILED", INSTALLED]  # only MISSING is ever reinstated
        details = [r.failure_detail for r in session.scalars(select(InstalledModelExport))]
        assert "the copy was interrupted" in details


def test_a_file_replacing_a_parent_folder_means_the_file_is_gone(world: World) -> None:
    world.register()
    shutil.rmtree(world.package.path / "models")
    (world.package.path / "models").write_bytes(b"a file where the folder was")

    assert world.sweep() == InstallationSweep(0, 2)  # nothing can be below a regular file


def test_a_known_missing_artifact_is_swept_even_when_the_disk_cannot_be_examined(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    world.register()
    with world.factory() as session:  # startup recovery found the files gone; access then returned
        for artifact in session.scalars(select(Artifact)):
            artifact.state = ArtifactState.MISSING
        session.commit()
    original = Path.stat

    def denied(self: Path, *args: Any, **kwargs: Any) -> Any:
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "stat", denied)

    assert world.sweep() == InstallationSweep(1, 2)  # the artifact already says it is not there
    monkeypatch.setattr(Path, "stat", original)
    world.register()  # verified: everything is back, artifacts included
    assert world.states() == ([INSTALLED], [INSTALLED, INSTALLED])
    with world.factory() as session:
        assert {a.state for a in session.scalars(select(Artifact))} == {ArtifactState.AVAILABLE}


# --- the packages a library depends on --------------------------------------------------------


def hold_vectors(world: World, result: RegisteredPackage) -> None:
    """The library holds an active vector made by this package's embedder."""
    embedder = next(e for e in result.exports if e.component_key == "embedder")
    with world.factory() as session:
        build = ModelFactory(session, world.clock, world.new_id)
        build.representation(
            representation_space_id=embedder.representation_space_id, state="ACTIVE", ann_key=1
        )
        session.commit()


def dependencies(world: World) -> list[str]:
    with world.factory() as session:
        return missing_dependencies(session)


def test_a_library_with_no_vectors_depends_on_nothing(world: World) -> None:
    world.register()
    shutil.rmtree(world.package.path)
    world.sweep()

    assert dependencies(world) == []  # a package that made nothing is not a dependency


def test_a_missing_package_that_made_the_librarys_vectors_is_reported_by_name_and_version(
    world: World,
) -> None:
    result = world.register()
    hold_vectors(world, result)
    assert dependencies(world) == []  # installed: nothing is missing

    shutil.rmtree(world.package.path)
    world.sweep()

    assert dependencies(world) == ["reference-cpu 1.0.0"]


def test_another_package_does_not_stand_in_for_the_one_that_made_the_vectors(
    world: World, tmp_path: Path
) -> None:
    result = world.register()
    hold_vectors(world, result)
    shutil.rmtree(world.package.path)
    world.sweep()
    different = manifest_dict("other-package", embedder=b"different weights")
    world.package = world.store.install(package_files(tmp_path / "other", different), {})
    world.register()  # a healthy package with other weights, hence another space

    assert dependencies(world) == ["reference-cpu 1.0.0"]  # still needs its own


def test_restoring_the_package_clears_the_dependency(world: World, tmp_path: Path) -> None:
    result = world.register()
    hold_vectors(world, result)
    shutil.rmtree(world.package.path)
    world.sweep()
    assert dependencies(world) == ["reference-cpu 1.0.0"]

    world.package = world.store.install(package_files(tmp_path / "again", manifest_dict()), {})
    world.register()

    assert dependencies(world) == []


def test_a_space_without_a_known_package_is_named_by_its_key(world: World) -> None:
    with world.factory() as session:
        build = ModelFactory(session, world.clock, world.new_id)
        space = build.representation_space(semantic_key="abcdef0123456789-unknown")
        build.representation(representation_space_id=space.id, state="ACTIVE", ann_key=1)
        session.commit()

    assert dependencies(world) == ["representation space abcdef012345"]


def test_not_a_directory_is_absence_whatever_the_platform_calls_it(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    world.register()
    original = Path.stat

    def below_a_file(self: Path, *args: Any, **kwargs: Any) -> Any:
        if self.name == "embedder.onnx":
            raise NotADirectoryError(
                "a path component is a file"
            )  # (POSIX; Windows says not found)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", below_a_file)

    assert world.sweep() == InstallationSweep(0, 1)


@pytest.mark.parametrize("state", ["PENDING", "SUPERSEDED"])
def test_only_active_vectors_make_a_dependency(world: World, state: str) -> None:
    result = world.register()
    embedder = next(e for e in result.exports if e.component_key == "embedder")
    with world.factory() as session:
        build = ModelFactory(session, world.clock, world.new_id)
        build.representation(representation_space_id=embedder.representation_space_id, state=state)
        session.commit()
    shutil.rmtree(world.package.path)
    world.sweep()

    assert dependencies(world) == []  # private or retired vectors are not compared against
