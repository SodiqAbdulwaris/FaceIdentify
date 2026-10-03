"""Writing a run's private output in the detector-then-embedder order.

A processing run's detections and vectors are private and discardable until the run is accepted
(Persistence 5, 6.2, 30): they are `PENDING` rows of exactly one run, absent from the global index.
`write_observation` is called as soon as detection settles; `write_representation` is called only
after embedding settles. This preserves a PENDING observation when embedding fails or is interrupted
(Persistence 5 and 30). Together they are the only writers of this output. Each records what the
client produced (`PerceptionClient`) and **what actually produced it** (decision 2026-10-03, issue
88): the observation carries the detector variant that executed and the representation the embedder
variant that executed, each a foreign key to the catalog (variant, then export, then component
version), never the configured or preferred one. A variant that was not what the plan named is the
client's refusal (`PerceptionClient` checks the worker's own provenance); the writer checks the
catalog agrees with it.

Checked before anything is stored (Persistence 6.2: "validate the exact dimension, finite values,
and normalization required by the RepresentationSpace contract"):

* the vector is the space's dimension, finite, and of the space's normalization (an
  `L2_NORMALIZED` vector has unit length to within `UNIT_LENGTH_TOLERANCE`);
* the detector variant is a face detector and the embedder variant a face representation component,
  and each variant's export belongs to the component version the output names (so an observation's
  `detector_component_version_id` and variant cannot disagree);
* the embedder variant is declared or validated for the space (a vector from a variant the library
  never said could produce this space does not enter it).

The JSON columns the spec left undefined (Persistence 5, decision 2026-09-23) get a small versioned
shape here: `landmarks_json` is `{"schema_version": 1, "points": [[x, y], ...]}` in the normalised
coordinates the worker returned; an observation's `quality_json` is `{"schema_version": 1,
"detection_score": s}`; a representation's is `{"schema_version": 1, "l2_norm": n}`.

Like the other repositories it joins the caller's transaction and never commits. `sequence_in_run`
is the caller's (the schema makes it unique within a run, which is what makes a replayed write
refuse instead of duplicate).
"""

import math
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.memory.models import (
    Observation,
    ObservationState,
    Representation,
    RepresentationSpace,
    RepresentationState,
)
from backend.app.processing.models import (
    ExecutionSegment,
    ExecutionSegmentState,
    ProcessingRun,
    ProcessingRunState,
)
from backend.app.runtime.models import (
    Component,
    ComponentVersion,
    ModelExport,
    RuntimeVariant,
    RuntimeVariantRepresentationSpace,
)
from backend.app.runtime.perception_client import FaceVector
from backend.app.runtime.registration import DECLARED, DETECTOR, EMBEDDER, VALIDATED
from backend.app.runtime.worker_config import PlannedVariant
from backend.ml.contracts.messages import Detection

SCHEMA_VERSION = 1
UNIT_LENGTH_TOLERANCE = 1e-3  # float32 round trips and the worker's own normalisation


class PendingOutputError(ValueError):
    """The output cannot be recorded as it is: nothing was written."""


@dataclass(frozen=True, slots=True)
class WrittenObservation:
    observation_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class WrittenRepresentation:
    representation_id: uuid.UUID


def _check_provenance(session: Session, variant: PlannedVariant, kind: str, what: str) -> uuid.UUID:
    """The variant's catalog row, checked: of the right kind and of the component version the
    output names. Returns the variant id."""
    if variant.kind != kind:
        raise PendingOutputError(f"the {what} is a {variant.kind} variant, not a {kind}")
    catalog = session.execute(
        select(ModelExport.component_version_id, Component.kind)
        .join(RuntimeVariant, RuntimeVariant.model_export_id == ModelExport.id)
        .join(ComponentVersion, ComponentVersion.id == ModelExport.component_version_id)
        .join(Component, Component.id == ComponentVersion.component_id)
        .where(RuntimeVariant.id == variant.runtime_variant_id)
    ).one_or_none()
    if catalog is None:
        raise PendingOutputError(
            f"the {what} variant {variant.runtime_variant_id} is not in the catalog"
        )
    component_version_id, catalog_kind = catalog
    if catalog_kind != kind:
        raise PendingOutputError(
            f"the {what} variant's catalog component is {catalog_kind}, not {kind}"
        )
    if component_version_id != variant.component_version_id:
        raise PendingOutputError(
            f"the {what} variant belongs to component version {component_version_id}, not "
            f"{variant.component_version_id}"
        )
    return variant.runtime_variant_id


def _check_vector(vector: FaceVector, space: RepresentationSpace) -> float:
    """The vector's length, finiteness and normalisation against the space; returns its L2 norm."""
    values = vector.vector
    if not isinstance(values, np.ndarray):
        raise PendingOutputError("a vector must be a NumPy array")
    if values.dtype != np.dtype("<f4"):
        raise PendingOutputError("a vector must be little-endian float32")
    if not values.flags.c_contiguous:
        raise PendingOutputError("a vector must be contiguous")
    if values.shape != (space.dimension,):
        raise PendingOutputError(
            f"a vector of shape {values.shape}, the space has dimension {space.dimension}"
        )
    if not np.isfinite(values).all():
        raise PendingOutputError("a vector must be finite (no NaN or infinity)")
    if vector.normalization != space.normalization:
        raise PendingOutputError(
            f"a {vector.normalization} vector, the space is {space.normalization}"
        )
    norm = float(np.linalg.norm(values))
    if space.normalization == "L2_NORMALIZED" and not math.isclose(
        norm, 1.0, abs_tol=UNIT_LENGTH_TOLERANCE
    ):
        raise PendingOutputError(f"an L2_NORMALIZED vector of length {norm}")
    return norm


def _check_context(
    session: Session,
    *,
    source_id: uuid.UUID,
    processing_run_id: uuid.UUID,
    execution_segment_id: uuid.UUID,
) -> None:
    """The output belongs to one source, running run and running segment before it is written."""
    run = session.get(ProcessingRun, processing_run_id)
    if run is None:
        raise PendingOutputError(f"no processing run {processing_run_id}")
    if run.source_id != source_id:
        raise PendingOutputError("the source does not belong to the processing run")
    if run.state != ProcessingRunState.RUNNING:
        raise PendingOutputError(f"the processing run is {run.state}, not writable")
    segment = session.get(ExecutionSegment, execution_segment_id)
    if segment is None:
        raise PendingOutputError(f"no execution segment {execution_segment_id}")
    if segment.processing_run_id != run.id:
        raise PendingOutputError("the execution segment does not belong to the processing run")
    if segment.state != ExecutionSegmentState.RUNNING:
        raise PendingOutputError(f"the execution segment is {segment.state}, not writable")


def write_observation(
    session: Session,
    *,
    source_id: uuid.UUID,
    processing_run_id: uuid.UUID,
    execution_segment_id: uuid.UUID,
    sequence_in_run: int,
    detection: Detection,
    detector: PlannedVariant,
    new_id: Callable[[], uuid.UUID],
    now: datetime,
) -> WrittenObservation:
    """Persist one detector result as a PENDING observation before embedding begins."""
    _check_context(
        session,
        source_id=source_id,
        processing_run_id=processing_run_id,
        execution_segment_id=execution_segment_id,
    )
    detector_variant = _check_provenance(session, detector, DETECTOR, "detector")
    x0, y0, x1, y1 = detection.box
    observation = Observation(
        id=new_id(),
        source_id=source_id,
        processing_run_id=processing_run_id,
        execution_segment_id=execution_segment_id,
        state=ObservationState.PENDING,
        sequence_in_run=sequence_in_run,
        bbox_x=x0,
        bbox_y=y0,
        bbox_width=x1 - x0,  # (the worker's box is inside the image, so x + width <= 1 holds)
        bbox_height=y1 - y0,
        landmarks_json=_landmarks(detection),
        quality_json={"schema_version": SCHEMA_VERSION, "detection_score": detection.score},
        detector_component_version_id=detector.component_version_id,
        runtime_variant_id=detector_variant,
        created_at=now,
    )
    session.add(observation)
    session.flush()
    return WrittenObservation(observation.id)


def write_representation(
    session: Session,
    *,
    observation_id: uuid.UUID,
    detection_index: int,
    vector: FaceVector,
    embedder: PlannedVariant,
    representation_space_id: uuid.UUID,
    new_id: Callable[[], uuid.UUID],
    now: datetime,
) -> WrittenRepresentation:
    """Persist one settled embedding for a PENDING observation.

    The caller's transient mapping from detector index to observation id is retained until this
    function verifies the returned vector's index. The durable row deliberately does not treat a
    per-request detector index as provenance; `sequence_in_run` is an idempotent run sequence.
    """
    observation = session.get(Observation, observation_id)
    if observation is None:
        raise PendingOutputError(f"no observation {observation_id}")
    if observation.state != ObservationState.PENDING:
        raise PendingOutputError(f"the observation is {observation.state}, not writable")
    _check_context(
        session,
        source_id=observation.source_id,
        processing_run_id=observation.processing_run_id,
        execution_segment_id=observation.execution_segment_id,
    )
    space = session.get(RepresentationSpace, representation_space_id)
    if space is None:
        raise PendingOutputError(f"no representation space {representation_space_id}")
    embedder_variant = _check_provenance(session, embedder, EMBEDDER, "embedder")
    compatible = session.scalar(
        select(RuntimeVariantRepresentationSpace.state).where(
            RuntimeVariantRepresentationSpace.runtime_variant_id == embedder_variant,
            RuntimeVariantRepresentationSpace.representation_space_id == space.id,
        )
    )
    if compatible not in (DECLARED, VALIDATED):
        raise PendingOutputError(
            f"the embedder variant is not declared for representation space {space.id}"
        )
    norm = _check_vector(vector, space)
    if vector.detection_index != detection_index:
        raise PendingOutputError("the vector does not belong to this observation")
    representation = Representation(
        id=new_id(),
        observation_id=observation.id,
        processing_run_id=observation.processing_run_id,
        execution_segment_id=observation.execution_segment_id,
        representation_space_id=space.id,
        state=RepresentationState.PENDING,
        vector=vector.vector.tobytes(),
        vector_dimension=space.dimension,
        quality_json={"schema_version": SCHEMA_VERSION, "l2_norm": norm},
        runtime_variant_id=embedder_variant,
        created_at=now,
    )
    session.add(representation)
    session.flush()
    return WrittenRepresentation(representation.id)


def _landmarks(detection: Detection) -> dict[str, Any] | None:
    if detection.landmarks is None:
        return None
    return {
        "schema_version": SCHEMA_VERSION,
        "points": [[x, y] for x, y in detection.landmarks],
    }
