"""The reference-model runtime package: two ONNX files described as a package manifest (issue 69).

The weights are developer-supplied local files, never committed. This module turns a folder that
holds them into the package a `RuntimePackageStore` installs: it measures the files (size and
SHA-256, never copied from a claim), declares one CUDA and one CPU variant per model (the
preferred provider first, the CPU as the fallback), and records the provenance mandatory for every
export. Which models, from where and under what terms is the caller's record, not guessed here.
"""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DETECTOR_CONTRACT = "scrfd-letterbox-v1"
EMBEDDER_CONTRACT = "arcface-112-similarity-v1"
_PROVIDERS = (
    ("CUDAExecutionProvider", "GPU", "cuda"),
    ("CPUExecutionProvider", "CPU", "cpu"),
)


@dataclass(frozen=True, slots=True)
class ReferenceModel:
    component_key: str
    file: Path  # the ONNX file on disk
    family: str  # descriptive provenance (it is not part of a space's identity)


@dataclass(frozen=True, slots=True)
class Provenance:
    license: str
    source: str
    redistributable: bool


def reference_manifest(
    key: str,
    version: str,
    detector: ReferenceModel,
    embedder: ReferenceModel,
    *,
    dimension: int,
    provenance: Provenance,
) -> dict[str, Any]:
    """The manifest (schema 1) of a package holding `detector` and `embedder`, whose files are
    laid out under `models/` by `write_reference_package`."""

    def export(model: ReferenceModel) -> dict[str, Any]:
        data = model.file.read_bytes()
        return {
            "component": model.component_key,
            "file": f"models/{model.file.name}",
            "format": "ONNX",
            "precision": "FP32",
            "sha256": hashlib.sha256(data).hexdigest(),
            "size_bytes": len(data),
            "input_contract": {"layout": "NCHW"},
            "provenance": {
                "license": provenance.license,
                "source": provenance.source,
                "redistributable": provenance.redistributable,
            },
        }

    exports = [export(detector), export(embedder)]
    return {
        "schema_version": 1,
        "key": key,
        "version": version,
        "requirements": {},
        "components": [
            {
                "key": detector.component_key,
                "kind": "FACE_DETECTOR",
                "version": version,
                "contract": {"preprocessing_contract": DETECTOR_CONTRACT},
            },
            {
                "key": embedder.component_key,
                "kind": "FACE_REPRESENTATION",
                "version": version,
                "contract": {
                    "family": embedder.family,
                    "dimension": dimension,
                    "preprocessing_contract": EMBEDDER_CONTRACT,
                    "normalization": "L2_NORMALIZED",
                    "normalization_contract_version": "l2-v1",
                    "compatibility_version": "1",
                },
            },
        ],
        "exports": exports,
        "variants": [
            {
                "export_file": item["file"],
                "provider": provider,
                "device_kind": device,
                "variant_key": f"{item['component']}-{name}",
                "requirements": {},
            }
            for item in exports
            for provider, device, name in _PROVIDERS
        ],
    }


def write_reference_package(manifest: dict[str, Any], files: dict[str, Path], out: Path) -> Path:
    """Write `out/<key>/` with `manifest.json` and the declared files (copied from `files`, which
    maps each export's file name to where it is now); returns that directory."""
    directory: Path = out / manifest["key"]
    (directory / "models").mkdir(parents=True, exist_ok=True)
    for export in manifest["exports"]:
        (directory / export["file"]).write_bytes(files[Path(export["file"]).name].read_bytes())
    (directory / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return directory
