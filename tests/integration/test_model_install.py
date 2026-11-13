"""Installing the face models the user obtained (M8 step 5, R6): the table is the only trust."""

import hashlib
import json
import uuid
import zipfile
from dataclasses import replace
from pathlib import Path

import pytest

from backend.app.runtime import model_install
from backend.app.runtime.model_install import (
    KNOWN_FILES,
    PACKAGE_KEY,
    ModelSourceError,
    install_models,
)
from backend.app.runtime.package_store import PackageExistsError, RuntimePackageStore
from backend.infrastructure.storage.layout import StorageRoots
from tests.fixtures.onnx_models import detector_model, embedder_model

DETECTOR, EMBEDDER = KNOWN_FILES[0].name, KNOWN_FILES[1].name


@pytest.fixture
def store(tmp_path: Path) -> RuntimePackageStore:
    roots = StorageRoots(tmp_path / "library", tmp_path / "state")
    roots.ensure_layout()
    return RuntimePackageStore(roots, new_id=uuid.uuid4)


@pytest.fixture
def models(tmp_path: Path) -> Path:
    """Small stand-in models under the real names, in a folder the user might have unpacked."""
    folder = tmp_path / "downloaded"
    folder.mkdir()
    (folder / DETECTOR).write_bytes(detector_model(()))
    (folder / EMBEDDER).write_bytes(embedder_model(dimension=512))
    return folder


@pytest.fixture
def trusted(models: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The table says these stand-ins are the selected models (real weights are never in a test)."""
    table = tuple(
        replace(
            known,
            size_bytes=(models / known.name).stat().st_size,
            sha256=hashlib.sha256((models / known.name).read_bytes()).hexdigest(),
        )
        for known in KNOWN_FILES
    )
    monkeypatch.setattr(model_install, "KNOWN_FILES", table)


def test_models_that_match_the_table_are_installed_with_a_gpu_and_a_cpu_variant(
    models: Path, trusted: None, store: RuntimePackageStore
) -> None:
    installed = install_models(models, store, allow_fixture=False)

    assert installed.key == PACKAGE_KEY
    assert store.get(PACKAGE_KEY) is not None
    assert store.verify(PACKAGE_KEY) == []
    manifest = json.loads((installed.path / "manifest.json").read_text(encoding="utf-8"))
    providers = {variant["provider"] for variant in manifest["variants"]}
    assert {"DmlExecutionProvider", "CPUExecutionProvider"} <= providers
    assert manifest["exports"][0]["provenance"]["redistributable"] is False


def test_a_zip_is_unpacked_for_the_two_files_by_their_base_names(
    models: Path, trusted: None, store: RuntimePackageStore, tmp_path: Path
) -> None:
    archive = tmp_path / "buffalo_l.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        for known in KNOWN_FILES:
            bundle.write(models / known.name, f"buffalo_l/{known.name}")
        bundle.writestr("buffalo_l/genderage.onnx", b"not used")

    install_models(archive, store, allow_fixture=False)

    assert store.get(PACKAGE_KEY) is not None


def test_a_folder_inside_the_chosen_folder_is_looked_into(
    models: Path, trusted: None, store: RuntimePackageStore, tmp_path: Path
) -> None:
    outer = tmp_path / "outer"
    (outer / "buffalo_l").mkdir(parents=True)
    for known in KNOWN_FILES:
        (outer / "buffalo_l" / known.name).write_bytes((models / known.name).read_bytes())

    install_models(outer, store, allow_fixture=False)

    assert store.get(PACKAGE_KEY) is not None


def test_a_file_that_is_not_the_selected_model_is_refused_and_nothing_is_installed(
    models: Path, trusted: None, store: RuntimePackageStore
) -> None:
    (models / EMBEDDER).write_bytes(embedder_model(dimension=512) + b"\0")

    with pytest.raises(ModelSourceError, match=EMBEDDER):
        install_models(models, store, allow_fixture=False)

    assert store.get(PACKAGE_KEY) is None
    assert store.installed() == []


def test_a_refused_install_leaves_the_models_that_were_already_installed_working(
    models: Path, trusted: None, store: RuntimePackageStore, tmp_path: Path
) -> None:
    first = install_models(models, store, allow_fixture=False)
    before = (first.path / "manifest.json").read_bytes()
    damaged = tmp_path / "damaged"
    damaged.mkdir()
    (damaged / DETECTOR).write_bytes(b"not the selected detector")
    (damaged / EMBEDDER).write_bytes((models / EMBEDDER).read_bytes())

    with pytest.raises(ModelSourceError, match=DETECTOR):
        install_models(damaged, store, allow_fixture=False)

    assert store.get(PACKAGE_KEY) is not None
    assert store.verify(PACKAGE_KEY) == []  # every file of the first install still matches
    assert (first.path / "manifest.json").read_bytes() == before
    assert not list(store.root.parent.parent.joinpath("temp").iterdir())  # no scratch is left


def test_a_missing_file_a_missing_path_and_a_bad_zip_are_refused(
    models: Path, trusted: None, store: RuntimePackageStore, tmp_path: Path
) -> None:
    (models / DETECTOR).unlink()
    with pytest.raises(ModelSourceError, match=DETECTOR):
        install_models(models, store, allow_fixture=False)
    with pytest.raises(ModelSourceError, match="does not exist"):
        install_models(tmp_path / "nowhere", store, allow_fixture=False)
    not_a_zip = tmp_path / "pack.zip"
    not_a_zip.write_bytes(b"plain bytes")
    with pytest.raises(ModelSourceError, match="not a zip"):
        install_models(not_a_zip, store, allow_fixture=False)


def test_a_zip_member_larger_than_its_model_is_refused_before_it_is_written(
    models: Path, trusted: None, store: RuntimePackageStore, tmp_path: Path
) -> None:
    archive = tmp_path / "bomb.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr(DETECTOR, bytes(KNOWN_FILES[0].size_bytes + 1))

    with pytest.raises(ModelSourceError, match="larger"):
        install_models(archive, store, allow_fixture=False)


def test_installing_the_same_models_again_changes_nothing_and_other_models_are_refused(
    models: Path, trusted: None, store: RuntimePackageStore
) -> None:
    first = install_models(models, store, allow_fixture=False)
    assert install_models(models, store, allow_fixture=False).path == first.path

    (models / EMBEDDER).write_bytes(embedder_model(dimension=512) + b"\x00")
    (models / "fixture.json").write_text(json.dumps({"fixture": True}), encoding="utf-8")
    with pytest.raises(PackageExistsError):  # a different package under the same key
        install_models(models, store, allow_fixture=True)

    assert store.verify(PACKAGE_KEY) == []


def test_a_fixture_folder_is_accepted_only_where_fixtures_are_allowed(
    models: Path, store: RuntimePackageStore
) -> None:
    """The real table is in force (no `trusted`): these stand-ins are not the selected models."""
    (models / "fixture.json").write_text(json.dumps({"fixture": True}), encoding="utf-8")

    with pytest.raises(ModelSourceError, match="not the selected model"):
        install_models(models, store, allow_fixture=False)  # a production build
    assert store.get(PACKAGE_KEY) is None

    install_models(models, store, allow_fixture=True)  # the development profile
    assert store.get(PACKAGE_KEY) is not None


@pytest.mark.parametrize("declared", ["not json", '["fixture"]', '{"fixture": "yes"}', "{}"])
def test_only_a_file_that_declares_itself_a_fixture_makes_one(
    models: Path, store: RuntimePackageStore, declared: str
) -> None:
    (models / "fixture.json").write_text(declared, encoding="utf-8")

    with pytest.raises(ModelSourceError, match="not the selected model"):
        install_models(models, store, allow_fixture=True)
