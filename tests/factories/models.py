"""Deterministic persistence factories (TST-008).

`ModelFactory` builds valid, flushed rows with every id from `new_id` and every timestamp from
`clock`, so tests are reproducible. Pass keyword overrides to change fields; missing parents are
created on demand. Use the `build` fixture rather than constructing the factory yourself.
"""

import hashlib
import struct
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from sqlalchemy.orm import Session

from backend.app.identities.models import Evidence, Identity
from backend.app.jobs.models import Job
from backend.app.memory.models import (
    Observation,
    Occurrence,
    Representation,
    RepresentationSpace,
)
from backend.app.people.models import IdentityPersonAssociation, Person
from backend.app.processing.models import (
    ExecutionSegment,
    ProcessingCheckpoint,
    ProcessingConfigurationSnapshot,
    ProcessingRun,
)
from backend.app.runtime.models import Component, ComponentVersion
from backend.app.sources.models import Artifact, Source
from tests.fixtures.deterministic import FrozenClock, SeededUUIDs

SHA = hashlib.sha256(b"bytes").digest()


def float32_vector(values: list[float]) -> bytes:
    """Little-endian float32 bytes: the canonical vector encoding (§23)."""
    return struct.pack(f"<{len(values)}f", *values)


class ModelFactory:
    """Valid rows with overridable fields, all ids and times deterministic."""

    def __init__(self, session: Session, clock: FrozenClock, new_id: SeededUUIDs) -> None:
        self.session, self.clock, self.new_id = session, clock, new_id
        # Per-run state so repeated observations share one segment and number themselves.
        self._segments: dict[uuid.UUID, ExecutionSegment] = {}
        self._sequences: dict[uuid.UUID, int] = {}

    def add[T](self, row: T) -> T:
        self.session.add(row)
        self.session.flush()
        return row

    def _parent(self, kw: dict[str, Any], key: str, make: Callable[[], Any]) -> uuid.UUID:
        """Use kw[key] if given, otherwise build the parent with `make()`."""
        given: uuid.UUID | None = kw.pop(key, None)
        if given is not None:
            return given
        made: uuid.UUID = make().id
        return made

    # --- sources and processing ---------------------------------------------------------

    def artifact(self, **kw: Any) -> Artifact:
        fields: dict[str, Any] = dict(
            id=self.new_id(), kind="SOURCE_ORIGINAL", storage_mode="MANAGED", state="AVAILABLE",
            storage_key=f"originals/{self.new_id()}", sha256=SHA, size_bytes=5,
            created_at=self.clock(),
        )  # fmt: skip
        return self.add(Artifact(**(fields | kw)))

    def source(self, **kw: Any) -> Source:
        fields: dict[str, Any] = dict(
            id=self.new_id(), kind="IMAGE", state="ACTIVE", display_name="beach.jpg",
            original_artifact_id=self._parent(kw, "original_artifact_id", self.artifact),
            created_at=self.clock(), updated_at=self.clock(),
        )  # fmt: skip
        return self.add(Source(**(fields | kw)))

    def snapshot(self) -> ProcessingConfigurationSnapshot:
        return self.add(
            ProcessingConfigurationSnapshot(
                id=self.new_id(), schema_version=1, canonical_json={}, fingerprint_sha256=SHA,
                created_at=self.clock(),
            )
        )  # fmt: skip

    def run(self, **kw: Any) -> ProcessingRun:
        fields: dict[str, Any] = dict(
            id=self.new_id(), source_id=self._parent(kw, "source_id", self.source),
            configuration_snapshot_id=self._parent(kw, "configuration_snapshot_id", self.snapshot),
            state="RUNNING", requested_at=self.clock(), created_at=self.clock(),
            updated_at=self.clock(),
        )  # fmt: skip
        return self.add(ProcessingRun(**(fields | kw)))

    def segment(
        self, run: ProcessingRun, ordinal: int = 0, state: str = "RUNNING"
    ) -> ExecutionSegment:
        return self.add(
            ExecutionSegment(
                id=self.new_id(), processing_run_id=run.id, ordinal=ordinal, state=state,
                runtime_details_json={}, started_at=self.clock(), created_at=self.clock(),
            )
        )  # fmt: skip

    def checkpoint(
        self, run: ProcessingRun, ordinal: int, kind: str, state: str
    ) -> ProcessingCheckpoint:
        return self.add(
            ProcessingCheckpoint(
                id=self.new_id(), processing_run_id=run.id, ordinal=ordinal, kind=kind,
                state=state, payload_schema_version=1, payload_json={}, created_at=self.clock(),
            )
        )  # fmt: skip

    def job(self, **kw: Any) -> Job:
        fields: dict[str, Any] = dict(
            id=self.new_id(), type="PROCESS_SOURCE", state="QUEUED", priority="NORMAL",
            payload_schema_version=1, progress_mode="DETERMINATE", created_at=self.clock(),
            updated_at=self.clock(),
        )  # fmt: skip
        return self.add(Job(**(fields | kw)))

    # --- catalog ------------------------------------------------------------------------

    def component_version(self, kind: str = "FACE_DETECTOR") -> ComponentVersion:
        component = self.add(
            Component(
                id=self.new_id(), key=f"component-{self.new_id()}", kind=kind,
                display_name=kind, state="ACTIVE",
            )
        )  # fmt: skip
        return self.add(
            ComponentVersion(
                id=self.new_id(), component_id=component.id, semantic_version="1.0.0",
                contract_schema_version=1, contract_json={}, created_at=self.clock(),
            )
        )  # fmt: skip

    def representation_space(self, **kw: Any) -> RepresentationSpace:
        fields: dict[str, Any] = dict(
            id=self.new_id(), semantic_key=f"space-{self.new_id()}", state="ACTIVE",
            dimension=4, metric="COSINE", normalization="L2_NORMALIZED",
            component_version_id=self._parent(
                kw, "component_version_id", lambda: self.component_version("FACE_REPRESENTATION")
            ),
            contract_schema_version=1, contract_json={}, created_at=self.clock(),
        )  # fmt: skip
        return self.add(RepresentationSpace(**(fields | kw)))

    # --- memory -------------------------------------------------------------------------

    def observation(self, run: ProcessingRun | None = None, /, **kw: Any) -> Observation:
        run = run or self.run()
        segment_id = self._parent(kw, "execution_segment_id", lambda: self._run_segment(run))
        sequence = kw.pop("sequence_in_run", None)
        fields: dict[str, Any] = dict(
            id=self.new_id(), source_id=run.source_id, processing_run_id=run.id,
            execution_segment_id=segment_id, state="PENDING",
            sequence_in_run=self._next_sequence(run) if sequence is None else sequence,
            bbox_x=0.1, bbox_y=0.1, bbox_width=0.2, bbox_height=0.3,
            detector_component_version_id=self._parent(
                kw, "detector_component_version_id", self.component_version
            ),
            created_at=self.clock(),
        )  # fmt: skip
        return self.add(Observation(**(fields | kw)))

    def _run_segment(self, run: ProcessingRun) -> ExecutionSegment:
        if run.id not in self._segments:
            self._segments[run.id] = self.segment(run)
        return self._segments[run.id]

    def _next_sequence(self, run: ProcessingRun) -> int:
        self._sequences[run.id] = self._sequences.get(run.id, -1) + 1
        return self._sequences[run.id]

    def identity(self, **kw: Any) -> Identity:
        fields: dict[str, Any] = dict(
            id=self.new_id(), state="ACTIVE", created_at=self.clock(), updated_at=self.clock(),
            activated_at=self.clock(),
        )  # fmt: skip
        return self.add(Identity(**(fields | kw)))

    def representation(
        self, observation: Observation | None = None, /, **kw: Any
    ) -> Representation:
        observation = observation or self.observation()
        space_id = self._parent(kw, "representation_space_id", self.representation_space)
        fields: dict[str, Any] = dict(
            id=self.new_id(), observation_id=observation.id,
            processing_run_id=observation.processing_run_id,
            execution_segment_id=observation.execution_segment_id,
            representation_space_id=space_id, state="PENDING",
            vector=float32_vector([0.5, 0.5, 0.5, 0.5]), vector_dimension=4,
            created_at=self.clock(),
        )  # fmt: skip
        return self.add(Representation(**(fields | kw)))

    def occurrence(self, observation: Observation | None = None, /, **kw: Any) -> Occurrence:
        observation = observation or self.observation()
        fields: dict[str, Any] = dict(
            id=self.new_id(), source_id=observation.source_id,
            identity_id=self._parent(kw, "identity_id", self.identity),
            processing_run_id=observation.processing_run_id,
            representative_observation_id=observation.id, kind="IMAGE", state="PENDING",
            created_at=self.clock(),
        )  # fmt: skip
        return self.add(Occurrence(**(fields | kw)))

    def evidence(self, **kw: Any) -> Evidence:
        fields: dict[str, Any] = dict(
            id=self.new_id(), kind="IDENTITY_CREATED", payload_schema_version=1,
            payload_json={}, created_at=self.clock(),
        )  # fmt: skip
        return self.add(Evidence(**(fields | kw)))

    # --- people -------------------------------------------------------------------------

    def person(self, **kw: Any) -> Person:
        fields: dict[str, Any] = dict(
            id=self.new_id(), state="ACTIVE", display_name="Alice", normalized_name="alice",
            created_at=self.clock(), updated_at=self.clock(),
        )  # fmt: skip
        return self.add(Person(**(fields | kw)))

    def association(self, **kw: Any) -> IdentityPersonAssociation:
        fields: dict[str, Any] = dict(
            id=self.new_id(), identity_id=self._parent(kw, "identity_id", self.identity),
            person_id=self._parent(kw, "person_id", self.person), state="ACTIVE",
            created_at=self.clock(),
        )  # fmt: skip
        return self.add(IdentityPersonAssociation(**(fields | kw)))


@pytest.fixture
def build(db_session: Session, clock: FrozenClock, new_id: SeededUUIDs) -> ModelFactory:
    return ModelFactory(db_session, clock, new_id)
