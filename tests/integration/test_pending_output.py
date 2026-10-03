"""The writer of a run's PENDING output (M3 step 7; Persistence 5, 6.2; GitHub issue 88).

Real SQLite and a real catalog (a fixture package registered the way an installed one is). Proved
here: an observation and its representation are recorded `PENDING` with the geometry, the vector's
exact bytes and the variants that actually produced them, the provenance chain resolves to the
component versions, and anything that does not stand up (a vector that does not fit its space, a
variant that is not what the output says, an embedder the library never declared for the space) is
refused with nothing written.
"""

import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.memory.models import (
    Observation,
    ObservationState,
    Representation,
    RepresentationState,
)
from backend.app.processing.pending_output import (
    SCHEMA_VERSION,
    UNIT_LENGTH_TOLERANCE,
    PendingOutputError,
    write_face,
)
from backend.app.runtime.models import (
    ModelExport,
    RuntimeVariant,
    RuntimeVariantRepresentationSpace,
)
from backend.app.runtime.perception_client import FaceVector
from backend.app.runtime.registration import RegisteredExport, register_package
from backend.app.runtime.worker_config import PlannedVariant
from backend.ml.contracts.messages import Detection
from tests.factories.models import ModelFactory
from tests.fixtures.catalog_packages import installed, manifest_dict
from tests.fixtures.deterministic import FrozenClock, SeededUUIDs

DIMENSION = 512
LANDMARKS = ((0.3, 0.3), (0.7, 0.3), (0.5, 0.5), (0.3, 0.7), (0.7, 0.7))


def planned(export: RegisteredExport, provider: str = "CPUExecutionProvider") -> PlannedVariant:
    (variant_id,) = export.variant_ids.values()
    return PlannedVariant(
        component_version_id=export.component_version_id,
        runtime_variant_id=variant_id,
        kind=export.kind,
        contract="a-contract",
        provider=provider,
        device="CPU",
        package_key="pkg",
        model_path=Path("model.onnx"),
        sha256=b"\x00" * 32,
    )


class World:
    def __init__(
        self, session: Session, tmp_path: Path, new_id: SeededUUIDs, clock: FrozenClock
    ) -> None:
        self.session = session
        self.new_id = new_id
        self.clock = clock
        self.build = ModelFactory(session, clock, new_id)
        package = register_package(
            session,
            installed(tmp_path / "package", manifest_dict("pkg")),
            new_id=new_id,
            clock=clock,
        )
        by_kind = {export.kind: export for export in package.exports}
        self.detector = planned(by_kind["FACE_DETECTOR"])
        self.embedder = planned(by_kind["FACE_REPRESENTATION"])
        assert by_kind["FACE_REPRESENTATION"].representation_space_id is not None
        self.space_id = by_kind["FACE_REPRESENTATION"].representation_space_id
        self.run = self.build.run()
        self.segment = self.build.segment(self.run)
        session.flush()

    def vector(self, **kw: Any) -> FaceVector:
        values = np.random.default_rng(5).standard_normal(DIMENSION).astype(np.float32)
        values /= np.linalg.norm(values)
        fields: dict[str, Any] = dict(
            detection_index=0, vector=values, normalization="L2_NORMALIZED"
        )
        return FaceVector(**(fields | kw))

    def write(self, sequence: int = 0, **kw: Any) -> Any:
        detection = Detection(0, 0, (0.2, 0.25, 0.6, 0.85), 0.93, LANDMARKS)
        arguments: dict[str, Any] = dict(
            source_id=self.run.source_id, processing_run_id=self.run.id,
            execution_segment_id=self.segment.id, sequence_in_run=sequence, detection=detection,
            detector=self.detector, vector=self.vector(), embedder=self.embedder,
            representation_space_id=self.space_id, new_id=self.new_id, now=self.clock(),
        )  # fmt: skip
        return write_face(self.session, **(arguments | kw))

    def counts(self) -> tuple[int, int]:
        observations = self.session.scalar(select(func.count()).select_from(Observation))
        representations = self.session.scalar(select(func.count()).select_from(Representation))
        assert observations is not None
        assert representations is not None
        return observations, representations


@pytest.fixture
def world(db_session: Session, tmp_path: Path, new_id: SeededUUIDs, clock: FrozenClock) -> World:
    return World(db_session, tmp_path, new_id, clock)


# --- what is written ---------------------------------------------------------------------------


def test_a_face_is_recorded_pending_with_its_geometry_vector_and_the_variants_that_made_it(
    world: World,
) -> None:
    vector = world.vector()
    written = world.write(vector=vector)

    observation = world.session.get(Observation, written.observation_id)
    representation = world.session.get(Representation, written.representation_id)
    assert observation is not None
    assert representation is not None
    assert observation.state == ObservationState.PENDING
    assert (observation.bbox_x, observation.bbox_y) == (0.2, 0.25)
    assert observation.bbox_width == pytest.approx(0.4)
    assert observation.bbox_height == pytest.approx(0.6)
    assert observation.landmarks_json == {
        "schema_version": SCHEMA_VERSION,
        "points": [list(point) for point in LANDMARKS],
    }
    assert observation.quality_json == {"schema_version": SCHEMA_VERSION, "detection_score": 0.93}
    assert observation.sequence_in_run == 0
    assert observation.source_id == world.run.source_id
    assert observation.processing_run_id == world.run.id
    assert observation.execution_segment_id == world.segment.id
    assert observation.detector_component_version_id == world.detector.component_version_id
    assert observation.runtime_variant_id == world.detector.runtime_variant_id
    assert observation.superseded_by_run_id is None

    assert representation.state == RepresentationState.PENDING
    assert representation.observation_id == observation.id
    assert representation.representation_space_id == world.space_id
    assert representation.vector == np.asarray(vector.vector, dtype="<f4").tobytes()
    assert representation.vector_dimension == DIMENSION
    assert representation.ann_key is None  # not ANN-eligible until accepted
    assert representation.identity_id is None
    assert representation.runtime_variant_id == world.embedder.runtime_variant_id
    assert representation.quality_json is not None
    assert representation.quality_json["schema_version"] == SCHEMA_VERSION
    assert representation.quality_json["l2_norm"] == pytest.approx(1.0, abs=1e-5)
    assert representation.processing_run_id == world.run.id
    assert representation.execution_segment_id == world.segment.id


def test_the_provenance_chain_resolves_to_the_component_versions_that_ran(world: World) -> None:
    written = world.write()
    for output_id, model, expected in (
        (written.observation_id, Observation, world.detector.component_version_id),
        (written.representation_id, Representation, world.embedder.component_version_id),
    ):
        resolved = world.session.scalar(
            select(ModelExport.component_version_id)
            .join(RuntimeVariant, RuntimeVariant.model_export_id == ModelExport.id)
            .join(model, model.runtime_variant_id == RuntimeVariant.id)
            .where(model.id == output_id)
        )
        assert resolved == expected


def test_a_box_that_reaches_the_edge_of_the_image_satisfies_the_geometry_check(
    world: World,
) -> None:
    detection = Detection(0, 0, (0.3, 0.1, 1.0, 1.0), 0.9, None)
    written = world.write(detection=detection)
    observation = world.session.get(Observation, written.observation_id)
    assert observation is not None
    assert observation.bbox_x + observation.bbox_width <= 1.0
    assert observation.bbox_y + observation.bbox_height <= 1.0
    assert observation.bbox_width == pytest.approx(0.7)


def test_a_detection_without_landmarks_leaves_them_null(world: World) -> None:
    written = world.write(detection=Detection(0, 0, (0.1, 0.1, 0.5, 0.5), 0.9, None))
    observation = world.session.get(Observation, written.observation_id)
    assert observation is not None
    assert observation.landmarks_json is None


def test_faces_of_one_run_take_their_sequence_numbers_and_a_replayed_one_is_refused(
    world: World,
) -> None:
    first, second = world.write(0), world.write(1)
    assert first.observation_id != second.observation_id
    assert world.counts() == (2, 2)
    with pytest.raises(IntegrityError, match="sequence_in_run"):
        world.write(1)  # (the schema makes a replayed write refuse, not duplicate)


# --- what is refused, and nothing is written ----------------------------------------------------


def refused(world: World, match: str, **kw: Any) -> None:
    before = world.counts()
    with pytest.raises(PendingOutputError, match=match):
        world.write(**kw)
    assert world.counts() == before


def test_a_vector_of_the_wrong_length_is_refused(world: World) -> None:
    refused(world, "shape", vector=world.vector(vector=np.ones(DIMENSION - 1, np.float32)))


@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
def test_a_vector_that_is_not_finite_is_refused(world: World, bad: float) -> None:
    values = np.ones(DIMENSION, np.float32)
    values[3] = bad
    refused(world, "finite", vector=world.vector(vector=values))


def test_a_vector_of_another_normalisation_than_the_spaces_is_refused(world: World) -> None:
    refused(world, "L2_NORMALIZED", vector=world.vector(normalization="UNIT_BALL"))


@pytest.mark.parametrize("scale", [0.5, 0.998, 1.002, 2.0])
def test_an_l2_normalised_vector_that_is_not_unit_length_is_refused(
    world: World, scale: float
) -> None:
    values = world.vector().vector * np.float32(scale)
    refused(world, "length", vector=world.vector(vector=values))


def test_a_vector_just_inside_the_tolerance_is_accepted_and_its_length_is_kept(
    world: World,
) -> None:
    assert UNIT_LENGTH_TOLERANCE == 1e-3
    values = world.vector().vector * np.float32(1.0004)
    written = world.write(vector=world.vector(vector=values))
    representation = world.session.get(Representation, written.representation_id)
    assert representation is not None
    assert representation.quality_json is not None
    assert representation.quality_json["l2_norm"] == pytest.approx(1.0004, abs=1e-5)


def test_an_unknown_representation_space_is_refused(world: World) -> None:
    refused(world, "no representation space", representation_space_id=uuid.uuid4())


def test_a_variant_of_the_wrong_kind_is_refused_in_either_role(world: World) -> None:
    refused(world, "not a FACE_DETECTOR", detector=world.embedder)
    refused(world, "not a FACE_REPRESENTATION", embedder=world.detector)


def test_a_variant_that_is_not_in_the_catalog_is_refused(world: World) -> None:
    ghost = PlannedVariant(**{**vars_of(world.detector), "runtime_variant_id": uuid.uuid4()})
    refused(world, "not in the catalog", detector=ghost)
    refused(world, "not in the catalog", embedder=PlannedVariant(
        **{**vars_of(world.embedder), "runtime_variant_id": uuid.uuid4()}
    ))  # fmt: skip


def test_an_output_naming_another_component_version_than_the_variants_is_refused(
    world: World,
) -> None:
    other = uuid.uuid4()
    refused(
        world, "belongs to component version",
        detector=PlannedVariant(**{**vars_of(world.detector), "component_version_id": other}),
    )  # fmt: skip
    refused(
        world, "belongs to component version",
        embedder=PlannedVariant(**{**vars_of(world.embedder), "component_version_id": other}),
    )  # fmt: skip


def test_an_embedder_the_library_never_declared_for_the_space_is_refused(world: World) -> None:
    world.session.execute(update(RuntimeVariantRepresentationSpace).values(state="RETIRED"))
    refused(world, "not declared")


def test_a_validated_embedder_is_accepted_like_a_declared_one(world: World) -> None:
    world.session.execute(update(RuntimeVariantRepresentationSpace).values(state="VALIDATED"))
    world.write()
    assert world.counts() == (1, 1)


def vars_of(variant: PlannedVariant) -> dict[str, Any]:
    return {name: getattr(variant, name) for name in PlannedVariant.__slots__}


def test_the_timestamps_are_the_callers(world: World) -> None:
    moment = datetime(2026, 10, 3, 12, 0, tzinfo=world.clock().tzinfo)
    written = world.write(now=moment)
    observation = world.session.get(Observation, written.observation_id)
    representation = world.session.get(Representation, written.representation_id)
    assert observation is not None
    assert representation is not None
    assert observation.created_at == moment
    assert representation.created_at == moment
