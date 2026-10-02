"""A valid runtime package on disk, for tests of the installer."""

import hashlib
import json
from pathlib import Path
from typing import Any

DETECTOR = b"detector weights"
EMBEDDER = b"embedder weights"
FACTS = {"os": "windows", "architecture": "amd64"}


def manifest_for(key: str = "reference-cpu", *, detector: bytes = DETECTOR) -> dict[str, Any]:
    def export(component: str, file: str, data: bytes) -> dict[str, Any]:
        return {
            "component": component,
            "file": file,
            "format": "ONNX",
            "precision": "FP32",
            "sha256": hashlib.sha256(data).hexdigest(),
            "size_bytes": len(data),
            "input_contract": {},
            "provenance": {"license": "MIT", "source": "local fixture", "redistributable": False},
        }

    def variant(file: str, name: str) -> dict[str, Any]:
        return {
            "export_file": file,
            "provider": "CPUExecutionProvider",
            "device_kind": "CPU",
            "variant_key": name,
            "requirements": {},
        }

    return {
        "schema_version": 1,
        "key": key,
        "version": "1.0.0",
        "requirements": {"os": ["windows"], "architecture": ["x86_64", "amd64"]},
        "components": [
            {"key": "detector", "kind": "FACE_DETECTOR", "version": "1.0.0", "contract": {}},
            {"key": "embedder", "kind": "FACE_REPRESENTATION", "version": "1.0.0", "contract": {}},
        ],
        "exports": [
            export("detector", "models/detector.onnx", detector),
            export("embedder", "models/embedder.onnx", EMBEDDER),
        ],
        "variants": [
            variant("models/detector.onnx", "detector-cpu"),
            variant("models/embedder.onnx", "embedder-cpu"),
        ],
    }


def build_package(
    directory: Path, key: str = "reference-cpu", *, detector: bytes = DETECTOR
) -> Path:
    """Write a package (its manifest and the files it declares) into `directory`."""
    (directory / "models").mkdir(parents=True)
    (directory / "models" / "detector.onnx").write_bytes(detector)
    (directory / "models" / "embedder.onnx").write_bytes(EMBEDDER)
    (directory / "manifest.json").write_text(
        json.dumps(manifest_for(key, detector=detector)), encoding="utf-8"
    )
    return directory
