"""Registering an installed runtime package in the library's catalog (issue 80; ML 9.1 and 18.1).

Real SQLite. Proved here: the catalog says what the package is (components, versions, exports,
variants, referenced artifacts, installation records); every embedder export is one representation
space whose identity is the owner's list (and not the execution provider); catalog rows are never
updated (what differs is refused); registering again finds the same rows; and nothing is committed
on the caller's behalf.
"""

import copy
import hashlib
import json
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.memory.models import RepresentationSpace
from backend.app.runtime.manifest import parse_manifest
from backend.app.runtime.models import (
    Component,
    ComponentVersion,
    InstalledModelExport,
    ModelExport,
    RuntimePackage,
    RuntimePackageInstallation,
    RuntimeVariant,
    RuntimeVariantRepresentationSpace,
)
from backend.app.runtime.package_store import InstalledPackage
from backend.app.runtime.registration import (
    DECLARED,
    FINGERPRINT_SCHEME,
    RegisteredPackage,
    RegistrationError,
    register_package,
    space_identity,
    space_key,
)
from backend.app.sources.models import Artifact, ArtifactKind, ArtifactState, StorageMode
from backend.infrastructure.db.engine import create_session_factory
from tests.fixtures.deterministic import SeededUUIDs

DETECTOR_BYTES = b"detector weights"
EMBEDDER_BYTES = b"embedder weights"
EMBEDDER_FP16_BYTES = b"embedder weights, half precision"
EMBEDDER_CONTRACT = {
    "family": "arcface",
    "dimension": 512,
    "preprocessing_contract": "arcface-112-similarity-v1",
    "normalization": "L2_NORMALIZED",
    "normalization_contract_version": "l2-v1",
    "compatibility_version": "1",
}
DETECTOR_CONTRACT = {"preprocessing_contract": "scrfd-letterbox-v1"}


def manifest_dict(
    key: str = "reference-cpu",
    *,
    provider: str = "CPUExecutionProvider",
    device: str = "CPU",
    embedder: bytes = EMBEDDER_BYTES,
    embedder_contract: dict[str, Any] | None = None,
    extra_embedder_export: bytes | None = None,
    requirements: dict[str, Any] | None = None,
) -> dict[str, Any]:
    def export(component: str, file: str, data: bytes, precision: str = "FP32") -> dict[str, Any]:
        return {
            "component": component,
            "file": file,
            "format": "ONNX",
            "precision": precision,
            "sha256": hashlib.sha256(data).hexdigest(),
            "size_bytes": len(data),
            "input_contract": {"layout": "NCHW"},
            "provenance": {"license": "MIT", "source": "fixture", "redistributable": False},
        }

    def variant(file: str, name: str) -> dict[str, Any]:
        return {
            "export_file": file,
            "provider": provider,
            "device_kind": device,
            "variant_key": name,
            "requirements": requirements or {},
        }

    exports = [
        export("detector", "models/detector.onnx", DETECTOR_BYTES),
        export("embedder", "models/embedder.onnx", embedder),
    ]
    variants = [
        variant("models/detector.onnx", f"detector-{device}"),
        variant("models/embedder.onnx", f"embedder-{device}"),
    ]
    if extra_embedder_export is not None:
        exports.append(
            export("embedder", "models/embedder-fp16.onnx", extra_embedder_export, "FP16")
        )
        variants.append(variant("models/embedder-fp16.onnx", f"embedder-fp16-{device}"))
    return {
        "schema_version": 1,
        "key": key,
        "version": "1.0.0",
        "requirements": {},
        "components": [
            {"key": "detector", "kind": "FACE_DETECTOR", "version": "1.0.0",
             "contract": copy.deepcopy(DETECTOR_CONTRACT)},
            {"key": "embedder", "kind": "FACE_REPRESENTATION", "version": "1.0.0",
             "contract": copy.deepcopy(embedder_contract or EMBEDDER_CONTRACT)},
        ],
        "exports": exports,
        "variants": variants,
    }  # fmt: skip


def installed(directory: Path, manifest: dict[str, Any]) -> InstalledPackage:
    """A package as the installer leaves it: a directory with its manifest (and files)."""
    directory.mkdir(parents=True, exist_ok=True)
    text = json.dumps(manifest)
    (directory / "manifest.json").write_text(text, encoding="utf-8")
    parsed = parse_manifest(text)
    return InstalledPackage(parsed.key, parsed.version, directory, parsed)


@pytest.fixture
def factory(sqlite_engine: Engine) -> sessionmaker[Session]:
    return create_session_factory(sqlite_engine)


@pytest.fixture
def register(
    new_id: SeededUUIDs, clock: Callable[[], Any]
) -> Callable[[Session, InstalledPackage], RegisteredPackage]:
    def call(session: Session, package: InstalledPackage) -> RegisteredPackage:
        return register_package(session, package, new_id=new_id, clock=clock)

    return call


def count(session: Session, model: Any) -> int:
    return int(session.scalar(select(func.count()).select_from(model)) or 0)


# --- what registration records ---------------------------------------------------------------


def test_a_package_is_recorded_as_components_exports_variants_and_referenced_artifacts(
    factory: sessionmaker[Session], register: Any, tmp_path: Path
) -> None:
    package = installed(tmp_path / "pkg", manifest_dict())
    with factory() as session:
        result = register(session, package)
        session.commit()
    with factory() as session:
        assert {c.key: c.kind for c in session.scalars(select(Component))} == {
            "detector": "FACE_DETECTOR",
            "embedder": "FACE_REPRESENTATION",
        }
        versions = {v.id: v for v in session.scalars(select(ComponentVersion))}
        assert sorted(
            v.contract_json.get("preprocessing_contract", "") for v in versions.values()
        ) == [
            "arcface-112-similarity-v1",
            "scrfd-letterbox-v1",
        ]
        exports = {e.sha256: e for e in session.scalars(select(ModelExport))}
        assert set(exports) == {
            hashlib.sha256(DETECTOR_BYTES).digest(),
            hashlib.sha256(EMBEDDER_BYTES).digest(),
        }
        assert {e.format for e in exports.values()} == {"ONNX"}
        assert {e.precision for e in exports.values()} == {"FP32"}
        assert count(session, InstalledModelExport) == 2
        variants = {v.variant_key: v for v in session.scalars(select(RuntimeVariant))}
        assert set(variants) == {"detector-CPU", "embedder-CPU"}
        assert {v.provider for v in variants.values()} == {"CPUExecutionProvider"}
        row = session.scalars(select(RuntimePackage)).one()
        assert (row.key, row.state, row.manifest_schema_version) == (
            "reference-cpu",
            "REGISTERED",
            1,
        )
        assert row.manifest_json == json.loads((package.path / "manifest.json").read_text("utf-8"))
        installation = session.scalars(select(RuntimePackageInstallation)).one()
        assert installation.state == "INSTALLED"
        assert installation.runtime_package_id == row.id
        assert (result.runtime_package_id, result.installation_id) == (row.id, installation.id)
        by_file = {e.file: e for e in result.exports}
        assert set(by_file) == {"models/detector.onnx", "models/embedder.onnx"}
        detector = by_file["models/detector.onnx"]
        assert detector.representation_space_id is None
        assert detector.variant_ids == {"detector-CPU": variants["detector-CPU"].id}


def test_every_file_is_a_referenced_artifact_never_a_managed_copy(
    factory: sessionmaker[Session], register: Any, tmp_path: Path
) -> None:
    package = installed(tmp_path / "pkg", manifest_dict())
    with factory() as session:
        result = register(session, package)
        session.commit()
    with factory() as session:
        artifacts = {a.id: a for a in session.scalars(select(Artifact))}
        assert len(artifacts) == 3  # two model files and the package directory
        assert {a.storage_mode for a in artifacts.values()} == {StorageMode.REFERENCED}
        assert {a.state for a in artifacts.values()} == {ArtifactState.AVAILABLE}
        assert all(a.storage_key is None for a in artifacts.values())
        models = {
            a.external_path: a for a in artifacts.values() if a.kind == ArtifactKind.MODEL_EXPORT
        }
        assert set(models) == {
            str(package.path / "models" / "detector.onnx"),
            str(package.path / "models" / "embedder.onnx"),
        }
        embedder = models[str(package.path / "models" / "embedder.onnx")]
        assert embedder.sha256 == hashlib.sha256(EMBEDDER_BYTES).digest()
        assert embedder.size_bytes == len(EMBEDDER_BYTES)
        (folder,) = [a for a in artifacts.values() if a.kind == ArtifactKind.RUNTIME_PACKAGE]
        assert folder.external_path == str(package.path)
        manifest_bytes = (package.path / "manifest.json").read_bytes()
        assert folder.sha256 == hashlib.sha256(manifest_bytes).digest()  # the manifest's hash
        assert folder.size_bytes == len(manifest_bytes)
        installation = session.scalars(select(RuntimePackageInstallation)).one()
        assert installation.artifact_id == folder.id
        by_file = {e.file: e for e in result.exports}
        export = by_file["models/embedder.onnx"]
        assert export.artifact_id == embedder.id
        installed_export = session.scalars(
            select(InstalledModelExport).where(
                InstalledModelExport.model_export_id == export.model_export_id
            )
        ).one()
        assert installed_export.artifact_id == embedder.id


def test_an_embedder_export_is_one_representation_space_with_the_recorded_identity(
    factory: sessionmaker[Session], register: Any, tmp_path: Path
) -> None:
    package = installed(tmp_path / "pkg", manifest_dict())
    with factory() as session:
        result = register(session, package)
        session.commit()
    digest = hashlib.sha256(EMBEDDER_BYTES).hexdigest()
    identity = {
        "family": "arcface",
        "weights_digest": digest,
        "dimension": 512,
        "preprocessing_contract": "arcface-112-similarity-v1",
        "normalization": "L2_NORMALIZED",
        "normalization_contract_version": "l2-v1",
        "model_compatibility_version": "1",
    }
    assert space_identity(EMBEDDER_CONTRACT, digest) == identity
    with factory() as session:
        space = session.scalars(select(RepresentationSpace)).one()
        assert space.semantic_key == space_key(identity)
        assert space.semantic_key.startswith(f"{FINGERPRINT_SCHEME}:")
        assert (space.dimension, space.metric, space.normalization, space.state) == (
            512,
            "COSINE",
            "L2_NORMALIZED",
            "ACTIVE",
        )
        assert space.contract_json == identity | {"fingerprint_scheme": FINGERPRINT_SCHEME}
        assert space.contract_schema_version == 1
        embedder = next(e for e in result.exports if e.kind == "FACE_REPRESENTATION")
        assert embedder.representation_space_id == space.id
        assert space.component_version_id == embedder.component_version_id
        compat = session.scalars(select(RuntimeVariantRepresentationSpace)).one()
        assert compat.representation_space_id == space.id
        assert compat.runtime_variant_id == embedder.variant_ids["embedder-CPU"]
        assert compat.state == DECLARED
        assert compat.validation_json == {"declared_by_package": "reference-cpu"}
        assert count(session, RuntimeVariantRepresentationSpace) == 1  # the detector has none


# --- identity ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "change",
    [
        {"family": "adaface"},
        {"dimension": 256},
        {"preprocessing_contract": "arcface-112-similarity-v2"},
        {"normalization": "NONE"},
        {"normalization_contract_version": "l2-v2"},
        {"compatibility_version": "2"},
    ],
)
def test_each_part_of_the_identity_makes_a_different_space(change: dict[str, Any]) -> None:
    base = space_key(space_identity(EMBEDDER_CONTRACT, "ab" * 32))
    assert space_key(space_identity(EMBEDDER_CONTRACT | change, "ab" * 32)) != base
    assert space_key(space_identity(EMBEDDER_CONTRACT, "cd" * 32)) != base  # the weights digest


def test_the_fingerprint_scheme_is_pinned() -> None:
    """A stored key must mean the same thing for ever: the canonical form is part of the data."""
    identity = space_identity(EMBEDDER_CONTRACT, "ab" * 32)
    assert (
        space_key(identity)
        == "rs1:a4802a9ca39a96417fe1fd730a5e20aa43af15838bb71f25b9e44e876e2f1a29"
    )


def test_the_fingerprint_ignores_everything_but_the_identity() -> None:
    noisy = EMBEDDER_CONTRACT | {"note": "irrelevant", "provider": "CUDAExecutionProvider"}
    assert space_key(space_identity(noisy, "ab" * 32)) == space_key(
        space_identity(EMBEDDER_CONTRACT, "ab" * 32)
    )
    assert "provider" not in space_identity(noisy, "ab" * 32)


@pytest.mark.parametrize(
    "second",
    [
        {"variant_key": "embedder-other"},  # only the name differs
        {"provider": "CUDAExecutionProvider"},  # only the provider differs
        {"device_kind": "CUDA"},  # only the device differs
    ],
)
def test_a_variant_that_differs_in_any_one_respect_is_another_variant_of_the_same_export(
    factory: sessionmaker[Session],
    register: Any,
    tmp_path: Path,
    second: dict[str, str],
) -> None:
    other = manifest_dict("other")
    other["variants"][1] = other["variants"][1] | second
    with factory() as session:
        register(session, installed(tmp_path / "a", manifest_dict("one")))
        result = register(session, installed(tmp_path / "b", other))
        session.commit()
        embedder = next(e for e in result.exports if e.kind == "FACE_REPRESENTATION")
        assert len(embedder.variant_ids) == 1
    with factory() as session:
        assert count(session, RuntimeVariant) == 3  # not folded into the first package's variant
        assert count(session, RuntimeVariantRepresentationSpace) == 2  # both reach the one space


def test_the_same_weights_under_another_provider_are_the_same_space(
    factory: sessionmaker[Session], register: Any, tmp_path: Path
) -> None:
    cpu = installed(tmp_path / "cpu", manifest_dict("reference-cpu"))
    cuda = installed(
        tmp_path / "cuda",
        manifest_dict("reference-cuda", provider="CUDAExecutionProvider", device="CUDA"),
    )
    with factory() as session:
        first = register(session, cpu)
        second = register(session, cuda)
        session.commit()
    assert first.runtime_package_id != second.runtime_package_id
    spaces = {e.representation_space_id for r in (first, second) for e in r.exports}
    assert len(spaces - {None}) == 1
    with factory() as session:
        assert count(session, RepresentationSpace) == 1
        assert count(session, Component) == 2  # shared, not duplicated
        assert count(session, ComponentVersion) == 2
        assert count(session, ModelExport) == 2
        assert count(session, InstalledModelExport) == 4  # but each package has its own install
        assert {v.provider for v in session.scalars(select(RuntimeVariant))} == {
            "CPUExecutionProvider",
            "CUDAExecutionProvider",
        }
        compat = session.scalars(select(RuntimeVariantRepresentationSpace)).all()
        assert len(compat) == 2  # both embedder variants point at the one space


def test_other_weights_are_another_space_even_for_the_same_component_version(
    factory: sessionmaker[Session], register: Any, tmp_path: Path
) -> None:
    both = installed(tmp_path / "both", manifest_dict(extra_embedder_export=EMBEDDER_FP16_BYTES))
    with factory() as session:
        result = register(session, both)
        session.commit()
    spaces = {e.file: e.representation_space_id for e in result.exports}
    assert spaces["models/embedder.onnx"] != spaces["models/embedder-fp16.onnx"]
    with factory() as session:
        assert count(session, RepresentationSpace) == 2
        assert count(session, ComponentVersion) == 2  # one embedder version, two exports
        digests = {
            s.contract_json["weights_digest"] for s in session.scalars(select(RepresentationSpace))
        }
        assert digests == {
            hashlib.sha256(EMBEDDER_BYTES).hexdigest(),
            hashlib.sha256(EMBEDDER_FP16_BYTES).hexdigest(),
        }


# --- registering again and refusing what differs --------------------------------------------------


def test_registering_the_same_package_again_finds_what_it_made(
    factory: sessionmaker[Session], register: Any, tmp_path: Path
) -> None:
    package = installed(tmp_path / "pkg", manifest_dict(extra_embedder_export=EMBEDDER_FP16_BYTES))
    with factory() as session:
        first = register(session, package)
        session.commit()
    tables = (Component, ComponentVersion, ModelExport, InstalledModelExport, RuntimeVariant,
              RuntimePackage, RuntimePackageInstallation, RepresentationSpace, Artifact,
              RuntimeVariantRepresentationSpace)  # fmt: skip
    with factory() as session:
        before = {t.__name__: count(session, t) for t in tables}
        again = register(session, package)
        session.commit()
        assert again == first
        assert {t.__name__: count(session, t) for t in tables} == before
    with factory() as session:
        assert register(session, package) == first  # (and from a fresh session)


def test_registering_again_finds_its_own_rows_among_a_packages_that_share_them(
    factory: sessionmaker[Session], register: Any, tmp_path: Path
) -> None:
    cpu = installed(tmp_path / "cpu", manifest_dict("reference-cpu"))
    cuda = installed(
        tmp_path / "cuda",
        manifest_dict("reference-cuda", provider="CUDAExecutionProvider", device="CUDA"),
    )
    with factory() as session:
        first_cpu = register(session, cpu)
        first_cuda = register(session, cuda)
        session.commit()
    with factory() as session:
        assert register(session, cpu) == first_cpu
        assert register(session, cuda) == first_cuda
        assert first_cpu.exports[1].artifact_id != first_cuda.exports[1].artifact_id


def test_the_same_weights_in_a_new_component_version_get_their_own_export_row(
    factory: sessionmaker[Session], register: Any, tmp_path: Path
) -> None:
    with factory() as session:
        register(session, installed(tmp_path / "a", manifest_dict("one")))
        session.commit()
    bump = manifest_dict("two")  # the same file bytes, announced as the next version
    for component in bump["components"]:
        component["version"] = "1.1.0"
    with factory() as session:
        register(session, installed(tmp_path / "b", bump))
        session.commit()
    with factory() as session:
        assert count(session, ModelExport) == 4  # an export belongs to one component version
        assert count(session, RepresentationSpace) == 1  # but the weights are one space


def test_a_different_package_under_the_same_key_is_refused(
    factory: sessionmaker[Session], register: Any, tmp_path: Path
) -> None:
    with factory() as session:
        register(session, installed(tmp_path / "a", manifest_dict()))
        session.commit()
    other = installed(tmp_path / "b", manifest_dict(embedder=b"other weights"))
    with factory() as session, pytest.raises(RegistrationError, match="different package"):
        register(session, other)


def test_a_component_versions_contract_is_immutable(
    factory: sessionmaker[Session], register: Any, tmp_path: Path
) -> None:
    with factory() as session:
        register(session, installed(tmp_path / "a", manifest_dict("one")))
        session.commit()
    changed = installed(
        tmp_path / "b",
        manifest_dict("two", embedder_contract=EMBEDDER_CONTRACT | {"compatibility_version": "9"}),
    )
    with factory() as session, pytest.raises(RegistrationError, match="immutable"):
        register(session, changed)


def test_a_new_version_of_a_known_component_is_added_beside_the_old_one(
    factory: sessionmaker[Session], register: Any, tmp_path: Path
) -> None:
    with factory() as session:
        register(session, installed(tmp_path / "a", manifest_dict("one")))
        session.commit()
    upgrade = manifest_dict("two", embedder=b"better weights")
    upgrade["components"][1]["version"] = "2.0.0"
    with factory() as session:
        result = register(session, installed(tmp_path / "b", upgrade))
        session.commit()
    with factory() as session:
        embedder_versions = session.scalars(
            select(ComponentVersion.semantic_version)
            .join(Component, Component.id == ComponentVersion.component_id)
            .where(Component.key == "embedder")
            .order_by(ComponentVersion.semantic_version)
        ).all()
        assert embedder_versions == ["1.0.0", "2.0.0"]
        assert count(session, RepresentationSpace) == 2  # the old weights keep their space
        assert count(session, Component) == 2
    assert {e.component_key for e in result.exports} == {"detector", "embedder"}


def test_a_space_whose_recorded_identity_was_tampered_with_is_not_reused(
    factory: sessionmaker[Session], register: Any, tmp_path: Path
) -> None:
    with factory() as session:
        register(session, installed(tmp_path / "a", manifest_dict("one")))
        space = session.scalars(select(RepresentationSpace)).one()
        space.contract_json = {**space.contract_json, "dimension": 7}  # the key no longer fits
        session.commit()
    with factory() as session, pytest.raises(RegistrationError, match="another identity record"):
        register(session, installed(tmp_path / "b", manifest_dict("two")))


def test_a_component_cannot_change_kind(
    factory: sessionmaker[Session], register: Any, tmp_path: Path
) -> None:
    with factory() as session:
        register(session, installed(tmp_path / "a", manifest_dict("one")))
        session.commit()
    swapped = manifest_dict("two")
    swapped["components"][0]["kind"] = "FACE_REPRESENTATION"
    swapped["components"][0]["contract"] = copy.deepcopy(EMBEDDER_CONTRACT)
    with factory() as session, pytest.raises(RegistrationError, match="registered as a"):
        register(session, installed(tmp_path / "b", swapped))


def test_the_same_weights_cannot_come_back_with_another_precision_or_input_contract(
    factory: sessionmaker[Session], register: Any, tmp_path: Path
) -> None:
    with factory() as session:
        register(session, installed(tmp_path / "a", manifest_dict("one")))
        session.commit()
    for field, value in (("precision", "FP16"), ("input_contract", {"layout": "NHWC"})):
        other = manifest_dict("two")
        other["exports"][1][field] = value
        with factory() as session, pytest.raises(RegistrationError, match="immutable"):
            register(session, installed(tmp_path / f"b-{field}", other))


def test_a_variant_cannot_come_back_with_other_requirements(
    factory: sessionmaker[Session], register: Any, tmp_path: Path
) -> None:
    with factory() as session:
        register(session, installed(tmp_path / "a", manifest_dict("one")))
        session.commit()
    other = installed(tmp_path / "b", manifest_dict("two", requirements={"gpu": ["any"]}))
    with factory() as session, pytest.raises(RegistrationError, match="other requirements"):
        register(session, other)


def test_registration_joins_the_callers_transaction_and_never_commits(
    factory: sessionmaker[Session], register: Any, tmp_path: Path
) -> None:
    package = installed(tmp_path / "pkg", manifest_dict())
    with factory() as session:
        register(session, package)
        session.rollback()
    with factory() as session:
        assert count(session, RuntimePackage) == 0
        assert count(session, Artifact) == 0
        assert count(session, RepresentationSpace) == 0


def test_a_refused_registration_leaves_nothing_once_the_caller_rolls_back(
    factory: sessionmaker[Session], register: Any, tmp_path: Path
) -> None:
    with factory() as session:
        register(session, installed(tmp_path / "a", manifest_dict("one")))
        session.commit()
    broken = manifest_dict("two", requirements={"gpu": ["any"]})
    with factory() as session:
        before = count(session, Artifact)
        with pytest.raises(RegistrationError):
            register(session, installed(tmp_path / "b", broken))
        session.rollback()
    with factory() as session:
        assert count(session, Artifact) == before
        assert count(session, RuntimePackage) == 1


# --- what a manifest must say ---------------------------------------------------------------------


def contract_cases() -> list[tuple[str, Callable[[dict[str, Any]], None], str]]:
    def embedder(change: Callable[[dict[str, Any]], None]) -> Callable[[dict[str, Any]], None]:
        return lambda m: change(m["components"][1]["contract"])

    return [
        (
            "a kind that is neither",
            lambda m: m["components"][0].update(kind="FACE_QUALITY"),
            "kind",
        ),
        (
            "a detector without its contract",
            lambda m: m["components"][0]["contract"].clear(),
            "lacks",
        ),
        ("no family", embedder(lambda c: c.pop("family")), "lacks"),
        ("no dimension", embedder(lambda c: c.pop("dimension")), "lacks"),
        ("no preprocessing", embedder(lambda c: c.pop("preprocessing_contract")), "lacks"),
        ("no normalization", embedder(lambda c: c.pop("normalization")), "lacks"),
        (
            "no normalization version",
            embedder(lambda c: c.pop("normalization_contract_version")),
            "lacks",
        ),
        ("no compatibility version", embedder(lambda c: c.pop("compatibility_version")), "lacks"),
        ("a zero dimension", embedder(lambda c: c.update(dimension=0)), "dimension"),
        ("a boolean dimension", embedder(lambda c: c.update(dimension=True)), "dimension"),
        ("a text dimension", embedder(lambda c: c.update(dimension="512")), "dimension"),
        ("an empty family", embedder(lambda c: c.update(family="")), "family"),
        (
            "a number as the preprocessing",
            embedder(lambda c: c.update(preprocessing_contract=3)),
            "preprocessing",
        ),
    ]


@pytest.mark.parametrize(
    ("why", "change", "match"), contract_cases(), ids=lambda v: v if isinstance(v, str) else ""
)
def test_a_manifest_that_does_not_say_what_a_space_needs_is_refused(
    factory: sessionmaker[Session],
    register: Any,
    tmp_path: Path,
    why: str,
    change: Callable[[dict[str, Any]], None],
    match: str,
) -> None:
    manifest = manifest_dict()
    change(manifest)
    with factory() as session, pytest.raises(RegistrationError, match=match):
        register(session, installed(tmp_path / "pkg", manifest))
    with factory() as session:
        assert count(session, Component) == 0


def test_ids_come_from_the_callers_generator(
    factory: sessionmaker[Session], register: Any, tmp_path: Path
) -> None:
    with factory() as session:
        result = register(session, installed(tmp_path / "pkg", manifest_dict()))
        assert isinstance(result.runtime_package_id, uuid.UUID)
        session.commit()
