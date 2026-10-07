"""The reference-model package builder: what it declares is what the installer accepts."""

import hashlib
import json
from pathlib import Path

import pytest

from backend.app.runtime.manifest import file_problems, parse_manifest
from backend.app.runtime.reference_package import (
    Provenance,
    ReferenceModel,
    reference_manifest,
    write_reference_package,
)

PROVENANCE = Provenance("non-commercial research", "https://example.test/pack.zip", False)


@pytest.fixture
def models(tmp_path: Path) -> tuple[ReferenceModel, ReferenceModel]:
    (tmp_path / "in").mkdir()
    detector = tmp_path / "in" / "det.onnx"
    embedder = tmp_path / "in" / "emb.onnx"
    detector.write_bytes(b"detector bytes")
    embedder.write_bytes(b"embedder bytes")
    return ReferenceModel("det", detector, "scrfd"), ReferenceModel("emb", embedder, "arcface")


def test_the_manifest_parses_and_declares_cuda_first_then_cpu(models, tmp_path) -> None:  # type: ignore[no-untyped-def]
    manifest = reference_manifest(
        "ref-pack", "1.0.0", *models, dimension=512, provenance=PROVENANCE
    )
    parsed = parse_manifest(json.dumps(manifest))
    assert [e.sha256.hex() for e in parsed.exports] == [
        hashlib.sha256(b"detector bytes").hexdigest(),
        hashlib.sha256(b"embedder bytes").hexdigest(),
    ]
    assert [v.provider for v in parsed.variants if v.export_file == "models/det.onnx"] == [
        "CUDAExecutionProvider",
        "CPUExecutionProvider",
    ]
    assert parsed.exports[0].provenance.redistributable is False
    assert parsed.components[1].contract["dimension"] == 512


def test_a_written_package_passes_the_installers_file_checks(models, tmp_path) -> None:  # type: ignore[no-untyped-def]
    manifest = reference_manifest(
        "ref-pack", "1.0.0", *models, dimension=512, provenance=PROVENANCE
    )
    directory = write_reference_package(
        manifest, {"det.onnx": models[0].file, "emb.onnx": models[1].file}, tmp_path / "out"
    )
    parsed = parse_manifest((directory / "manifest.json").read_text(encoding="utf-8"))
    assert directory.name == "ref-pack"
    assert file_problems(directory, parsed) == []


def test_the_package_registers_in_the_catalog_as_one_space_with_both_variants(  # type: ignore[no-untyped-def]
    models, tmp_path, sqlite_engine, new_id, clock
) -> None:
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from backend.app.memory.models import RepresentationSpace
    from backend.app.runtime.models import ModelExport, RuntimeVariant
    from backend.app.runtime.package_store import InstalledPackage
    from backend.app.runtime.registration import register_package

    manifest = reference_manifest(
        "ref-pack", "1.0.0", *models, dimension=512, provenance=PROVENANCE
    )
    directory = write_reference_package(
        manifest, {"det.onnx": models[0].file, "emb.onnx": models[1].file}, tmp_path / "out"
    )
    parsed = parse_manifest((directory / "manifest.json").read_text(encoding="utf-8"))
    with Session(sqlite_engine) as session:
        registered = register_package(
            session, InstalledPackage(parsed.key, parsed.version, directory, parsed),
            new_id=new_id, clock=clock,
        )  # fmt: skip
        session.commit()
        assert len(session.scalars(select(ModelExport)).all()) == 2
        providers = sorted(v.provider for v in session.scalars(select(RuntimeVariant)))
        assert providers == ["CPUExecutionProvider"] * 2 + ["CUDAExecutionProvider"] * 2
        (space,) = session.scalars(select(RepresentationSpace)).all()
        assert space.dimension == 512
        embedder = next(e for e in registered.exports if e.representation_space_id is not None)
        assert embedder.representation_space_id == space.id
