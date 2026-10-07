"""The development profile: a fake catalog, fake perception and an uncalibrated decision policy, so
the whole application can be exercised before real models are cleared (M4 plan decision 1; the
weights are blocked on issue 69). It is **not** a release configuration.

Nothing here is on by default: the sidecar host enables it only with `--development-profile`.
What it does, honestly labelled:

* it registers a small catalog (a detector, an embedder and one representation space) once, in the
  library's own database, as ordinary rows whose exports point at no real model;
* its "perception" finds one face in the middle of every image and embeds it as a vector derived
  from the image's pixels, so identical images are the same identity and different images are not;
* its decision policy has a visibly provisional version name and thresholds chosen only so that
  those two cases separate; every run frozen under it reports `calibrated: false` (the snapshot
  says `UNCALIBRATED`), which is what the UI shows as the uncalibrated-policy notice.

Real calibration is TST-044; real models are issue 69.
"""

import hashlib
import os
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Final

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.api.library_profile import LibraryProfile
from backend.api.startup import (
    PROVISIONAL_MAX_PIXELS,
    LibrarySettings,
    ProcessingSettings,
    ProcessingUnavailableError,
)
from backend.app.lifecycle import OpenLibrary
from backend.app.memory.models import RepresentationSpace
from backend.app.runtime.models import (
    Component,
    ComponentVersion,
    ModelExport,
    RuntimeVariant,
    RuntimeVariantRepresentationSpace,
)
from backend.app.runtime.perception_client import Detected, FaceVector, Represented
from backend.app.runtime.registration import DETECTOR, EMBEDDER
from backend.app.runtime.worker_config import PerceptionPlan, PlannedVariant
from backend.app.sources.models import Artifact
from backend.ml.contracts.messages import Detection

DETECTOR_KEY: Final = "development-face-detector"
EMBEDDER_KEY: Final = "development-face-embedder"
SPACE_KEY: Final = "development-pixel-hash-embedding-v1"
POLICY_VERSION: Final = "development-uncalibrated-v1"
PROVIDER: Final = "CPUExecutionProvider"
DIMENSION: Final = 64  # enough that unrelated images are far apart (cosine near 0)

_VERSION: Final = "0.0.0-development"


@dataclass(frozen=True, slots=True)
class DevelopmentCatalog:
    detector_version_id: uuid.UUID
    detector_export_id: uuid.UUID
    embedder_version_id: uuid.UUID
    embedder_export_id: uuid.UUID
    space_id: uuid.UUID


# --- the catalog ----------------------------------------------------------------------------


def register_development_catalog(
    library: OpenLibrary,
    clock: Callable[[], datetime],
    new_id: Callable[[], uuid.UUID],
) -> DevelopmentCatalog:
    """Register the catalog if it is not there yet (safe to repeat on every start)."""
    return library.unit_of_work.write(lambda session: _register(session, clock(), new_id))


def _register(
    session: Session, now: datetime, new_id: Callable[[], uuid.UUID]
) -> DevelopmentCatalog:
    existing = _find(session)
    if existing is not None:
        return existing
    detector_version, detector_export, _ = _component(
        session, now, new_id, DETECTOR_KEY, DETECTOR, "development-detector-v1"
    )
    embedder_version, embedder_export, embedder_variant = _component(
        session, now, new_id, EMBEDDER_KEY, EMBEDDER, "development-embedder-v1"
    )
    space = RepresentationSpace(
        id=new_id(),
        semantic_key=SPACE_KEY,
        state="ACTIVE",
        dimension=DIMENSION,
        metric="COSINE",
        normalization="L2_NORMALIZED",
        component_version_id=embedder_version,
        contract_schema_version=1,
        contract_json={"development": True},
        created_at=now,
    )
    session.add(space)
    session.flush()
    session.add(
        RuntimeVariantRepresentationSpace(
            runtime_variant_id=embedder_variant,
            representation_space_id=space.id,
            validation_json={},
            state="DECLARED",
        )
    )
    session.flush()
    return DevelopmentCatalog(
        detector_version, detector_export, embedder_version, embedder_export, space.id
    )


def _component(
    session: Session,
    now: datetime,
    new_id: Callable[[], uuid.UUID],
    key: str,
    kind: str,
    contract: str,
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """A component, its version, an export (pointing at no real model) and a CPU variant."""
    component = Component(
        id=new_id(), key=key, kind=kind, display_name=f"{key} (development)", state="ACTIVE"
    )
    version = ComponentVersion(
        id=new_id(),
        component_id=component.id,
        semantic_version=_VERSION,
        contract_schema_version=1,
        contract_json={"development": True},
        created_at=now,
    )
    # A referenced artifact whose file exists (this module), so startup never reports it missing.
    artifact = Artifact(
        id=new_id(),
        kind="MODEL_EXPORT",
        storage_mode="REFERENCED",
        external_path=str(Path(__file__).resolve()),
        state="AVAILABLE",
        created_at=now,
    )
    session.add_all([component, artifact])
    session.flush()
    session.add(version)
    session.flush()
    export = ModelExport(
        id=new_id(),
        component_version_id=version.id,
        format="DEVELOPMENT",
        precision="FP32",
        artifact_id=artifact.id,
        sha256=hashlib.sha256(key.encode()).digest(),
        input_contract_json={"contract": contract},
        created_at=now,
    )
    session.add(export)
    session.flush()
    variant = RuntimeVariant(
        id=new_id(),
        model_export_id=export.id,
        provider=PROVIDER,
        device_kind="CPU",
        variant_key="cpu",
        requirements_json={},
        state="REGISTERED",
    )
    session.add(variant)
    session.flush()
    return version.id, export.id, variant.id


def _find(session: Session) -> DevelopmentCatalog | None:
    def export_of(key: str) -> tuple[uuid.UUID, uuid.UUID] | None:
        row = session.execute(
            select(ComponentVersion.id, ModelExport.id)
            .join(Component, Component.id == ComponentVersion.component_id)
            .join(ModelExport, ModelExport.component_version_id == ComponentVersion.id)
            .where(Component.key == key)
        ).first()
        return None if row is None else (row[0], row[1])

    detector, embedder = export_of(DETECTOR_KEY), export_of(EMBEDDER_KEY)
    space = session.scalar(
        select(RepresentationSpace.id).where(RepresentationSpace.semantic_key == SPACE_KEY)
    )
    if detector is None or embedder is None or space is None:
        return None
    return DevelopmentCatalog(detector[0], detector[1], embedder[0], embedder[1], space)


# --- the request, the plan and the perception -----------------------------------------------


def development_request(session: Session) -> dict[str, Any]:
    """The `ProcessingRequestV1` a process command runs under: the registered catalog, the CPU
    provider, and the development decision policy (uncalibrated)."""
    catalog = _find(session)
    if catalog is None:
        raise ProcessingUnavailableError("the development catalog is not registered")
    return {
        "schema_version": 1,
        "detector": {
            "component_version_id": str(catalog.detector_version_id),
            "model_export_id": str(catalog.detector_export_id),
        },
        "embedder": {
            "component_version_id": str(catalog.embedder_version_id),
            "model_export_id": str(catalog.embedder_export_id),
        },
        "representation_space_id": str(catalog.space_id),
        "calibration": {
            "mode": "UNCALIBRATED",
            "interpretation": "COSINE_UNCALIBRATED",
            "profile_id": None,
        },
        "runtime_policy": {
            "schema_version": 1,
            "providers": [PROVIDER],
            "allow_fallback": False,
        },
        "crop_policy": {"schema_version": 1},
        "quality_policy": {"schema_version": 1},
        "decision_policy": {
            "schema_version": 1,
            "version": POLICY_VERSION,
            "min_detection_score": 0.1,
            "new_identity_ceiling": 0.5,
            "match_threshold": 0.9,
            "margin": 0.1,
        },
        "command_options": {"schema_version": 1},
    }


def development_plan(
    session: Session,
    store: object,
    *,
    detector_component_version_id: uuid.UUID,
    representation_space_id: uuid.UUID,
    providers: Sequence[str],
    detector_model_export_id: uuid.UUID | None = None,
    embedder_model_export_id: uuid.UUID | None = None,
) -> PerceptionPlan:
    """The plan for the development catalog (it has no package on disk to read)."""
    assert detector_model_export_id is not None
    assert embedder_model_export_id is not None
    space = session.get(RepresentationSpace, representation_space_id)
    assert space is not None
    return PerceptionPlan(
        representation_space_id,
        space.dimension,
        (_planned(session, detector_component_version_id, detector_model_export_id, DETECTOR),),
        (_planned(session, space.component_version_id, embedder_model_export_id, EMBEDDER),),
    )


def _planned(
    session: Session, version_id: uuid.UUID, export_id: uuid.UUID, kind: str
) -> PlannedVariant:
    export = session.get(ModelExport, export_id)
    assert export is not None
    variant = session.scalars(
        select(RuntimeVariant).where(RuntimeVariant.model_export_id == export_id)
    ).one()
    return PlannedVariant(
        component_version_id=version_id,
        runtime_variant_id=variant.id,
        kind=kind,
        contract=export.input_contract_json["contract"],
        provider=variant.provider,
        device=variant.device_kind,
        package_key="development",
        model_path=Path("development"),
        sha256=export.sha256,
    )


class DevelopmentPerception:
    """One face in the middle of every image, embedded as a vector derived from its pixels."""

    def __init__(self, plan: PerceptionPlan) -> None:
        self._detector = plan.detector[0]
        self._embedder = plan.embedder[0]
        self._dimension = plan.dimension

    def detect(self, pixels: Any) -> Detected:
        return Detected((Detection(0, 0, (0.2, 0.2, 0.8, 0.8), 0.9, None),), self._detector)

    def represent(self, pixels: Any, detections: tuple[Detection, ...]) -> Represented:
        if not detections:
            return Represented((), None)  # nothing to represent: no variant ran
        digest = hashlib.sha256(np.ascontiguousarray(pixels).tobytes()).digest()
        rng = np.random.default_rng(int.from_bytes(digest[:8], "big"))
        vector = rng.standard_normal(self._dimension).astype("<f4")
        vector /= np.linalg.norm(vector)
        faces = tuple(FaceVector(d.detection_index, vector, "L2_NORMALIZED") for d in detections)
        return Represented(faces, self._embedder, ())


def development_processing(settings: LibrarySettings) -> ProcessingSettings:
    """The processing configuration the host uses under `--development-profile`. The limits are
    provisional (unmeasured), like the host's other operating limits."""

    def prepare(library: OpenLibrary) -> None:
        register_development_catalog(library, settings.clock, settings.new_id)

    return ProcessingSettings(
        client_for=DevelopmentPerception,
        request_for=development_request,
        max_pixels=PROVISIONAL_MAX_PIXELS,
        recognition_k=5,
        lease_for=timedelta(minutes=10),
        idle_seconds=2.0,
        owner=f"sidecar-{os.getpid()}",
        planner=development_plan,
        prepare=prepare,
        profile=LibraryProfile.DEVELOPMENT,
    )
