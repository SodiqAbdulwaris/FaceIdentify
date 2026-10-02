"""The ML worker's configuration from the catalog and this machine's packages (issue 80).

Real SQLite and a real package store. Proved here: the plan offers only variants that can run here
and now (an installed, intact, declared file whose digest is the recorded one, with an allowed
provider), in the caller's order of preference; a package that is gone, damaged, elsewhere or not
what was recorded is reported with a reason and never replaced by anything else; and the text it
produces is what the worker accepts.
"""

import shutil
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, select, update
from sqlalchemy.orm import Session, sessionmaker

from backend.app.runtime.models import (
    Component,
    ComponentVersion,
    InstalledModelExport,
    RuntimeVariantRepresentationSpace,
)
from backend.app.runtime.package_store import InstalledPackage, RuntimePackageStore
from backend.app.runtime.registration import RegisteredPackage, register_package
from backend.app.runtime.worker_config import (
    PerceptionPlan,
    RuntimeUnavailableError,
    plan_perception,
)
from backend.app.sources.models import Artifact, ArtifactState
from backend.infrastructure.db.engine import create_session_factory
from backend.infrastructure.storage.layout import StorageRoots
from backend.ml.worker.perception_handlers import parse_config
from tests.fixtures.catalog_packages import (
    DETECTOR_BYTES,
    EMBEDDER_BYTES,
    EMBEDDER_FP16_BYTES,
    installed,
    manifest_dict,
    package_files,
)
from tests.fixtures.deterministic import SeededUUIDs

CPU = "CPUExecutionProvider"
CUDA = "CUDAExecutionProvider"


@pytest.fixture
def factory(sqlite_engine: Engine) -> sessionmaker[Session]:
    return create_session_factory(sqlite_engine)


@pytest.fixture
def store(storage_roots: StorageRoots, new_id: SeededUUIDs) -> RuntimePackageStore:
    return RuntimePackageStore(storage_roots, new_id=new_id)


class Library:
    """A library with packages installed on this machine and registered in the catalog."""

    def __init__(
        self,
        factory: sessionmaker[Session],
        store: RuntimePackageStore,
        tmp_path: Path,
        new_id: SeededUUIDs,
        clock: Callable[[], Any],
    ) -> None:
        self.factory, self.store, self.tmp_path = factory, store, tmp_path
        self.new_id, self.clock = new_id, clock
        self.counter = 0

    def install(self, manifest: dict[str, Any]) -> InstalledPackage:
        self.counter += 1
        source = package_files(self.tmp_path / f"source-{self.counter}", manifest)
        return self.store.install(source, {})

    def register(self, package: InstalledPackage) -> RegisteredPackage:
        with self.factory() as session:
            result = register_package(session, package, new_id=self.new_id, clock=self.clock)
            session.commit()
        return result

    def plan(
        self, result: RegisteredPackage, providers: tuple[str, ...] = (CPU,), **override: Any
    ) -> PerceptionPlan:
        detector = next(e for e in result.exports if e.component_key == "detector")
        embedder = next(e for e in result.exports if e.component_key == "embedder")
        arguments: dict[str, Any] = {
            "detector_component_version_id": detector.component_version_id,
            "representation_space_id": embedder.representation_space_id,
            "providers": providers,
        } | override
        with self.factory() as session:
            return plan_perception(session, self.store, **arguments)


@pytest.fixture
def library(
    factory: sessionmaker[Session],
    store: RuntimePackageStore,
    tmp_path: Path,
    new_id: SeededUUIDs,
    clock: Callable[[], Any],
) -> Library:
    return Library(factory, store, tmp_path, new_id, clock)


def with_cuda(manifest: dict[str, Any]) -> dict[str, Any]:
    """The same package, with a CUDA variant beside the CPU one for each export."""
    for variant in list(manifest["variants"]):
        manifest["variants"].append(
            variant
            | {
                "provider": CUDA,
                "device_kind": "CUDA",
                "variant_key": variant["variant_key"].replace("CPU", "CUDA"),
            }
        )
    return manifest


# --- what is offered ------------------------------------------------------------------------------


def test_the_installed_package_is_offered_with_its_verified_paths_and_the_workers_config(
    library: Library,
) -> None:
    package = library.install(manifest_dict())
    result = library.plan(library.register(package))
    (detector,) = result.detector
    (embedder,) = result.embedder
    assert detector.model_path == package.path / "models" / "detector.onnx"
    assert embedder.model_path == package.path / "models" / "embedder.onnx"
    assert (detector.kind, embedder.kind) == ("FACE_DETECTOR", "FACE_REPRESENTATION")
    assert detector.contract == "scrfd-letterbox-v1"
    assert embedder.contract == "arcface-112-similarity-v1"
    assert (detector.package_key, embedder.package_key) == ("reference-cpu", "reference-cpu")
    assert (detector.provider, detector.device) == (CPU, "CPU")
    assert result.dimension == 512
    parsed = {v.runtime_variant_id: v for v in parse_config(result.worker_config())}
    assert set(parsed) == {str(detector.runtime_variant_id), str(embedder.runtime_variant_id)}
    config_embedder = parsed[str(embedder.runtime_variant_id)]
    assert config_embedder.model_path == embedder.model_path
    assert config_embedder.sha256 == embedder.sha256
    assert config_embedder.dimension == 512
    assert config_embedder.contract == "arcface-112-similarity-v1"
    assert parsed[str(detector.runtime_variant_id)].dimension is None
    assert result.representation_space_id is not None


def test_the_callers_provider_order_is_the_order_variants_are_offered_in(
    library: Library,
) -> None:
    registered = library.register(library.install(with_cuda(manifest_dict())))
    cuda_first = library.plan(registered, (CUDA, CPU))
    assert [v.provider for v in cuda_first.detector] == [CUDA, CPU]
    assert [v.provider for v in cuda_first.embedder] == [CUDA, CPU]
    cpu_first = library.plan(registered, (CPU, CUDA))
    assert [v.provider for v in cpu_first.embedder] == [CPU, CUDA]
    only_cpu = library.plan(registered, (CPU,))
    assert [v.provider for v in only_cpu.detector] == [CPU]  # not allowed means not offered


def test_a_provider_nothing_can_run_on_is_reported_with_the_variants_that_needed_it(
    library: Library,
) -> None:
    registered = library.register(library.install(manifest_dict()))
    with pytest.raises(RuntimeUnavailableError) as refused:
        library.plan(registered, ("DmlExecutionProvider",))
    assert refused.value.what == "the detector"
    assert any(CPU in reason for reason in refused.value.reasons)


def test_a_package_is_verified_once_however_many_of_its_files_are_used(
    library: Library, factory: sessionmaker[Session]
) -> None:
    package = library.install(manifest_dict())
    registered = library.register(package)
    calls: list[str] = []

    class Counting(RuntimePackageStore):
        def verify(self, key: str) -> list[str]:
            calls.append(key)
            return super().verify(key)

    counting = Counting.__new__(Counting)
    counting.__dict__.update(library.store.__dict__)
    library.store = counting
    library.plan(registered)  # a detector and an embedder, both files of one package
    assert calls == ["reference-cpu"]


# --- never substituted ----------------------------------------------------------------------------


def test_a_package_that_is_no_longer_installed_is_reported_not_replaced(
    library: Library, store: RuntimePackageStore
) -> None:
    package = library.install(manifest_dict())
    registered = library.register(package)
    shutil.rmtree(package.path)
    with pytest.raises(RuntimeUnavailableError, match="not installed on this machine") as refused:
        library.plan(registered)
    assert refused.value.what == "the detector"


def test_a_damaged_package_is_reported_with_what_is_wrong(library: Library) -> None:
    package = library.install(manifest_dict())
    registered = library.register(package)
    (package.path / "models" / "detector.onnx").write_bytes(b"x" * len(DETECTOR_BYTES))
    with pytest.raises(RuntimeUnavailableError, match="damaged") as refused:
        library.plan(registered)
    assert "detector.onnx" in str(refused.value)


def test_a_damaged_embedder_is_reported_even_when_the_detector_is_fine(library: Library) -> None:
    package = library.install(manifest_dict(extra_embedder_export=EMBEDDER_FP16_BYTES))
    registered = library.register(package)
    (package.path / "models" / "embedder.onnx").write_bytes(b"y" * len(EMBEDDER_BYTES))
    with pytest.raises(RuntimeUnavailableError) as refused:
        library.plan(registered)  # (the whole package is verified, so the detector goes too)
    assert "damaged" in str(refused.value)


def test_another_space_is_never_a_substitute_for_the_one_asked_for(library: Library) -> None:
    package = library.install(manifest_dict(extra_embedder_export=EMBEDDER_FP16_BYTES))
    registered = library.register(package)
    full = next(e for e in registered.exports if e.file == "models/embedder.onnx")
    half = next(e for e in registered.exports if e.file == "models/embedder-fp16.onnx")
    assert full.representation_space_id != half.representation_space_id
    plan_full = library.plan(registered, representation_space_id=full.representation_space_id)
    plan_half = library.plan(registered, representation_space_id=half.representation_space_id)
    assert [v.model_path.name for v in plan_full.embedder] == ["embedder.onnx"]
    assert [v.model_path.name for v in plan_half.embedder] == ["embedder-fp16.onnx"]
    assert {v.sha256 for v in plan_full.embedder} != {v.sha256 for v in plan_half.embedder}


def test_an_installation_recorded_somewhere_else_is_not_a_model_path(
    library: Library, store: RuntimePackageStore, factory: sessionmaker[Session], tmp_path: Path
) -> None:
    elsewhere = library.install(manifest_dict())
    registered = library.register(elsewhere)
    outside = tmp_path / "outside" / "reference-cpu" / "models"
    outside.mkdir(parents=True)
    with factory() as session:
        for artifact in session.scalars(select(Artifact)):
            artifact.external_path = str(outside / Path(artifact.external_path or "x").name)
        session.commit()
    with pytest.raises(RuntimeUnavailableError, match="not in this machine's") as refused:
        library.plan(registered)
    assert refused.value.what == "the detector"


@pytest.mark.parametrize(
    ("rewrite", "why"),
    [
        (lambda root, a: str(root), "not a file of an installed package"),
        (lambda root, a: str(root / "reference-cpu"), "not a file of an installed package"),
        (lambda root, a: str(root / "no-such-package" / "models" / "m.onnx"), "not installed"),
        (
            lambda root, a: str(root / "reference-cpu" / "models" / "undeclared.onnx"),
            "not the recorded export",
        ),
        (
            lambda root, a: str(root / "reference-cpu" / "models" / "embedder.onnx"),
            "not the recorded export",  # the right package, another export's file
        ),
        (lambda root, a: str(root / ".." / "reference-cpu" / "models" / "m.onnx"), "not in this"),
    ],
)
def test_a_recorded_path_must_be_a_declared_file_of_an_installed_package_in_this_root(
    library: Library,
    store: RuntimePackageStore,
    factory: sessionmaker[Session],
    rewrite: Callable[[Path, Artifact], str],
    why: str,
) -> None:
    registered = library.register(library.install(manifest_dict()))
    detector = next(e for e in registered.exports if e.component_key == "detector")
    with factory() as session:
        artifact = session.get(Artifact, detector.artifact_id)
        assert artifact is not None
        artifact.external_path = rewrite(store.root, artifact)
        session.commit()
    with pytest.raises(RuntimeUnavailableError, match=why):
        library.plan(registered)


def test_an_artifact_that_is_not_available_is_not_offered(
    library: Library, factory: sessionmaker[Session]
) -> None:
    registered = library.register(library.install(manifest_dict()))
    detector = next(e for e in registered.exports if e.component_key == "detector")
    with factory() as session:
        artifact = session.get(Artifact, detector.artifact_id)
        assert artifact is not None
        artifact.state = ArtifactState.MISSING
        session.commit()
    with pytest.raises(RuntimeUnavailableError, match="recorded as MISSING"):
        library.plan(registered)


def test_an_export_with_no_recorded_installation_is_reported(
    library: Library, factory: sessionmaker[Session]
) -> None:
    registered = library.register(library.install(manifest_dict()))
    with factory() as session:
        session.execute(update(InstalledModelExport).values(state="REMOVED"))
        session.commit()
    with pytest.raises(RuntimeUnavailableError, match="no installation of export"):
        library.plan(registered)


def test_a_variant_not_validated_for_the_space_is_not_offered(
    library: Library, factory: sessionmaker[Session]
) -> None:
    registered = library.register(library.install(manifest_dict()))
    with factory() as session:
        session.execute(update(RuntimeVariantRepresentationSpace).values(state="REVOKED"))
        session.commit()
    with pytest.raises(RuntimeUnavailableError) as refused:
        library.plan(registered)
    assert refused.value.what == "the representation model"
    assert "validated for the space" in str(refused.value)


def test_a_library_from_another_machine_uses_the_installation_made_here(
    library: Library, factory: sessionmaker[Session], tmp_path: Path
) -> None:
    manifest = manifest_dict()
    there = installed(
        tmp_path / "other-machine", manifest
    )  # registered first, on the other machine
    with factory() as session:
        register_package(session, there, new_id=library.new_id, clock=library.clock)
        session.commit()
    here = library.install(manifest)
    registered = library.register(here)
    plan = library.plan(registered)
    assert plan.detector[0].model_path == here.path / "models" / "detector.onnx"
    assert plan.embedder[0].model_path == here.path / "models" / "embedder.onnx"


# --- what was asked for ---------------------------------------------------------------------------


def test_an_unknown_space_or_detector_is_reported(library: Library) -> None:
    registered = library.register(library.install(manifest_dict()))
    with pytest.raises(RuntimeUnavailableError, match="not in the library") as refused:
        library.plan(registered, representation_space_id=uuid.uuid4())
    assert refused.value.what == "the representation space"
    with pytest.raises(RuntimeUnavailableError, match="not recorded") as refused:
        library.plan(registered, detector_component_version_id=uuid.uuid4())
    assert refused.value.what == "the detector"


def test_a_component_of_the_wrong_kind_is_not_a_detector(library: Library) -> None:
    registered = library.register(library.install(manifest_dict()))
    embedder = next(e for e in registered.exports if e.component_key == "embedder")
    with pytest.raises(RuntimeUnavailableError, match="FACE_REPRESENTATION") as refused:
        library.plan(registered, detector_component_version_id=embedder.component_version_id)
    assert refused.value.what == "the detector"


def test_a_detector_with_nothing_recorded_for_it_is_reported(
    library: Library, factory: sessionmaker[Session]
) -> None:
    registered = library.register(library.install(manifest_dict()))
    with factory() as session:
        component = Component(
            id=library.new_id(),
            key="bare",
            kind="FACE_DETECTOR",
            display_name="bare",
            state="ACTIVE",
        )
        version = ComponentVersion(
            id=library.new_id(),
            component_id=component.id,
            semantic_version="1.0.0",
            contract_schema_version=1,
            contract_json={"preprocessing_contract": "x"},
            created_at=library.clock(),
        )
        session.add_all([component, version])
        session.commit()
        version_id = version.id
    with pytest.raises(RuntimeUnavailableError, match="no export is recorded"):
        library.plan(registered, detector_component_version_id=version_id)


# --- further cases the mutation pass asked for ---------------------------------------------------


def test_only_the_variants_validated_for_the_space_are_offered(
    library: Library, factory: sessionmaker[Session]
) -> None:
    registered = library.register(library.install(with_cuda(manifest_dict())))
    embedder = next(e for e in registered.exports if e.component_key == "embedder")
    with factory() as session:
        session.execute(
            update(RuntimeVariantRepresentationSpace)
            .where(
                RuntimeVariantRepresentationSpace.runtime_variant_id
                == embedder.variant_ids["embedder-CUDA"]
            )
            .values(state="REVOKED")
        )
        session.commit()
    plan = library.plan(registered, (CUDA, CPU))
    assert [v.provider for v in plan.embedder] == [CPU]  # the CUDA one was not validated
    assert [v.provider for v in plan.detector] == [CUDA, CPU]  # (the detector has no space)


def test_a_path_the_system_cannot_resolve_is_reported_not_raised(
    library: Library, monkeypatch: pytest.MonkeyPatch
) -> None:
    registered = library.register(library.install(manifest_dict()))
    real = Path.resolve

    def resolve(self: Path, strict: bool = False) -> Path:
        if self.name == "detector.onnx":
            raise OSError("the drive is not reachable")
        return real(self, strict)

    monkeypatch.setattr(Path, "resolve", resolve)
    with pytest.raises(RuntimeUnavailableError, match="not in this machine's") as refused:
        library.plan(registered)
    assert refused.value.what == "the detector"


def test_a_damaged_package_is_not_also_reported_as_having_no_installation(
    library: Library,
) -> None:
    package = library.install(manifest_dict())
    registered = library.register(package)
    (package.path / "models" / "detector.onnx").write_bytes(b"x" * len(DETECTOR_BYTES))
    with pytest.raises(RuntimeUnavailableError) as refused:
        library.plan(registered)
    assert not any("no installation" in reason for reason in refused.value.reasons)


def test_a_file_at_the_top_of_a_package_is_a_file_of_the_package(library: Library) -> None:
    manifest = manifest_dict()
    for export in manifest["exports"]:
        export["file"] = export["file"].replace("models/", "")
    for variant in manifest["variants"]:
        variant["export_file"] = variant["export_file"].replace("models/", "")
    package = library.install(manifest)
    plan = library.plan(library.register(package))
    assert plan.detector[0].model_path == package.path / "detector.onnx"
    assert plan.embedder[0].model_path == package.path / "embedder.onnx"


def test_the_same_weights_under_two_component_versions_each_keep_their_own_version(
    library: Library,
) -> None:
    first = library.register(library.install(manifest_dict("pkg-one")))
    bump = manifest_dict("pkg-two")
    for component in bump["components"]:
        component["version"] = "1.1.0"
    second = library.register(library.install(bump))
    space = next(e for e in first.exports if e.component_key == "embedder").representation_space_id
    assert (
        space
        == next(e for e in second.exports if e.component_key == "embedder").representation_space_id
    )
    plan = library.plan(first)
    versions = {v.component_version_id for v in plan.embedder}
    assert versions == {
        next(e for e in first.exports if e.component_key == "embedder").component_version_id,
        next(e for e in second.exports if e.component_key == "embedder").component_version_id,
    }
    assert {v.package_key for v in plan.embedder} == {"pkg-one", "pkg-two"}
