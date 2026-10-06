"""One complete, valid `ProcessingRequestV1` over a freshly registered fake catalog."""

from typing import Any

from backend.app.runtime.models import (
    ModelExport,
    RuntimeVariant,
    RuntimeVariantRepresentationSpace,
)
from tests.factories.models import ModelFactory


def processing_request(build: ModelFactory) -> dict[str, Any]:
    """One complete M3 request whose catalog selections exist and are compatible."""
    detector_version = build.component_version("FACE_DETECTOR")
    embedder_version = build.component_version("FACE_REPRESENTATION")
    detector_export = build.add(
        ModelExport(
            id=build.new_id(),
            component_version_id=detector_version.id,
            format="ONNX",
            precision="FP32",
            artifact_id=build.artifact(kind="MODEL_EXPORT").id,
            sha256=b"d" * 32,
            input_contract_json={"contract": "scrfd-letterbox-v1"},
            created_at=build.clock(),
        )
    )
    build.add(
        RuntimeVariant(
            id=build.new_id(),
            model_export_id=detector_export.id,
            provider="CPUExecutionProvider",
            device_kind="CPU",
            variant_key="cpu",
            requirements_json={},
            state="REGISTERED",
        )
    )
    embedder_export = build.add(
        ModelExport(
            id=build.new_id(),
            component_version_id=embedder_version.id,
            format="ONNX",
            precision="FP32",
            artifact_id=build.artifact(kind="MODEL_EXPORT").id,
            sha256=b"e" * 32,
            input_contract_json={"contract": "arcface-112-similarity-v1"},
            created_at=build.clock(),
        )
    )
    space = build.representation_space(component_version_id=embedder_version.id)
    variant = build.add(
        RuntimeVariant(
            id=build.new_id(),
            model_export_id=embedder_export.id,
            provider="CPUExecutionProvider",
            device_kind="CPU",
            variant_key="cpu",
            requirements_json={},
            state="REGISTERED",
        )
    )
    build.add(
        RuntimeVariantRepresentationSpace(
            runtime_variant_id=variant.id,
            representation_space_id=space.id,
            validation_json={},
            state="DECLARED",
        )
    )
    return {
        "schema_version": 1,
        "detector": {
            "component_version_id": str(detector_version.id),
            "model_export_id": str(detector_export.id),
        },
        "embedder": {
            "component_version_id": str(embedder_version.id),
            "model_export_id": str(embedder_export.id),
        },
        "representation_space_id": str(space.id),
        "calibration": {
            "mode": "UNCALIBRATED",
            "interpretation": "COSINE_UNCALIBRATED",
            "profile_id": None,
        },
        "runtime_policy": {
            "schema_version": 1,
            "providers": ["CPUExecutionProvider"],
            "allow_fallback": False,
        },
        "crop_policy": {"schema_version": 1},
        "quality_policy": {"schema_version": 1},
        "decision_policy": {
            "schema_version": 1,
            "version": "m3-fixture-v1",
            "min_detection_score": 0.1,
            "new_identity_ceiling": 0.2,
            "match_threshold": 0.8,
            "margin": 0.1,
        },
        "command_options": {"schema_version": 1},
    }
