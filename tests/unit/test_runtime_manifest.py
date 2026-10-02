"""The runtime package manifest: strict parsing, path safety, compatibility, file integrity."""

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from backend.app.runtime.manifest import (
    ManifestError,
    PackageManifest,
    file_problems,
    incompatibilities,
    parse_manifest,
    safe_relative_path,
)
from tests.fixtures.links import link_directory

DETECTOR = b"detector weights"
EMBEDDER = b"embedder weights"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def manifest_dict() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "key": "reference-cpu",
        "version": "1.0.0",
        "requirements": {"os": ["windows"], "architecture": ["x86_64", "amd64"]},
        "components": [
            {
                "key": "detector",
                "kind": "FACE_DETECTOR",
                "version": "1.0.0",
                "contract": {"in": "rgb"},
            },
            {"key": "embedder", "kind": "FACE_REPRESENTATION", "version": "1.0.0", "contract": {}},
        ],
        "exports": [
            {
                "component": "detector",
                "file": "models/detector.onnx",
                "format": "ONNX",
                "precision": "FP32",
                "sha256": sha(DETECTOR),
                "size_bytes": len(DETECTOR),
                "input_contract": {"layout": "HWC"},
                "provenance": {
                    "license": "MIT",
                    "source": "https://example.test/d",
                    "redistributable": True,
                },
            },
            {
                "component": "embedder",
                "file": "models/embedder.onnx",
                "format": "ONNX",
                "precision": "FP32",
                "sha256": sha(EMBEDDER),
                "size_bytes": len(EMBEDDER),
                "input_contract": {},
                "provenance": {
                    "license": "unclear",
                    "source": "local fixture",
                    "redistributable": False,
                },
            },
        ],
        "variants": [
            {
                "export_file": "models/detector.onnx",
                "provider": "CPUExecutionProvider",
                "device_kind": "CPU",
                "variant_key": "detector-cpu",
                "requirements": {},
            },
            {
                "export_file": "models/embedder.onnx",
                "provider": "CPUExecutionProvider",
                "device_kind": "CPU",
                "variant_key": "embedder-cpu",
                "requirements": {},
            },
        ],
    }


def parse(data: dict[str, Any]) -> PackageManifest:
    return parse_manifest(json.dumps(data))


def broken(path: list[str | int], value: Any) -> dict[str, Any]:
    data = copy.deepcopy(manifest_dict())
    target: Any = data
    for step in path[:-1]:
        target = target[step]
    if value is _DELETE:
        del target[path[-1]]
    else:
        target[path[-1]] = value
    return data


_DELETE = object()


# --- parsing -------------------------------------------------------------------------------------


def test_a_valid_manifest_is_read_into_its_parts() -> None:
    manifest = parse(manifest_dict())

    assert (manifest.key, manifest.version, manifest.schema_version) == (
        "reference-cpu",
        "1.0.0",
        1,
    )
    assert manifest.requirements == {"os": ("windows",), "architecture": ("x86_64", "amd64")}
    assert [c.key for c in manifest.components] == ["detector", "embedder"]
    detector = manifest.exports[0]
    assert detector.sha256 == hashlib.sha256(DETECTOR).digest()
    assert detector.size_bytes == len(DETECTOR)
    assert detector.provenance.license == "MIT"
    assert detector.provenance.redistributable is True
    assert [v.variant_key for v in manifest.variants] == ["detector-cpu", "embedder-cpu"]


def test_weights_that_may_not_be_redistributed_are_recorded_as_such() -> None:
    assert parse(manifest_dict()).exports[1].provenance.redistributable is False


def test_bytes_are_accepted_as_well_as_text() -> None:
    assert parse_manifest(json.dumps(manifest_dict()).encode()).key == "reference-cpu"


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (["schema_version"], 2, "not supported"),
        (["schema_version"], True, "not supported"),
        (["schema_version"], 1.0, "not supported"),
        (["schema_version"], "1", "not supported"),
        (["surprise"], 1, "unexpected"),
        (["key"], _DELETE, "missing"),
        (["key"], "", "non-empty"),
        (["key"], " padded ", "non-empty"),
        (["key"], "a\x00b", "control or invisible"),
        (["version"], "1.0\n", "non-empty"),
        (["requirements", "os"], ["\u200bwindows"], "control or invisible"),
        (["components", 0, "kind"], "FACE\u202eDETECTOR", "control or invisible"),
        (["key"], 5, "non-empty"),
        (["key"], "Upper", "valid package key"),
        (["key"], "a/b", "valid package key"),
        (["key"], "a b", "valid package key"),
        (["key"], "-lead", "valid package key"),
        (["key"], "trail.", "valid package key"),
        (["key"], "nul", "valid package key"),
        (["key"], "com1.x", "valid package key"),
        (["key"], "k" * 65, "valid package key"),
        (["version"], None, "non-empty"),
        (["requirements"], [], "must be an object"),
        (["requirements", "os"], [], "non-empty list"),
        (["requirements", "os"], "windows", "non-empty list"),
        (["requirements", "os"], [""], "non-empty"),
        (["components"], [], "non-empty list"),
        (["components"], {}, "non-empty list"),
        (["components", 0, "extra"], 1, "unexpected"),
        (["components", 0, "contract"], [], "must be an object"),
        (["components", 1, "key"], "detector", "duplicate component key"),
        (["exports"], [], "non-empty list"),
        (["exports", 0, "component"], "ghost", "unknown component"),
        (["exports", 0, "sha256"], "ABC", "64 lowercase"),
        (["exports", 0, "sha256"], sha(DETECTOR).upper(), "64 lowercase"),
        (["exports", 0, "sha256"], 5, "non-empty"),
        (["exports", 0, "size_bytes"], -1, "non-negative"),
        (["exports", 0, "size_bytes"], True, "non-negative"),
        (["exports", 0, "size_bytes"], 1.5, "non-negative"),
        (["exports", 0, "provenance", "redistributable"], "yes", "true or false"),
        (["exports", 0, "provenance", "license"], _DELETE, "missing"),
        (["exports", 0, "provenance"], "MIT", "must be an object"),
        (["exports", 0, "input_contract"], [], "must be an object"),
        (["exports", 1, "file"], "MODELS/Detector.onnx", "duplicate export file"),
        (["exports", 0, "file"], "../escape.onnx", "safe relative"),
        (["exports", 1, "file"], "models/detector.onnx/inner.bin", "inside another export"),
        (["exports", 1, "file"], "MODELS/DETECTOR.ONNX/inner.bin", "inside another export"),
        (["exports", 1, "file"], "MODELS", "safe relative|inside another export"),
        (["variants"], [], "non-empty list"),
        (["variants", 0, "export_file"], "models/other.onnx", "unknown export file"),
        (["variants", 1, "variant_key"], "detector-cpu", "duplicate variant key"),
        (["variants", 0, "requirements"], [], "must be an object"),
    ],
)
def test_a_malformed_manifest_is_refused_and_says_why(
    path: list[str | int], value: Any, message: str
) -> None:
    with pytest.raises(ManifestError, match=message):
        parse(broken(path, value))


@pytest.mark.parametrize(
    ("text", "message"),
    [
        (b'{"key": "\xc3("}', "UTF-8"),
        pytest.param("[" * 200_000, "nested too deeply", id="deeply-nested"),
        ("{", "not valid JSON"),
        ("[]", "must be an object"),
        ('{"schema_version": 1, "schema_version": 1}', "duplicate key"),
        ('{"schema_version": NaN}', "NaN"),
        ('{"schema_version": Infinity}', "Infinity"),
    ],
)
def test_text_that_is_not_a_manifest_is_refused(text: str, message: str) -> None:
    with pytest.raises(ManifestError, match=message):
        parse_manifest(text)


@pytest.mark.parametrize(
    "path",
    ["models/a.onnx", "a.onnx", "deep/er/still/a.bin", "a b/c.txt", "name.with.dots/x"],
)
def test_ordinary_relative_paths_are_safe(path: str) -> None:
    assert safe_relative_path(path) == path


@pytest.mark.parametrize(
    "path",
    [
        "",
        "/etc/passwd",
        "..",
        "../x",
        "a/../b",
        "a//b",
        "./a",
        "a/.",
        "a\\b",
        "C:/x",
        "C:x",
        "a/b/",
        "trailing.dot.",
        "trailing space ",
        "dir./x",
        "con",
        "CON.txt",
        "a/nul.onnx",
        "com1",
        "lpt9.bin",
        "a\x00b",
        "a\nb",
    ],
)
def test_a_path_that_could_leave_the_package_or_be_rewritten_by_windows_is_refused(
    path: str,
) -> None:
    with pytest.raises(ManifestError):
        safe_relative_path(path)


def test_a_path_must_be_a_string() -> None:
    with pytest.raises(ManifestError):
        safe_relative_path(5)


def test_a_variant_finds_an_export_spelled_with_capitals_and_takes_the_exports_spelling() -> None:
    data = manifest_dict()
    data["exports"][0]["file"] = "Models/Detector.onnx"
    data["variants"][0]["export_file"] = "models/detector.ONNX"

    manifest = parse(data)

    assert manifest.variants[0].export_file == "Models/Detector.onnx"


def test_a_variant_finds_its_export_whatever_the_case_and_takes_the_exports_spelling() -> None:
    data = manifest_dict()
    data["variants"][0]["export_file"] = "MODELS/Detector.ONNX"

    manifest = parse(data)

    assert manifest.variants[0].export_file == "models/detector.onnx"


# --- compatibility -------------------------------------------------------------------------------


def test_a_package_for_this_machine_is_compatible() -> None:
    manifest = parse(manifest_dict())

    assert (
        incompatibilities(manifest, {"os": "Windows", "architecture": "AMD64", "ram": "16"}) == []
    )


def test_every_mismatch_is_reported() -> None:
    manifest = parse(manifest_dict())

    problems = incompatibilities(manifest, {"os": "linux", "architecture": "arm64"})

    assert len(problems) == 2
    assert "os is 'linux'" in problems[0]
    assert "architecture is 'arm64'" in problems[1]


def test_a_fact_that_is_not_known_is_a_mismatch_not_an_assumption() -> None:
    manifest = parse(manifest_dict())

    problems = incompatibilities(manifest, {"os": "windows"})

    assert problems == ["architecture is not known on this machine (package needs x86_64, amd64)"]


def test_fact_names_are_matched_without_regard_to_case() -> None:
    manifest = parse(manifest_dict())

    assert incompatibilities(manifest, {"OS": "windows", "Architecture": "x86_64"}) == []


def test_a_requirement_named_with_capitals_is_met_by_a_fact_named_without() -> None:
    data = manifest_dict()
    data["requirements"] = {"OS": ["Windows"]}

    assert incompatibilities(parse(data), {"os": "windows"}) == []


def test_a_fact_that_is_not_text_is_compared_as_text_not_a_crash() -> None:
    data = manifest_dict()
    data["requirements"] = {"cores": ["8"]}

    assert incompatibilities(parse(data), {"cores": 8}) == []  # type: ignore[dict-item]
    assert incompatibilities(parse(data), {"cores": 4})  # type: ignore[dict-item]


def test_a_package_with_no_requirements_fits_anywhere() -> None:
    data = manifest_dict()
    data["requirements"] = {}

    assert incompatibilities(parse(data), {}) == []


# --- file integrity ------------------------------------------------------------------------------


def write_package(root: Path) -> PackageManifest:
    (root / "models").mkdir(parents=True)
    (root / "models" / "detector.onnx").write_bytes(DETECTOR)
    (root / "models" / "embedder.onnx").write_bytes(EMBEDDER)
    return parse(manifest_dict())


def test_a_package_directory_that_matches_its_manifest_has_no_problems(tmp_path: Path) -> None:
    manifest = write_package(tmp_path)
    (tmp_path / "README.txt").write_text("not declared, so not part of the package")

    assert file_problems(tmp_path, manifest) == []


def test_a_missing_file_is_reported(tmp_path: Path) -> None:
    manifest = write_package(tmp_path)
    (tmp_path / "models" / "embedder.onnx").unlink()

    assert file_problems(tmp_path, manifest) == ["models/embedder.onnx: missing"]


def test_a_directory_where_a_file_belongs_is_reported_as_missing(tmp_path: Path) -> None:
    manifest = write_package(tmp_path)
    (tmp_path / "models" / "embedder.onnx").unlink()
    (tmp_path / "models" / "embedder.onnx").mkdir()

    assert file_problems(tmp_path, manifest) == ["models/embedder.onnx: missing"]


def test_a_wrong_size_is_reported_before_the_hash(tmp_path: Path) -> None:
    manifest = write_package(tmp_path)
    (tmp_path / "models" / "detector.onnx").write_bytes(DETECTOR + b"!")

    (problem,) = file_problems(tmp_path, manifest)

    assert (
        problem == f"models/detector.onnx: size {len(DETECTOR) + 1}, manifest says {len(DETECTOR)}"
    )


def test_changed_bytes_of_the_same_size_are_caught_by_the_hash(tmp_path: Path) -> None:
    manifest = write_package(tmp_path)
    (tmp_path / "models" / "detector.onnx").write_bytes(b"X" * len(DETECTOR))

    assert file_problems(tmp_path, manifest) == [
        "models/detector.onnx: hash does not match the manifest"
    ]


def test_a_declared_path_that_cannot_be_resolved_is_reported_not_raised(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = write_package(tmp_path)
    real = Path.resolve

    def resolve(self: Path, strict: bool = False) -> Path:
        if self.name == "embedder.onnx":
            raise RuntimeError("Symlink loop")
        return real(self, strict)

    monkeypatch.setattr(Path, "resolve", resolve)

    assert file_problems(tmp_path, manifest) == ["models/embedder.onnx: cannot be resolved"]


def test_a_declared_file_reached_through_a_link_out_of_the_package_is_refused(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "detector.onnx").write_bytes(DETECTOR)
    (outside / "embedder.onnx").write_bytes(EMBEDDER)
    package = tmp_path / "package"
    package.mkdir()
    link_directory(package / "models", outside)

    problems = file_problems(package, parse(manifest_dict()))

    assert problems == [
        "models/detector.onnx: resolves outside the package",
        "models/embedder.onnx: resolves outside the package",
    ]
