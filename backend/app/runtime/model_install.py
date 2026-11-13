"""Installing the face models the user obtained (M8 step 5, decision R6).

The weights are never bundled and never downloaded by the application: the user points at the
folder or the zip they downloaded from InsightFace, and this module installs them as the one
runtime package the real profile runs. Each file is checked against the size and SHA-256 recorded
in `docs/guides/INSTALLING_MODELS_WINDOWS.md` (the evidence of the evaluation applies only to
those files); a file that differs is refused and nothing is installed.

The table is the only thing a production build trusts. Under the development profile, and only
there, a folder that holds a `fixture.json` declaring itself a fixture is accepted with the files'
own measured hashes, so the same flow can be exercised without the weights; a production build
rejects that folder like any other file that is not in the table.
"""

import hashlib
import json
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from backend.app.runtime.package_store import InstalledPackage, RuntimePackageStore
from backend.app.runtime.reference_package import (
    Provenance,
    ReferenceModel,
    reference_manifest,
    write_reference_package,
)

PACKAGE_KEY = "insightface-buffalo-l"
PACKAGE_VERSION = "1.0.0"
LICENCE = "InsightFace pretrained models: non-commercial research purposes only"
SOURCE_URL = "https://github.com/deepinsight/insightface/releases/tag/v0.7"
FIXTURE_FILE = "fixture.json"
DIMENSION = 512


@dataclass(frozen=True, slots=True)
class KnownFile:
    name: str
    size_bytes: int
    sha256: str
    component_key: str
    family: str  # (descriptive provenance only)


# The two files of `buffalo_l.zip` the application uses (the pack's other files are not used).
KNOWN_FILES = (
    KnownFile(
        "det_10g.onnx",
        16_923_827,
        "5838f7fe053675b1c7a08b633df49e7af5495cee0493c7dcf6697200b85b5b91",
        "scrfd-10g",
        "scrfd",
    ),
    KnownFile(
        "w600k_r50.onnx",
        174_383_860,
        "4c06341c33c2ca1f86781dab0e829f88ad5b64be9fba56e56bc9ebdefc619e43",
        "arcface-r50",
        "arcface",
    ),
)


class ModelSourceError(Exception):
    """What the user pointed at cannot be installed. Nothing of it is left behind."""


def install_models(
    source: Path,
    store: RuntimePackageStore,
    *,
    allow_fixture: bool,
) -> InstalledPackage:
    """Install the two models found in `source` (a folder, or a zip holding them) as the package
    `PACKAGE_KEY`. Raises `ModelSourceError` for anything the table does not accept, and the
    store's `PackageExistsError` when the package is already installed."""
    if not source.exists():
        raise ModelSourceError("that folder or file does not exist")
    temp = store.root.parent.parent / "temp"  # (machine-local, the same volume as the store)
    temp.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=temp) as scratch_name:
        scratch = Path(scratch_name)
        files = _unpacked(source, scratch / "files")
        fixture = allow_fixture and _declares_fixture(source)
        for known in KNOWN_FILES:
            _check(known, files[known.name], accept_any=fixture)
        detector, embedder = (
            ReferenceModel(known.component_key, files[known.name], known.family)
            for known in KNOWN_FILES
        )
        manifest = reference_manifest(
            PACKAGE_KEY,
            PACKAGE_VERSION,
            detector,
            embedder,
            dimension=DIMENSION,
            provenance=Provenance(LICENCE, SOURCE_URL, redistributable=False),
        )
        package = write_reference_package(
            manifest, {path.name: path for path in files.values()}, scratch / "package"
        )
        return store.install(package, facts={})


def _unpacked(source: Path, target: Path) -> dict[str, Path]:
    """The two files by name: copied out of a zip (only those two, by their base name, and never
    more bytes than the table says) or taken from the folder."""
    target.mkdir(parents=True)
    wanted = {known.name: known for known in KNOWN_FILES}
    found: dict[str, Path] = {}
    if source.is_file():
        try:
            archive = zipfile.ZipFile(source)
        except zipfile.BadZipFile:
            raise ModelSourceError("that file is not a zip archive") from None
        with archive:
            for member in archive.infolist():
                name = PurePosixPath(member.filename).name
                if member.is_dir() or name not in wanted or name in found:
                    continue
                if member.file_size > wanted[name].size_bytes:
                    raise ModelSourceError(f"{name} in the zip is larger than the model it names")
                with archive.open(member) as inside, (target / name).open("wb") as out:
                    shutil.copyfileobj(inside, out)
                found[name] = target / name
    else:
        for name in wanted:
            candidates = [source / name, *source.glob(f"*/{name}")]
            path = next((candidate for candidate in candidates if candidate.is_file()), None)
            if path is not None:
                shutil.copyfile(path, target / name)
                found[name] = target / name
    missing = [name for name in wanted if name not in found]
    if missing:
        raise ModelSourceError(f"{', '.join(missing)} not found in what you chose")
    return found


def _check(known: KnownFile, path: Path, *, accept_any: bool) -> None:
    if accept_any:
        return
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as file:
        while chunk := file.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    if size != known.size_bytes or digest.hexdigest() != known.sha256:
        raise ModelSourceError(
            f"{known.name} is not the selected model (its size or SHA-256 differs from the "
            "recorded one), so it is not installed"
        )


def _declares_fixture(source: Path) -> bool:
    try:
        declared = json.loads((source / FIXTURE_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError, NotADirectoryError):
        return False
    return isinstance(declared, dict) and declared.get("fixture") is True
