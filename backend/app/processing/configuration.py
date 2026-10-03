"""M3's strict command-time processing configuration resolver.

The caller supplies `ProcessingRequestV1`: explicit semantic intent, never a mutable default.
Inside the request transaction the resolver verifies the catalog selections and freezes both those
selections and the immutable catalog facts that give them meaning.  Runtime variants remain actual
execution provenance and are deliberately absent here (Persistence §13, decision 2026-10-03).
"""

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.memory.models import RepresentationSpace, RepresentationSpaceState
from backend.app.runtime.models import (
    Component,
    ComponentVersion,
    ModelExport,
    RuntimeVariant,
    RuntimeVariantRepresentationSpace,
)
from backend.app.runtime.registration import DECLARED, DETECTOR, EMBEDDER, REGISTERED, VALIDATED

SCHEMA_VERSION = 1
UNCALIBRATED = "UNCALIBRATED"
UNCALIBRATED_INTERPRETATION = "COSINE_UNCALIBRATED"


class ProcessingConfigurationError(ValueError):
    """A processing request is malformed or does not name compatible durable metadata."""


def _object(value: object, path: str, keys: set[str]) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ProcessingConfigurationError(f"{path} must be an object")
    actual = set(value)
    if actual != keys:
        raise ProcessingConfigurationError(
            f"{path} keys must be {sorted(keys)}, not {sorted(actual)}"
        )
    return value


def _uuid(value: object, path: str) -> uuid.UUID:
    if not isinstance(value, str):
        raise ProcessingConfigurationError(f"{path} must be a UUID string")
    try:
        return uuid.UUID(value)
    except ValueError:
        raise ProcessingConfigurationError(f"{path} must be a UUID string") from None


def _string(value: object, path: str) -> str:
    if not isinstance(value, str) or not value:
        raise ProcessingConfigurationError(f"{path} must be a non-empty string")
    return value


def _number(value: object, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ProcessingConfigurationError(f"{path} must be a number")
    return float(value)


def _schema_version(value: object, path: str) -> None:
    """Accept precisely the integer schema version, never Python's bool/float aliases."""
    if type(value) is not int or value != SCHEMA_VERSION:
        raise ProcessingConfigurationError(f"{path} is not supported")


@dataclass(frozen=True, slots=True)
class ExportSelection:
    component_version_id: uuid.UUID
    model_export_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class CalibrationSelection:
    mode: str
    interpretation: str
    profile_id: uuid.UUID | None


@dataclass(frozen=True, slots=True)
class ProcessingRequestV1:
    """Explicit, versioned semantic intent supplied to the M3 processing command."""

    detector: ExportSelection
    embedder: ExportSelection
    representation_space_id: uuid.UUID
    calibration: CalibrationSelection
    runtime_policy: Mapping[str, Any]
    crop_policy: Mapping[str, Any]
    quality_policy: Mapping[str, Any]
    decision_policy: Mapping[str, Any]
    command_options: Mapping[str, Any]

    @classmethod
    def parse(cls, value: object) -> "ProcessingRequestV1":
        root = _object(
            value,
            "$",
            {
                "schema_version",
                "detector",
                "embedder",
                "representation_space_id",
                "calibration",
                "runtime_policy",
                "crop_policy",
                "quality_policy",
                "decision_policy",
                "command_options",
            },
        )
        _schema_version(root["schema_version"], "$.schema_version")
        return cls(
            detector=_selection(root["detector"], "$.detector"),
            embedder=_selection(root["embedder"], "$.embedder"),
            representation_space_id=_uuid(
                root["representation_space_id"], "$.representation_space_id"
            ),
            calibration=_calibration(root["calibration"]),
            runtime_policy=_runtime_policy(root["runtime_policy"]),
            crop_policy=_versioned_policy(root["crop_policy"], "$.crop_policy"),
            quality_policy=_versioned_policy(root["quality_policy"], "$.quality_policy"),
            decision_policy=_decision_policy(root["decision_policy"]),
            command_options=_versioned_policy(root["command_options"], "$.command_options"),
        )


def _selection(value: object, path: str) -> ExportSelection:
    selected = _object(value, path, {"component_version_id", "model_export_id"})
    return ExportSelection(
        _uuid(selected["component_version_id"], f"{path}.component_version_id"),
        _uuid(selected["model_export_id"], f"{path}.model_export_id"),
    )


def _calibration(value: object) -> CalibrationSelection:
    selected = _object(value, "$.calibration", {"mode", "interpretation", "profile_id"})
    mode = _string(selected["mode"], "$.calibration.mode")
    interpretation = _string(selected["interpretation"], "$.calibration.interpretation")
    profile = selected["profile_id"]
    if mode == UNCALIBRATED:
        if interpretation != UNCALIBRATED_INTERPRETATION or profile is not None:
            raise ProcessingConfigurationError("uncalibrated selection must have no profile")
        return CalibrationSelection(mode, interpretation, None)
    raise ProcessingConfigurationError("$.calibration.mode is not supported")


def _runtime_policy(value: object) -> Mapping[str, Any]:
    policy = _object(value, "$.runtime_policy", {"allow_fallback", "providers", "schema_version"})
    _schema_version(policy["schema_version"], "$.runtime_policy.schema_version")
    providers = policy["providers"]
    if (
        not isinstance(providers, list)
        or not providers
        or any(not isinstance(p, str) or not p for p in providers)
    ):
        raise ProcessingConfigurationError("$.runtime_policy.providers must be non-empty strings")
    if not isinstance(policy["allow_fallback"], bool):
        raise ProcessingConfigurationError("$.runtime_policy.allow_fallback must be a boolean")
    return {
        "schema_version": SCHEMA_VERSION,
        "providers": providers,
        "allow_fallback": policy["allow_fallback"],
    }


def _versioned_policy(value: object, path: str) -> Mapping[str, Any]:
    policy = _object(value, path, {"schema_version"})
    _schema_version(policy["schema_version"], f"{path}.schema_version")
    return {"schema_version": SCHEMA_VERSION}


def _decision_policy(value: object) -> Mapping[str, Any]:
    policy = _object(
        value,
        "$.decision_policy",
        {
            "margin",
            "match_threshold",
            "min_detection_score",
            "new_identity_ceiling",
            "schema_version",
            "version",
        },
    )
    _schema_version(policy["schema_version"], "$.decision_policy.schema_version")
    minimum = _number(policy["min_detection_score"], "$.decision_policy.min_detection_score")
    ceiling = _number(policy["new_identity_ceiling"], "$.decision_policy.new_identity_ceiling")
    threshold = _number(policy["match_threshold"], "$.decision_policy.match_threshold")
    margin = _number(policy["margin"], "$.decision_policy.margin")
    if not 0.0 <= minimum <= 1.0 or not -1.0 <= ceiling <= threshold <= 1.0 or not 0 < margin <= 2:
        raise ProcessingConfigurationError("$.decision_policy thresholds are invalid")
    return {
        "schema_version": SCHEMA_VERSION,
        "version": _string(policy["version"], "$.decision_policy.version"),
        "min_detection_score": minimum,
        "new_identity_ceiling": ceiling,
        "match_threshold": threshold,
        "margin": margin,
    }


def resolve(session: Session, request: ProcessingRequestV1) -> dict[str, Any]:
    """Validate the requested durable catalog graph and return its canonical snapshot payload."""
    detector = _export(session, request.detector, DETECTOR, "detector")
    embedder = _export(session, request.embedder, EMBEDDER, "embedder")
    detector_variant = session.scalar(
        select(RuntimeVariant.id).where(
            RuntimeVariant.model_export_id == request.detector.model_export_id,
            RuntimeVariant.provider.in_(request.runtime_policy["providers"]),
            RuntimeVariant.state.in_((REGISTERED, VALIDATED)),
        )
    )
    if detector_variant is None:
        raise ProcessingConfigurationError(
            "the detector export has no usable variant for the requested runtime policy"
        )
    space = session.get(RepresentationSpace, request.representation_space_id)
    if space is None or space.state != RepresentationSpaceState.ACTIVE:
        raise ProcessingConfigurationError("the representation space is not ACTIVE")
    compatible = session.scalar(
        select(RuntimeVariant.id)
        .join(ModelExport, ModelExport.id == RuntimeVariant.model_export_id)
        .join(
            RuntimeVariantRepresentationSpace,
            RuntimeVariantRepresentationSpace.runtime_variant_id == RuntimeVariant.id,
        )
        .where(
            ModelExport.id == request.embedder.model_export_id,
            RuntimeVariant.provider.in_(request.runtime_policy["providers"]),
            RuntimeVariant.state.in_((REGISTERED, VALIDATED)),
            RuntimeVariantRepresentationSpace.representation_space_id == space.id,
            RuntimeVariantRepresentationSpace.state.in_((DECLARED, VALIDATED)),
        )
    )
    if compatible is None:
        raise ProcessingConfigurationError(
            "the embedder export has no usable variant for the requested space and runtime policy"
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "detector": detector,
        "embedder": embedder,
        "representation_space": {
            "id": str(space.id),
            "semantic_key": space.semantic_key,
            "dimension": space.dimension,
            "metric": space.metric,
            "normalization": space.normalization,
            "origin_component_version_id": str(space.component_version_id),
            "contract_schema_version": space.contract_schema_version,
            "contract": space.contract_json,
        },
        "calibration": {
            "mode": request.calibration.mode,
            "interpretation": request.calibration.interpretation,
            "profile": None,
        },
        "runtime_policy": dict(request.runtime_policy),
        "crop_policy": dict(request.crop_policy),
        "quality_policy": dict(request.quality_policy),
        "decision_policy": dict(request.decision_policy),
        "command_options": dict(request.command_options),
    }


def _export(
    session: Session, selection: ExportSelection, expected_kind: str, name: str
) -> dict[str, Any]:
    row = session.execute(
        select(Component, ComponentVersion, ModelExport)
        .join(ComponentVersion, ComponentVersion.component_id == Component.id)
        .join(ModelExport, ModelExport.component_version_id == ComponentVersion.id)
        .where(
            ComponentVersion.id == selection.component_version_id,
            ModelExport.id == selection.model_export_id,
        )
    ).one_or_none()
    if row is None:
        raise ProcessingConfigurationError(
            f"the {name} export does not belong to its component version"
        )
    component, version, export = row
    if component.kind != expected_kind:
        raise ProcessingConfigurationError(f"the {name} component is not {expected_kind}")
    return {
        "component": {"id": str(component.id), "key": component.key, "kind": component.kind},
        "component_version": {
            "id": str(version.id),
            "semantic_version": version.semantic_version,
            "contract_schema_version": version.contract_schema_version,
            "contract": version.contract_json,
        },
        "export": {
            "id": str(export.id),
            "format": export.format,
            "precision": export.precision,
            "sha256": export.sha256.hex(),
            "input_contract": export.input_contract_json,
        },
    }
