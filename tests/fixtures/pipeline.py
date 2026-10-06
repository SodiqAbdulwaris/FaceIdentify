"""The real M3 pipeline with planted perception, shared by the end-to-end and process-kill tests.

Only perception is faked (a client returning a planted detection and vector; never real weights).
Everything else is real: the library opened through `open_library`, the scheduler, the executor,
acceptance and the IndexCoordinator. `Pipeline` drives one opened library; `prepare_catalog`
registers a fake catalog and returns what a later process needs (as JSON) to run the same pipeline.
"""

import io
import uuid
from collections.abc import Callable, Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PIL import Image
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.lifecycle import OpenLibrary, open_library
from backend.app.memory.index_coordinator import RetryPolicy
from backend.app.processing.accept_run import AcceptProcessingRunUseCase
from backend.app.processing.execute_job import ExecuteProcessingJob
from backend.app.processing.process_source import ProcessSourceUseCase
from backend.app.processing.runner import ProcessingRunner
from backend.app.processing.scheduler import ProcessingScheduler
from backend.app.runtime.models import ModelExport, RuntimeVariant
from backend.app.runtime.package_store import RuntimePackageStore
from backend.app.runtime.perception_client import Detected, FaceVector, Represented
from backend.app.runtime.worker_config import PerceptionPlan, PlannedVariant
from backend.infrastructure.db.unit_of_work import TransactionRetry
from backend.infrastructure.indexing.representation_index import (
    IndexUnusableError,
    RepresentationIndex,
)
from backend.ml.contracts.messages import Detection
from tests.factories.models import ModelFactory
from tests.fixtures.deterministic import FrozenClock, SeededUUIDs
from tests.fixtures.processing_request import processing_request

NDIM = 4


def unit(*values: float) -> np.ndarray:
    vector = np.array(values, dtype="<f4")
    return np.asarray(vector / np.linalg.norm(vector), dtype="<f4")


class PlantedPerception:
    """Detects one face and embeds it as whatever vector was planted; counts its calls."""

    def __init__(self, detector: PlannedVariant, embedder: PlannedVariant) -> None:
        self.detector, self.embedder = detector, embedder
        self.vector = unit(1, 0, 0, 0)
        self.calls = 0
        self.on_represent: Callable[[], None] | None = None

    def detect(self, pixels: Any) -> Detected:
        self.calls += 1
        return Detected((Detection(0, 0, (0.2, 0.2, 0.8, 0.8), 0.9, None),), self.detector)

    def represent(self, pixels: Any, detections: tuple[Detection, ...]) -> Represented:
        self.calls += 1
        if self.on_represent is not None:
            self.on_represent()
        return Represented((FaceVector(0, self.vector, "L2_NORMALIZED"),), self.embedder, ())


def planned_variant(session: Session, export_id: str) -> PlannedVariant:
    export = session.get(ModelExport, uuid.UUID(export_id))
    assert export is not None
    variant = session.scalars(
        select(RuntimeVariant).where(RuntimeVariant.model_export_id == export.id)
    ).one()
    contract = export.input_contract_json["contract"]
    return PlannedVariant(
        component_version_id=export.component_version_id,
        runtime_variant_id=variant.id,
        kind="FACE_DETECTOR" if contract.startswith("scrfd") else "FACE_REPRESENTATION",
        contract="fixture",
        provider="CPUExecutionProvider",
        device="CPU",
        package_key="fixture",
        model_path=Path("fixture.onnx"),
        sha256=b"x" * 32,
    )


def variant_to_json(variant: PlannedVariant) -> dict[str, str]:
    return {
        "component_version_id": str(variant.component_version_id),
        "runtime_variant_id": str(variant.runtime_variant_id),
        "kind": variant.kind,
    }


def variant_from_json(data: dict[str, str]) -> PlannedVariant:
    return PlannedVariant(
        component_version_id=uuid.UUID(data["component_version_id"]),
        runtime_variant_id=uuid.UUID(data["runtime_variant_id"]),
        kind=data["kind"],
        contract="fixture",
        provider="CPUExecutionProvider",
        device="CPU",
        package_key="fixture",
        model_path=Path("fixture.onnx"),
        sha256=b"x" * 32,
    )


def prepare_catalog(
    lib: OpenLibrary, clock: Callable[[], Any], new_id: Callable[[], uuid.UUID]
) -> dict[str, Any]:
    """Register a fake catalog in `lib` and return JSON-safe facts a later process needs."""
    with Session(lib.engine) as session:
        build = ModelFactory(session, clock, new_id)  # type: ignore[arg-type]
        request = processing_request(build)
        session.commit()
        detector = planned_variant(session, request["detector"]["model_export_id"])
        embedder = planned_variant(session, request["embedder"]["model_export_id"])
    return {
        "request": request,
        "detector": variant_to_json(detector),
        "embedder": variant_to_json(embedder),
        "space_id": request["representation_space_id"],
    }


class Pipeline:
    """One opened library, run through the real pipeline with planted perception."""

    def __init__(
        self,
        lib: OpenLibrary,
        clock: Callable[[], Any],
        new_id: Callable[[], uuid.UUID],
        catalog: dict[str, Any],
    ) -> None:
        self.lib, self.clock, self.new_id = lib, clock, new_id
        self.request = catalog["request"]
        detector = variant_from_json(catalog["detector"])
        embedder = variant_from_json(catalog["embedder"])
        self.space_id = uuid.UUID(catalog["space_id"])
        self.perception = PlantedPerception(detector, embedder)
        self.plan = PerceptionPlan(self.space_id, NDIM, (detector,), (embedder,))
        self.before_global_index: Callable[[], None] | None = None

    def import_image(self) -> uuid.UUID:
        with Session(self.lib.engine) as session:
            build = ModelFactory(session, self.clock, self.new_id)  # type: ignore[arg-type]
            artifact = build.artifact()
            artifact.storage_key = f"originals/{artifact.id.hex}"
            source = build.source(original_artifact_id=artifact.id)
            encoded = io.BytesIO()
            Image.new("RGB", (3, 2), "white").save(encoded, format="PNG")
            self.lib.store.store(f"originals/{artifact.id.hex}", io.BytesIO(encoded.getvalue()))
            session.commit()
            return source.id

    def enqueue(self, source_id: uuid.UUID) -> uuid.UUID:
        """Request processing: a snapshot, a PENDING run and a QUEUED job. Returns the job id."""
        return (
            ProcessSourceUseCase(
                self.lib.unit_of_work,
                new_id=self.new_id,
                clock=self.clock,
                wake_scheduler=lambda: None,
            )
            .process(
                source_id,
                processing_request=self.request,
                priority="NORMAL",
                created_by_user_action=None,
            )
            .job_id
        )

    def execute(self, source_id: uuid.UUID) -> uuid.UUID:
        """Request, claim and privately execute; the run is left FINALIZING. Returns its id."""
        self.enqueue(source_id)
        return self.run_next()

    def scheduler(self) -> ProcessingScheduler:
        lib = self.lib
        return ProcessingScheduler(
            lib.unit_of_work, new_id=self.new_id, clock=self.clock, lease_for=timedelta(minutes=5)
        )

    def executor(self) -> ExecuteProcessingJob:
        lib = self.lib
        executor = ExecuteProcessingJob(
            lib.unit_of_work,
            packages=RuntimePackageStore(lib.roots, new_id=self.new_id),
            files=lib.store,
            client_for=lambda _plan: self.perception,
            global_index_for=self.global_index,
            new_id=self.new_id,
            clock=self.clock,
            max_pixels=100,
            recognition_k=2,
        )
        executor._plan = lambda _session, _frozen: self.plan  # type: ignore[method-assign, assignment]
        return executor

    def runner(self, *, wake_index: Callable[[], None] | None = None) -> ProcessingRunner:
        uow = self.lib.unit_of_work
        return ProcessingRunner(
            uow,
            self.scheduler(),
            self.executor(),
            AcceptProcessingRunUseCase(
                uow, new_id=self.new_id, clock=self.clock, wake_index=wake_index
            ),
            owner="runner",
            clock=self.clock,
        )

    def run_next(self) -> uuid.UUID:
        """Claim the next queued job and execute it privately (also used to run a retry)."""
        started = self.scheduler().claim_source_job("worker")
        assert started is not None
        run_id = started.job.processing_run_id
        assert run_id is not None
        self.executor().execute(started)
        return run_id

    def accept(self, run_id: uuid.UUID, *, apply_index: bool) -> None:
        AcceptProcessingRunUseCase(
            self.lib.unit_of_work,
            new_id=self.new_id,
            clock=self.clock,
            wake_index=self.apply_index if apply_index else None,
        ).accept(run_id)

    def apply_index(self) -> None:
        self.lib.coordinator.apply_pending(limit=50)

    def global_index(self, space_id: uuid.UUID) -> RepresentationIndex:
        if self.before_global_index is not None:
            self.before_global_index()
        directory = self.lib.coordinator.index_directory(space_id)
        try:
            return RepresentationIndex.open(
                directory, representation_space_id=space_id, ndim=NDIM, metric="cos"
            )
        except IndexUnusableError:
            return RepresentationIndex.empty(
                directory, representation_space_id=space_id, ndim=NDIM, metric="cos"
            )

    def count(self, model: Any) -> int:
        with self.lib.session_factory() as session:
            return session.scalar(select(func.count()).select_from(model)) or 0


@pytest.fixture
def pipeline(tmp_path: Path, clock: FrozenClock, new_id: SeededUUIDs) -> Iterator[Pipeline]:
    """A freshly opened library with a registered fake catalog, run through the real pipeline."""
    (tmp_path / "library").mkdir()
    with open_library(
        library_root=tmp_path / "library",
        local_state_root=tmp_path / "local",
        clock=clock,
        new_id=new_id,
        index_batch=50,
        max_index_passes=5,
        transaction_retry=TransactionRetry(max_attempts=3, backoff=lambda n: 0.1 * n),
        retry=RetryPolicy(max_attempts=3, backoff=lambda n: timedelta(minutes=n)),
    ) as lib:
        yield Pipeline(lib, clock, new_id, prepare_catalog(lib, clock, new_id))
