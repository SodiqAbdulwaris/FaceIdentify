"""M3 end to end: request -> claim -> private execution -> FINAL -> acceptance -> index -> restart
(TST-043 "results survive restart"; persistence §30).

Only perception is faked (a client that returns planted detections and vectors, never real weights).
Everything else is real: SQLite through `open_library`, the scheduler, the executor, acceptance, the
IndexCoordinator, USearch and startup recovery. The story, with unit-length 4-d vectors:

* A creates identity I1;
* B is a face near A and matches I1 with no new identity;
* C is a different face and creates I2;
* the process restarts and the index is lost, so recovery rebuilds it from SQLite;
* D is a face near A and matches I1 through the rebuilt index.

B is also run with the process "crashing" after execution (FINAL written, not accepted) and after
acceptance (ADD queued, not applied): the next start finishes the work without rerunning ML.
"""

import io
import shutil
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PIL import Image
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.identities.models import Evidence, Identity
from backend.app.lifecycle import OpenLibrary, open_library
from backend.app.memory.index_coordinator import RetryPolicy
from backend.app.memory.models import IndexOperation, Occurrence, Representation
from backend.app.processing.accept_run import AcceptProcessingRunUseCase
from backend.app.processing.execute_job import ExecuteProcessingJob
from backend.app.processing.models import ProcessingRun
from backend.app.processing.process_source import ProcessSourceUseCase
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


A = unit(1, 0, 0, 0)
B = unit(0.95, 0.1, 0, 0)  # near A
C = unit(0, 1, 0, 0)  # unlike A and B
D = unit(0.9, 0, 0.1, 0)  # near A


class PlantedPerception:
    """Detects one face and embeds it as whatever vector the test planted; counts its calls."""

    def __init__(self, detector: PlannedVariant, embedder: PlannedVariant) -> None:
        self.detector, self.embedder = detector, embedder
        self.vector = A
        self.calls = 0

    def detect(self, pixels: Any) -> Detected:
        self.calls += 1
        return Detected((Detection(0, 0, (0.2, 0.2, 0.8, 0.8), 0.9, None),), self.detector)

    def represent(self, pixels: Any, detections: tuple[Detection, ...]) -> Represented:
        self.calls += 1
        return Represented((FaceVector(0, self.vector, "L2_NORMALIZED"),), self.embedder, ())


class Library:
    """One open of the library; `request` and the planted perception persist across opens."""

    def __init__(
        self,
        lib: OpenLibrary,
        clock: FrozenClock,
        new_id: SeededUUIDs,
        request: dict[str, Any],
        perception: PlantedPerception,
        plan: PerceptionPlan,
    ) -> None:
        self.lib, self.clock, self.new_id = lib, clock, new_id
        self.request, self.perception, self.plan = request, perception, plan
        self.space_id = plan.representation_space_id

    def import_image(self) -> uuid.UUID:
        with Session(self.lib.engine) as session:
            build = ModelFactory(session, self.clock, self.new_id)
            artifact = build.artifact()
            artifact.storage_key = f"originals/{artifact.id.hex}"
            source = build.source(original_artifact_id=artifact.id)
            encoded = io.BytesIO()
            Image.new("RGB", (3, 2), "white").save(encoded, format="PNG")
            self.lib.store.store(f"originals/{artifact.id.hex}", io.BytesIO(encoded.getvalue()))
            session.commit()
            return source.id

    def execute(self, source_id: uuid.UUID) -> uuid.UUID:
        """Request, claim and privately execute: the run is left FINALIZING. Returns its id."""
        lib = self.lib
        ProcessSourceUseCase(
            lib.unit_of_work, new_id=self.new_id, clock=self.clock, wake_scheduler=lambda: None
        ).process(
            source_id,
            processing_request=self.request,
            priority="NORMAL",
            created_by_user_action=None,
        )
        started = ProcessingScheduler(
            lib.unit_of_work, new_id=self.new_id, clock=self.clock, lease_for=timedelta(minutes=5)
        ).claim_source_job("worker")
        assert started is not None
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
        run_id = started.job.processing_run_id
        assert run_id is not None
        executor.execute(started)
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
def story(tmp_path: Path, clock: FrozenClock, new_id: SeededUUIDs) -> tuple[Any, ...]:
    (tmp_path / "library").mkdir()
    state: dict[str, Any] = {}

    @contextmanager
    def opened() -> Iterator[Library]:
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
            if not state:
                with Session(lib.engine) as session:
                    build = ModelFactory(session, clock, new_id)
                    request = processing_request(build)
                    session.commit()
                    detector = _planned(session, request["detector"]["model_export_id"])
                    embedder = _planned(session, request["embedder"]["model_export_id"])
                state["request"] = request
                state["perception"] = PlantedPerception(detector, embedder)
                state["plan"] = PerceptionPlan(
                    uuid.UUID(request["representation_space_id"]), NDIM, (detector,), (embedder,)
                )
            yield Library(lib, clock, new_id, state["request"], state["perception"], state["plan"])

    return opened, state, tmp_path


def _planned(session: Session, export_id: str) -> PlannedVariant:
    export = session.get(ModelExport, uuid.UUID(export_id))
    assert export is not None
    variant = session.scalars(
        select(RuntimeVariant).where(RuntimeVariant.model_export_id == export.id)
    ).one()
    kind = (
        "FACE_DETECTOR"
        if export.input_contract_json["contract"].startswith("scrfd")
        else ("FACE_REPRESENTATION")
    )
    return PlannedVariant(
        component_version_id=export.component_version_id,
        runtime_variant_id=variant.id,
        kind=kind,
        contract="fixture",
        provider="CPUExecutionProvider",
        device="CPU",
        package_key="fixture",
        model_path=Path("fixture.onnx"),
        sha256=b"x" * 32,
    )


def recognise(library: Library, vector: np.ndarray, *, stop: str = "done") -> uuid.UUID:
    """One image through the pipeline, stopping where a crash would. `stop` is `execute` (FINAL
    written, not accepted), `accept` (accepted, index not applied) or `done`."""
    library.perception.vector = vector
    run_id = library.execute(library.import_image())
    if stop != "execute":
        library.accept(run_id, apply_index=stop == "done")
    return run_id


@pytest.mark.parametrize("stop_b", ["done", "accept", "execute"])
def test_recognition_survives_restart_and_a_rebuilt_index(story: Any, stop_b: str) -> None:
    opened, _state, _tmp_path = story

    with opened() as lib:  # --- first process
        recognise(lib, A)
        assert lib.count(Identity) == 1  # A created I1
        recognise(lib, B, stop=stop_b)
        calls_before_restart = lib.perception.calls

    with opened() as lib:  # --- restart: recovery finishes whatever B left
        assert lib.perception.calls == calls_before_restart  # recovery never ran ML
        with lib.lib.session_factory() as session:
            runs = list(session.scalars(select(ProcessingRun.state)))
        assert runs == ["COMPLETED", "COMPLETED"]
        assert lib.count(Identity) == 1  # B matched I1: no new identity
        recognise(lib, C)  # C creates I2
        assert lib.count(Identity) == 2
        space = lib.space_id
        index_directory = lib.lib.coordinator.index_directory(space)

    # the index is lost between processes; SQLite still holds every vector
    assert index_directory.exists()
    shutil.rmtree(index_directory)

    with opened() as lib:  # --- restart with no index
        assert lib.lib.startup.indexes_rebuilt == [space]
        rebuilt = lib.global_index(space)
        assert len(rebuilt) == 3  # A, B and C are in it again
        recognise(lib, D)  # D matches I1 through the rebuilt index

        with lib.lib.session_factory() as session:
            identities = list(session.scalars(select(Identity).order_by(Identity.created_at)))
            kinds = sorted(session.scalars(select(Evidence.kind)))
            representations = list(session.scalars(select(Representation)))
        assert len(identities) == 2
        assert all(i.state == "ACTIVE" for i in identities)
        assert kinds == ["IDENTITY_CREATED"] * 2 + ["IDENTITY_MATCHED"] * 2
        assert lib.count(Occurrence) == 4
        assert all(r.state == "ACTIVE" for r in representations)
        by_identity: dict[uuid.UUID | None, int] = {}
        for representation in representations:
            by_identity[representation.identity_id] = (
                by_identity.get(representation.identity_id, 0) + 1
            )
        assert sorted(by_identity.values()) == [1, 3]  # I2 has C; I1 has A, B and D
        with lib.lib.session_factory() as session:
            assert not list(
                session.scalars(select(IndexOperation).where(IndexOperation.state != "APPLIED"))
            )
        assert len(lib.global_index(space)) == 4
