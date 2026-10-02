"""Runtime packages as the catalog tests need them: a valid manifest, and the files it declares.

`manifest_dict` builds a manifest for a detector and an embedder (optionally a second embedder
export) and remembers the bytes it declared, so `installed` and `package_files` can write a package
that passes every check (size, hash, directory named by its key). Nothing here is a real model.
"""

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

from backend.app.runtime.manifest import parse_manifest
from backend.app.runtime.package_store import InstalledPackage

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
CONTENT: dict[str, bytes] = {}  # sha256 hex -> the bytes `manifest_dict` declared


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
        CONTENT[hashlib.sha256(data).hexdigest()] = data
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


def package_files(base: Path, manifest: dict[str, Any]) -> Path:
    """Write `base/<key>` with its manifest and the files it declares; returns that directory."""
    directory: Path = base / manifest["key"]
    directory.mkdir(parents=True, exist_ok=True)
    for export in manifest["exports"]:
        target = directory / export["file"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(CONTENT[export["sha256"]])
    (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return directory


def installed(base: Path, manifest: dict[str, Any]) -> InstalledPackage:
    """A package as the installer leaves it, without the installer."""
    directory = package_files(base, manifest)
    parsed = parse_manifest((directory / "manifest.json").read_text(encoding="utf-8"))
    return InstalledPackage(parsed.key, parsed.version, directory, parsed)
