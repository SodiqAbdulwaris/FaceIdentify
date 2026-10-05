"""The private execution boundary for a claimed single-image job (M3 step 10)."""

import io
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PIL import Image
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from backend.app.identities.models import Identity
from backend.app.jobs.models import Job
from backend.app.jobs.repository import ClaimedJob, JobRepository
from backend.app.memory.models import Observation, Representation
from backend.app.processing import execute_job
from backend.app.processing.execute_job import (
    ExecuteProcessingJob,
    ProcessingCancelledError,
    ProcessingExecutionError,
    _Decision,
    _frozen,
    _Input,
    _int,
    _number,
    _object,
    _string,
    _uuid,
)
from backend.app.processing.models import (
    ExecutionSegment,
    ProcessingCheckpoint,
    ProcessingConfigurationSnapshot,
    ProcessingRun,
)
from backend.app.processing.repository import SegmentRepository
from backend.app.processing.scheduler import StartedProcessingJob
from backend.app.recognition.assessment import ObservationQuality, RecognitionAssessment
from backend.app.recognition.reasoner import (
    DecisionPolicy,
    Reason,
    RecognitionDecision,
    RecognitionOutcome,
)
from backend.app.runtime.package_store import RuntimePackageStore
from backend.app.runtime.perception_client import (
    Detected,
    FaceVector,
    ProviderFallback,
    ProviderUnavailable,
    Represented,
)
from backend.app.runtime.registration import RegisteredExport, register_package
from backend.app.runtime.worker_config import PerceptionPlan, PlannedVariant
from backend.app.sources.models import Artifact, Source
from backend.infrastructure.db.unit_of_work import TransactionRetry, UnitOfWork
from backend.infrastructure.indexing.representation_index import RepresentationIndex
from backend.ml.contracts.messages import Detection
from backend.ml.contracts.protocol import MLErrorCode
from tests.factories.models import ModelFactory
from tests.fixtures.catalog_packages import installed, manifest_dict


class NoFaceClient:
    def __init__(self, detector: PlannedVariant) -> None:
        self._detector = detector
        self.detect_calls = 0
        self.represent_calls = 0

    def detect(self, pixels: Any) -> Detected:
        self.detect_calls += 1
        assert pixels.shape == (2, 3, 3)
        return Detected((), self._detector)

    def represent(self, pixels: Any, detections: tuple[Detection, ...]) -> Represented:
        self.represent_calls += 1
        assert not detections
        return Represented((), None)


class OneFaceClient(NoFaceClient):
    def __init__(
        self,
        detector: PlannedVariant,
        embedder: PlannedVariant,
        *,
        after_detect: Callable[[], None] | None = None,
        detector_fallbacks: tuple[ProviderFallback, ...] = (),
        embedder_fallbacks: tuple[ProviderFallback, ...] = (),
    ) -> None:
        super().__init__(detector)
        self._embedder = embedder
        self._after_detect = after_detect
        self._detector_fallbacks = detector_fallbacks
        self._embedder_fallbacks = embedder_fallbacks

    def detect(self, pixels: Any) -> Detected:
        self.detect_calls += 1
        result = Detected(
            (Detection(0, 0, (0.2, 0.2, 0.8, 0.8), 0.9, None),),
            self._detector,
            self._detector_fallbacks,
        )
        if self._after_detect is not None:
            self._after_detect()
        return result

    def represent(self, pixels: Any, detections: tuple[Detection, ...]) -> Represented:
        self.represent_calls += 1
        assert len(detections) == 1
        vector = np.full(512, 1 / np.sqrt(512), dtype="<f4")
        return Represented(
            (FaceVector(0, vector, "L2_NORMALIZED"),),
            self._embedder,
            self._embedder_fallbacks,
        )


def _snapshot(build: ModelFactory) -> ProcessingConfigurationSnapshot:
    detector, embedder, space = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    return build.add(
        ProcessingConfigurationSnapshot(
            id=build.new_id(),
            schema_version=1,
            canonical_json={
                "schema_version": 1,
                "detector": {
                    "component_version": {"id": str(detector)},
                    "export": {"id": str(uuid.uuid4())},
                },
                "embedder": {"export": {"id": str(embedder)}},
                "representation_space": {"id": str(space), "dimension": 4},
                "runtime_policy": {"schema_version": 1, "providers": ["CPU"]},
                "decision_policy": {
                    "schema_version": 1,
                    "version": "fixture-v1",
                    "min_detection_score": 0.1,
                    "new_identity_ceiling": 0.2,
                    "match_threshold": 0.8,
                    "margin": 0.1,
                },
            },
            fingerprint_sha256=b"x" * 32,
            created_at=build.clock(),
        )
    )


def _payload() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "detector": {
            "component_version": {"id": str(uuid.uuid4())},
            "export": {"id": str(uuid.uuid4())},
        },
        "embedder": {"export": {"id": str(uuid.uuid4())}},
        "representation_space": {"id": str(uuid.uuid4()), "dimension": 4},
        "runtime_policy": {"schema_version": 1, "providers": ["CPU"]},
        "decision_policy": {
            "schema_version": 1,
            "version": "fixture-v1",
            "min_detection_score": 0.1,
            "new_identity_ceiling": 0.2,
            "match_threshold": 0.8,
            "margin": 0.1,
        },
    }


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value.__setitem__("schema_version", 2),
        lambda value: value.__setitem__("runtime_policy", {"providers": []}),
        lambda value: value["detector"].__setitem__("export", {"id": "bad"}),
        lambda value: value["representation_space"].__setitem__("dimension", True),
        lambda value: value["decision_policy"].__setitem__("margin", False),
        lambda value: value["decision_policy"].__setitem__("version", ""),
    ],
)
def test_corrupt_frozen_snapshots_fail_closed(mutate: Any) -> None:
    payload = _payload()
    mutate(payload)

    with pytest.raises(ProcessingExecutionError):
        _frozen(payload)


@pytest.mark.parametrize(
    ("function", "value"),
    [
        (_object, None),
        (_uuid, 3),
        (_uuid, "not-a-uuid"),
        (_int, 0),
        (_int, True),
        (_string, ""),
        (_number, False),
    ],
)
def test_frozen_value_guards_fail_closed(function: Any, value: object) -> None:
    with pytest.raises(ProcessingExecutionError):
        _call_guard(function, value)


def test_snapshot_value_errors_are_normalized() -> None:
    payload = _payload()
    payload["decision_policy"]["new_identity_ceiling"] = 2.0

    with pytest.raises(ProcessingExecutionError, match="malformed"):
        _frozen(payload)


def _call_guard(function: Any, value: object) -> None:
    if function is _object or function is _int:
        function(value, "payload")
    else:
        function(value)


def test_constructor_and_original_loader_reject_incomplete_locations(
    sqlite_engine: Engine, file_store: Any, storage_roots: Any, build: ModelFactory, tmp_path: Path
) -> None:
    executor: Any = object.__new__(ExecuteProcessingJob)
    executor._files = file_store
    managed = _Input(uuid.uuid4(), uuid.uuid4(), {}, "MANAGED", None, None)
    referenced = _Input(uuid.uuid4(), uuid.uuid4(), {}, "REFERENCED", None, None)
    unknown = _Input(uuid.uuid4(), uuid.uuid4(), {}, "OTHER", None, None)
    for source in (managed, referenced, unknown):
        with pytest.raises(ProcessingExecutionError):
            executor._read_original(source)
    path = tmp_path / "original.bin"
    path.write_bytes(b"referenced")
    assert (
        executor._read_original(
            _Input(uuid.uuid4(), uuid.uuid4(), {}, "REFERENCED", None, str(path))
        )
        == b"referenced"
    )
    with pytest.raises(ValueError, match="max_pixels"):
        ExecuteProcessingJob(
            UnitOfWork(sqlite_engine, retry=TransactionRetry(1, lambda _: 0), sleep=lambda _: None),
            packages=RuntimePackageStore(storage_roots, new_id=build.new_id),
            files=file_store,
            client_for=lambda _: NoFaceClient(
                PlannedVariant(
                    uuid.uuid4(),
                    uuid.uuid4(),
                    "FACE_DETECTOR",
                    "fixture",
                    "CPU",
                    "cpu",
                    "pkg",
                    Path("unused"),
                    b"x" * 32,
                )
            ),
            global_index_for=lambda _: RepresentationIndex.empty(
                tmp_path / "index", representation_space_id=uuid.uuid4(), ndim=4, metric="cos"
            ),
            new_id=build.new_id,
            clock=build.clock,
            max_pixels=0,
            recognition_k=2,
        )


def test_known_execution_failure_closes_only_private_work(
    sqlite_engine: Engine, build: ModelFactory
) -> None:
    run = build.run()
    segment = build.segment(run)
    job = build.job(processing_run_id=run.id, state="RUNNING")
    build.session.commit()
    executor: Any = object.__new__(ExecuteProcessingJob)
    executor._uow = UnitOfWork(
        sqlite_engine, retry=TransactionRetry(1, lambda _: 0), sleep=lambda _: None
    )
    executor._clock = build.clock
    started = StartedProcessingJob(
        ClaimedJob(
            job.id,
            job.type,
            run.id,
            1,
            None,
            1,
            "worker",
            build.clock() + timedelta(seconds=1),
        ),
        segment.id,
    )

    executor._fail(started, "TEST_FAILURE")

    with Session(sqlite_engine) as session:
        failed_run = session.get(ProcessingRun, run.id)
        failed_segment = session.get(ExecutionSegment, segment.id)
        failed_job = session.get(type(job), job.id)
        assert failed_run is not None
        assert failed_run.state == "FAILED"
        assert failed_run.failure_code == "TEST_FAILURE"
        assert failed_segment is not None
        assert failed_segment.state == "FAILED"
        assert failed_job is not None
        assert failed_job.state == "FAILED"


@pytest.mark.parametrize("requested_on", ["job", "run"])
def test_cancellation_is_settled_only_at_a_safe_boundary(
    sqlite_engine: Engine, build: ModelFactory, requested_on: str
) -> None:
    executor, _, started = _finalizer(build)
    executor._uow = UnitOfWork(
        sqlite_engine, retry=TransactionRetry(1, lambda _: 0), sleep=lambda _: None
    )
    if requested_on == "job":
        job = build.session.get(Job, started.job.id)
        assert job is not None
        job.state = "CANCELLING"
    else:
        run = build.session.get(ProcessingRun, started.job.processing_run_id)
        assert run is not None
        run.state = "CANCELLING"
    build.session.commit()

    with pytest.raises(ProcessingCancelledError, match="cancelled"):
        executor._cancel_if_requested(started)

    with Session(sqlite_engine) as session:
        run = session.get(ProcessingRun, started.job.processing_run_id)
        job = session.get(Job, started.job.id)
        segment = session.get(ExecutionSegment, started.execution_segment_id)
        assert run is not None
        assert run.state == "CANCELLED"
        assert job is not None
        assert job.state == "CANCELLED"
        assert segment is not None
        assert (segment.state, segment.ended_reason) == ("COMPLETED", "CANCELLED")


def test_an_unlinked_claim_cannot_look_cancelled(build: ModelFactory) -> None:
    started = StartedProcessingJob(
        ClaimedJob(build.new_id(), "PROCESS_SOURCE", None, 1, None, 1, "worker", build.clock()),
        build.new_id(),
    )

    assert not ExecuteProcessingJob._cancellation_requested(build.session, started)


def test_execute_settles_cancellation_before_loading_the_run(
    sqlite_engine: Engine, build: ModelFactory
) -> None:
    executor, source, started = _finalizer(build)
    executor._uow = UnitOfWork(
        sqlite_engine, retry=TransactionRetry(1, lambda _: 0), sleep=lambda _: None
    )
    run = build.session.get(ProcessingRun, source.run_id)
    assert run is not None
    run.state = "CANCELLING"
    build.session.commit()
    executor._input = lambda *_: (_ for _ in ()).throw(AssertionError("must not load"))

    with pytest.raises(ProcessingCancelledError, match="cancelled"):
        executor.execute(started)

    with Session(sqlite_engine) as session:
        cancelled_run = session.get(ProcessingRun, source.run_id)
        cancelled_job = session.get(Job, started.job.id)
        cancelled_segment = session.get(ExecutionSegment, started.execution_segment_id)
        assert cancelled_run is not None
        assert cancelled_run.state == "CANCELLED"
        assert cancelled_job is not None
        assert cancelled_job.state == "CANCELLED"
        assert cancelled_segment is not None
        assert cancelled_segment.ended_reason == "CANCELLED"


@pytest.mark.parametrize("run_id", [None, uuid.uuid4()])
def test_cancellation_settlement_tolerates_a_stale_claim(
    build: ModelFactory, run_id: uuid.UUID | None
) -> None:
    executor: Any = object.__new__(ExecuteProcessingJob)
    executor._clock = build.clock
    started = StartedProcessingJob(
        ClaimedJob(build.new_id(), "PROCESS_SOURCE", run_id, 1, None, 1, "worker", build.clock()),
        build.new_id(),
    )

    executor._cancel(build.session, started)


def test_cancellation_with_a_foreign_segment_leaves_claimed_work_running(
    build: ModelFactory,
) -> None:
    executor, source, started = _finalizer(build)
    other = build.run()
    foreign_segment = build.segment(other)

    executor._cancel(build.session, StartedProcessingJob(started.job, foreign_segment.id))

    build.session.expire_all()
    run = build.session.get(ProcessingRun, source.run_id)
    claimed = build.session.get(ExecutionSegment, started.execution_segment_id)
    job = build.session.get(Job, started.job.id)
    foreign = build.session.get(ExecutionSegment, foreign_segment.id)
    assert run is not None
    assert run.state == "RUNNING"
    assert claimed is not None
    assert claimed.state == "RUNNING"
    assert job is not None
    assert job.state == "RUNNING"
    assert foreign is not None
    assert foreign.state == "RUNNING"


@pytest.mark.parametrize(
    ("operation", "run_state", "job_state"),
    [
        ("cancel", "CANCELLING", "PAUSING"),
        ("fail", "RUNNING", "CANCELLING"),
    ],
)
def test_terminal_settlement_refuses_an_ineligible_claimed_job(
    sqlite_engine: Engine,
    build: ModelFactory,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    run_state: str,
    job_state: str,
) -> None:
    executor, source, started = _finalizer(build)
    run = build.session.get(ProcessingRun, source.run_id)
    job = build.session.get(Job, started.job.id)
    assert run is not None
    assert job is not None
    run.state = run_state
    job.state = job_state
    build.session.commit()
    executor._uow = UnitOfWork(
        sqlite_engine, retry=TransactionRetry(1, lambda _: 0), sleep=lambda _: None
    )

    if operation == "cancel":
        with pytest.raises(ProcessingCancelledError, match="cancelled"):
            executor._cancel_if_requested(started)
    else:
        monkeypatch.setattr(
            SegmentRepository,
            "close",
            lambda *_args, **_kwargs: pytest.fail("an ineligible Job must not close its segment"),
        )
        executor._fail(started, "TEST_FAILURE")

    with Session(sqlite_engine) as session:
        unchanged_run = session.get(ProcessingRun, source.run_id)
        unchanged_job = session.get(Job, started.job.id)
        unchanged_segment = session.get(ExecutionSegment, started.execution_segment_id)
        assert unchanged_run is not None
        assert unchanged_run.state == run_state
        assert unchanged_job is not None
        assert unchanged_job.state == job_state
        assert unchanged_segment is not None
        assert unchanged_segment.state == "RUNNING"


@pytest.mark.parametrize("operation", ["cancel", "fail"])
def test_terminal_settlement_refuses_a_job_linked_to_another_run(
    sqlite_engine: Engine, build: ModelFactory, operation: str
) -> None:
    executor, source, started = _finalizer(build)
    run = build.session.get(ProcessingRun, source.run_id)
    job = build.session.get(Job, started.job.id)
    assert run is not None
    assert job is not None
    other = build.run()
    run.state = "CANCELLING" if operation == "cancel" else "RUNNING"
    job.processing_run_id = other.id
    build.session.commit()
    executor._uow = UnitOfWork(
        sqlite_engine, retry=TransactionRetry(1, lambda _: 0), sleep=lambda _: None
    )

    if operation == "cancel":
        with pytest.raises(ProcessingCancelledError, match="cancelled"):
            executor._cancel_if_requested(started)
    else:
        executor._fail(started, "TEST_FAILURE")

    with Session(sqlite_engine) as session:
        unchanged_run = session.get(ProcessingRun, source.run_id)
        unchanged_job = session.get(Job, started.job.id)
        unchanged_segment = session.get(ExecutionSegment, started.execution_segment_id)
        assert unchanged_run is not None
        assert unchanged_run.state == ("CANCELLING" if operation == "cancel" else "RUNNING")
        assert unchanged_job is not None
        assert unchanged_job.processing_run_id == other.id
        assert unchanged_job.state == "RUNNING"
        assert unchanged_segment is not None
        assert unchanged_segment.state == "RUNNING"


def test_cancellation_leaves_a_nonrunning_run_unchanged(build: ModelFactory) -> None:
    executor, source, started = _finalizer(build)
    run = build.session.get(ProcessingRun, source.run_id)
    assert run is not None
    run.state = "PENDING"
    build.session.flush()

    executor._cancel(build.session, started)

    assert run.state == "PENDING"


def _not_running(_: ModelFactory, run: ProcessingRun) -> None:
    run.state = "PENDING"


def _recycled(_: ModelFactory, run: ProcessingRun) -> None:
    run.source.state = "RECYCLED"


def _missing_original(build: ModelFactory, run: ProcessingRun) -> None:
    artifact = build.session.get(Artifact, run.source.original_artifact_id)
    assert artifact is not None
    artifact.state = "MISSING"


@pytest.mark.parametrize("prepare", [_not_running, _recycled, _missing_original])
def test_input_revalidates_durable_run_source_and_original(
    build: ModelFactory, prepare: Any
) -> None:
    run = build.run()
    segment = build.segment(run)
    job = build.job(processing_run_id=run.id, state="RUNNING")
    prepare(build, run)
    build.session.flush()
    executor: Any = object.__new__(ExecuteProcessingJob)
    started = StartedProcessingJob(
        ClaimedJob(job.id, job.type, run.id, 1, None, 1, "worker", build.clock()), segment.id
    )

    with pytest.raises(ProcessingExecutionError):
        executor._input(build.session, started)


def test_input_refuses_a_missing_durable_run(build: ModelFactory) -> None:
    executor: Any = object.__new__(ExecuteProcessingJob)
    started = StartedProcessingJob(
        ClaimedJob(
            build.new_id(), "PROCESS_SOURCE", build.new_id(), 1, None, 1, "worker", build.clock()
        ),
        build.new_id(),
    )

    with pytest.raises(ProcessingExecutionError, match="missing"):
        executor._input(build.session, started)


def test_input_refuses_a_claim_without_a_run(build: ModelFactory) -> None:
    executor: Any = object.__new__(ExecuteProcessingJob)
    started = StartedProcessingJob(
        ClaimedJob(build.new_id(), "PROCESS_SOURCE", None, 1, None, 1, "worker", build.clock()),
        build.new_id(),
    )

    with pytest.raises(ProcessingExecutionError, match="no processing run"):
        executor._input(build.session, started)


def test_representation_settlement_rejects_worker_protocol_contradictions() -> None:
    executor: Any = object.__new__(ExecuteProcessingJob)
    variant = PlannedVariant(
        uuid.uuid4(), uuid.uuid4(), "FACE_DETECTOR", "fixture", "CPU", "cpu", "pkg", Path("x"), b"x"
    )
    detected = Detected((), variant)
    frozen: Any = object()
    source = _Input(uuid.uuid4(), uuid.uuid4(), {}, "MANAGED", "key", None)
    started = StartedProcessingJob(
        ClaimedJob(
            uuid.uuid4(), "PROCESS_SOURCE", source.run_id, 1, None, 1, "worker", datetime.now()
        ),
        uuid.uuid4(),
    )
    with pytest.raises(ProcessingExecutionError, match="unexpectedly represented"):
        executor._settle_representations(
            object(), source, started, frozen, detected, [], Represented((), variant)
        )


def test_representation_settlement_requires_one_vector_per_detected_face() -> None:
    executor: Any = object.__new__(ExecuteProcessingJob)
    variant = PlannedVariant(
        uuid.uuid4(), uuid.uuid4(), "FACE_DETECTOR", "fixture", "CPU", "cpu", "pkg", Path("x"), b"x"
    )
    detected = Detected((Detection(0, 0, (0.1, 0.1, 0.9, 0.9), 0.9, None),), variant)
    source = _Input(uuid.uuid4(), uuid.uuid4(), {}, "MANAGED", "key", None)
    started = StartedProcessingJob(
        ClaimedJob(
            uuid.uuid4(), "PROCESS_SOURCE", source.run_id, 1, None, 1, "worker", datetime.now()
        ),
        uuid.uuid4(),
    )
    with pytest.raises(ProcessingExecutionError, match="did not settle"):
        executor._settle_representations(
            object(), source, started, object(), detected, [uuid.uuid4()], Represented((), None)
        )


def _decision(identity_id: uuid.UUID | None, outcome: RecognitionOutcome) -> RecognitionDecision:
    policy = DecisionPolicy("fixture-v1", 0.1, 0.8, 0.1, 0.2)
    assessment = RecognitionAssessment(
        "fixture", "COSINE_UNCALIBRATED", uuid.uuid4(), ObservationQuality(0.9), 2, 0, 0, True, ()
    )
    reason = Reason.MATCHED if outcome is RecognitionOutcome.MATCH_EXISTING else Reason.LOW_QUALITY
    return RecognitionDecision(outcome, reason, identity_id, assessment, policy)


@pytest.mark.parametrize("outcome", [RecognitionOutcome.MATCH_EXISTING, RecognitionOutcome.ABSTAIN])
def test_private_decision_persistence_handles_match_and_abstain(
    build: ModelFactory, outcome: RecognitionOutcome
) -> None:
    executor, source, started = _finalizer(build)
    run = build.session.get(ProcessingRun, source.run_id)
    assert run is not None
    observation = build.observation(run, execution_segment_id=started.execution_segment_id)
    representation = build.representation(observation)
    identity = build.identity()
    decision = _decision(
        identity.id if outcome is RecognitionOutcome.MATCH_EXISTING else None, outcome
    )

    persisted = executor._persist_decisions(
        build.session,
        source,
        started,
        [_Decision(observation.id, representation.id, decision, None)],
    )

    assert len(persisted) == 1
    assert representation.identity_id == (
        identity.id if outcome is RecognitionOutcome.MATCH_EXISTING else None
    )


def test_private_decision_persistence_rejects_stale_rows(build: ModelFactory) -> None:
    executor, source, started = _finalizer(build)
    run = build.session.get(ProcessingRun, source.run_id)
    assert run is not None
    missing = _Decision(
        uuid.uuid4(), uuid.uuid4(), _decision(None, RecognitionOutcome.ABSTAIN), None
    )
    with pytest.raises(ProcessingExecutionError, match="no longer this run"):
        executor._persist_decisions(build.session, source, started, [missing])

    observation = build.observation(run, execution_segment_id=started.execution_segment_id)
    representation = build.representation(observation)
    representation.state = "ACTIVE"
    stale = _Decision(
        observation.id, representation.id, _decision(None, RecognitionOutcome.ABSTAIN), None
    )
    with pytest.raises(ProcessingExecutionError, match="no longer private"):
        executor._persist_decisions(build.session, source, started, [stale])

    representation.state = "PENDING"
    unmatched = _Decision(
        observation.id,
        representation.id,
        _decision(uuid.uuid4(), RecognitionOutcome.MATCH_EXISTING),
        None,
    )
    with pytest.raises(ProcessingExecutionError, match="no longer ACTIVE"):
        executor._persist_decisions(build.session, source, started, [unmatched])


def test_decision_refuses_a_representation_space_that_changed() -> None:
    class ReadOnce:
        def read(self, work: Any) -> Any:
            return work(type("Session", (), {"get": lambda *_: None})())

    executor: Any = object.__new__(ExecuteProcessingJob)
    executor._uow = ReadOnce()
    executor._global_index_for = lambda _: object()
    frozen = _frozen(_payload())
    with pytest.raises(ProcessingExecutionError, match="no longer valid"):
        executor._decide(
            _Input(uuid.uuid4(), uuid.uuid4(), {}, "MANAGED", "key", None), frozen, [uuid.uuid4()]
        )


def test_execute_records_known_failure_then_reraises() -> None:
    class ReadOnce:
        def read(self, work: Any) -> Any:
            return work(None)

    executor: Any = object.__new__(ExecuteProcessingJob)
    executor._uow = ReadOnce()
    executor._input = lambda _session, _started: (_ for _ in ()).throw(
        ProcessingExecutionError("bad")
    )
    executor._cancel_if_requested = lambda _started: None
    recorded: list[str] = []
    executor._fail = lambda _started, code: recorded.append(code)
    started = StartedProcessingJob(
        ClaimedJob(
            uuid.uuid4(), "PROCESS_SOURCE", uuid.uuid4(), 1, None, 1, "worker", datetime.now()
        ),
        uuid.uuid4(),
    )
    with pytest.raises(ProcessingExecutionError, match="bad"):
        executor.execute(started)
    assert recorded == ["ProcessingExecutionError"]


def _finalizer(build: ModelFactory) -> tuple[Any, _Input, StartedProcessingJob]:
    run = build.run()
    segment = build.segment(run)
    job = build.job(processing_run_id=run.id, state="RUNNING")
    executor: Any = object.__new__(ExecuteProcessingJob)
    executor._new_id = build.new_id
    executor._clock = build.clock
    return (
        executor,
        _Input(run.source_id, run.id, {}, "MANAGED", "key", None),
        StartedProcessingJob(
            ClaimedJob(job.id, job.type, run.id, 1, None, 1, "worker", build.clock()), segment.id
        ),
    )


@pytest.mark.parametrize("state", ["PENDING", "RUNNING"])
def test_finalization_rejects_a_nonrunning_run_or_segment(build: ModelFactory, state: str) -> None:
    executor, source, started = _finalizer(build)
    if state == "PENDING":
        run = build.session.get(ProcessingRun, source.run_id)
        assert run is not None
        run.state = state
    else:
        segment = build.session.get(ExecutionSegment, started.execution_segment_id)
        assert segment is not None
        segment.state = "COMPLETED"
    build.session.flush()

    with pytest.raises(ProcessingExecutionError):
        executor._finalize(build.session, source, started, [], [])


def test_finalization_rejects_a_job_that_is_not_running(build: ModelFactory) -> None:
    executor, source, started = _finalizer(build)
    job = build.session.get(Job, started.job.id)
    assert job is not None
    job.state = "FAILED"
    build.session.flush()

    with pytest.raises(ProcessingExecutionError, match="job"):
        executor._finalize(build.session, source, started, [], [])


def test_private_output_checkpoint_records_only_durable_pending_rows(build: ModelFactory) -> None:
    executor, source, started = _finalizer(build)
    observations, representations = [build.new_id()], [build.new_id()]

    checkpoint_id = executor._append_private_output_checkpoint(
        build.session, source, started, observations, representations
    )

    checkpoint = build.session.get(ProcessingCheckpoint, checkpoint_id)
    run = build.session.get(ProcessingRun, source.run_id)
    assert checkpoint is not None
    assert checkpoint.kind == "INTERMEDIATE"
    assert checkpoint.payload_json == {
        "schema_version": 1,
        "observations": [str(observations[0])],
        "representations": [str(representations[0])],
    }
    assert run is not None
    assert run.current_checkpoint_id == checkpoint_id


@pytest.mark.parametrize("stale", ["run", "segment", "job"])
def test_private_output_checkpoint_refuses_stale_execution_state(
    build: ModelFactory, stale: str
) -> None:
    executor, source, started = _finalizer(build)
    if stale == "run":
        run = build.session.get(ProcessingRun, source.run_id)
        assert run is not None
        run.state = "PENDING"
    elif stale == "segment":
        segment = build.session.get(ExecutionSegment, started.execution_segment_id)
        assert segment is not None
        segment.state = "COMPLETED"
    else:
        job = build.session.get(Job, started.job.id)
        assert job is not None
        job.state = "FAILED"
    build.session.flush()

    with pytest.raises(ProcessingExecutionError):
        executor._append_private_output_checkpoint(build.session, source, started, [], [])


def test_private_output_checkpoint_refuses_an_optimistic_race(
    build: ModelFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    executor, source, started = _finalizer(build)
    monkeypatch.setattr(execute_job, "optimistic_locked_update", lambda *_args, **_kw: 0)

    with pytest.raises(ProcessingExecutionError, match="changed while checkpointing"):
        executor._append_private_output_checkpoint(build.session, source, started, [], [])


@pytest.mark.parametrize("operation", ["checkpoint", "finalize"])
def test_checkpoint_and_finalization_refuse_a_segment_of_another_run(
    build: ModelFactory, operation: str
) -> None:
    executor, source, started = _finalizer(build)
    other = build.run()
    foreign_segment = build.segment(other)
    wrong_started = StartedProcessingJob(started.job, foreign_segment.id)
    action = (
        executor._append_private_output_checkpoint
        if operation == "checkpoint"
        else executor._finalize
    )

    with pytest.raises(ProcessingExecutionError, match="segment"):
        action(build.session, source, wrong_started, [], [])


def test_planning_uses_only_frozen_component_and_export_selections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frozen = _frozen(_payload())
    executor: Any = object.__new__(ExecuteProcessingJob)
    executor._packages = object()
    seen: dict[str, Any] = {}
    sentinel = object()

    def planned(session: object, packages: object, **arguments: Any) -> object:
        seen.update(arguments)
        assert session == "session"
        assert packages is executor._packages
        return sentinel

    monkeypatch.setattr(execute_job, "plan_perception", planned)

    assert executor._plan("session", frozen) is sentinel
    assert seen == {
        "detector_component_version_id": frozen.detector_component_version_id,
        "detector_model_export_id": frozen.detector_export_id,
        "embedder_model_export_id": frozen.embedder_export_id,
        "representation_space_id": frozen.representation_space_id,
        "providers": frozen.providers,
    }


def test_decision_refuses_when_a_settled_representation_disappears() -> None:
    frozen = _frozen(_payload())
    space = type(
        "Space", (), {"id": frozen.representation_space_id, "dimension": frozen.dimension}
    )()

    class Session:
        calls = 0

        def get(self, _: object, __: object) -> object:
            return space

        def execute(self, _: object) -> object:
            self.calls += 1
            if self.calls == 1:
                return []
            return type("Rows", (), {"all": lambda _: []})()

    class ReadOnce:
        def read(self, work: Any) -> Any:
            return work(Session())

    executor: Any = object.__new__(ExecuteProcessingJob)
    executor._uow = ReadOnce()
    executor._global_index_for = lambda _: object()
    with pytest.raises(ProcessingExecutionError, match="disappeared"):
        executor._decide(
            _Input(uuid.uuid4(), uuid.uuid4(), {}, "MANAGED", "key", None), frozen, [uuid.uuid4()]
        )


def test_finalization_refuses_to_close_or_update_after_a_race(
    build: ModelFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    executor, source, started = _finalizer(build)
    monkeypatch.setattr(SegmentRepository, "close", lambda *_args, **_kw: False)
    with pytest.raises(ProcessingExecutionError, match="could not close"):
        executor._finalize(build.session, source, started, [], [])

    build.session.rollback()
    monkeypatch.undo()
    executor, source, started = _finalizer(build)
    monkeypatch.setattr(execute_job, "optimistic_locked_update", lambda *_args, **_kw: 0)
    with pytest.raises(ProcessingExecutionError, match="changed"):
        executor._finalize(build.session, source, started, [], [])


def test_failure_settlement_handles_missing_or_already_stopped_runs(
    sqlite_engine: Engine, build: ModelFactory
) -> None:
    executor: Any = object.__new__(ExecuteProcessingJob)
    executor._uow = UnitOfWork(
        sqlite_engine, retry=TransactionRetry(1, lambda _: 0), sleep=lambda _: None
    )
    executor._clock = build.clock
    no_run = build.job(processing_run_id=None, state="RUNNING")
    run = build.run()
    run.state = "PENDING"
    pending = build.job(processing_run_id=run.id, state="RUNNING")
    build.session.commit()
    for job, run_id in ((no_run, None), (pending, run.id)):
        executor._fail(
            StartedProcessingJob(
                ClaimedJob(job.id, job.type, run_id, 1, None, 1, "worker", build.clock()),
                uuid.uuid4(),
            ),
            "TEST",
        )


def test_failure_with_a_foreign_segment_leaves_claimed_work_running(
    sqlite_engine: Engine, build: ModelFactory
) -> None:
    executor, source, started = _finalizer(build)
    other = build.run()
    foreign_segment = build.segment(other)
    build.session.commit()
    executor._uow = UnitOfWork(
        sqlite_engine, retry=TransactionRetry(1, lambda _: 0), sleep=lambda _: None
    )

    executor._fail(StartedProcessingJob(started.job, foreign_segment.id), "TEST_FAILURE")

    with Session(sqlite_engine) as session:
        failed_run = session.get(ProcessingRun, source.run_id)
        claimed = session.get(ExecutionSegment, started.execution_segment_id)
        job = session.get(Job, started.job.id)
        foreign = session.get(ExecutionSegment, foreign_segment.id)
        assert failed_run is not None
        assert failed_run.state == "RUNNING"
        assert claimed is not None
        assert claimed.state == "RUNNING"
        assert job is not None
        assert job.state == "RUNNING"
        assert foreign is not None
        assert foreign.state == "RUNNING"


def test_failure_settlement_leaves_an_unsettled_claim_running(
    sqlite_engine: Engine, build: ModelFactory
) -> None:
    job = build.job(processing_run_id=None, state="RUNNING")
    build.session.commit()
    executor: Any = object.__new__(ExecuteProcessingJob)
    executor._uow = UnitOfWork(
        sqlite_engine, retry=TransactionRetry(1, lambda _: 0), sleep=lambda _: None
    )
    executor._clock = build.clock
    missing_run_id = build.new_id()
    started = StartedProcessingJob(
        ClaimedJob(job.id, job.type, missing_run_id, 1, None, 1, "worker", build.clock()),
        build.new_id(),
    )

    executor._fail(started, "TEST_FAILURE")

    with Session(sqlite_engine) as session:
        failed_job = session.get(Job, job.id)
        assert failed_job is not None
        assert failed_job.state == "RUNNING"


@pytest.mark.parametrize("operation", ["cancel", "fail"])
def test_unsuccessful_segment_close_leaves_claimed_work_running(
    sqlite_engine: Engine, build: ModelFactory, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    executor, source, started = _finalizer(build)
    monkeypatch.setattr(SegmentRepository, "close", lambda *_args, **_kwargs: False)
    if operation == "fail":
        build.session.commit()
        executor._uow = UnitOfWork(
            sqlite_engine, retry=TransactionRetry(1, lambda _: 0), sleep=lambda _: None
        )
        executor._fail(started, "TEST_FAILURE")
    else:
        executor._cancel(build.session, started)
        build.session.expire_all()

    session = build.session if operation == "cancel" else Session(sqlite_engine)
    try:
        run = session.get(ProcessingRun, source.run_id)
        job = session.get(Job, started.job.id)
        segment = session.get(ExecutionSegment, started.execution_segment_id)
        assert run is not None
        assert run.state == "RUNNING"
        assert job is not None
        assert job.state == "RUNNING"
        assert segment is not None
        assert segment.state == "RUNNING"
    finally:
        if operation == "fail":
            session.close()


@pytest.mark.parametrize("operation", ["cancel", "fail"])
def test_terminal_settlement_rolls_back_if_the_job_cannot_transition(
    sqlite_engine: Engine,
    build: ModelFactory,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    executor, source, started = _finalizer(build)
    monkeypatch.setattr(JobRepository, "transition", lambda *_args, **_kwargs: False)
    executor._uow = UnitOfWork(
        sqlite_engine, retry=TransactionRetry(1, lambda _: 0), sleep=lambda _: None
    )
    if operation == "cancel":
        run = build.session.get(ProcessingRun, source.run_id)
        assert run is not None
        run.state = "CANCELLING"
        build.session.commit()
        with pytest.raises(ProcessingExecutionError, match="job changed"):
            executor._cancel_if_requested(started)
    else:
        build.session.commit()
        executor._fail(started, "TEST_FAILURE")

    with Session(sqlite_engine) as session:
        unchanged_run = session.get(ProcessingRun, source.run_id)
        unchanged_job = session.get(Job, started.job.id)
        unchanged_segment = session.get(ExecutionSegment, started.execution_segment_id)
        assert unchanged_run is not None
        assert unchanged_run.state == ("CANCELLING" if operation == "cancel" else "RUNNING")
        assert unchanged_job is not None
        assert unchanged_job.state == "RUNNING"
        assert unchanged_segment is not None
        assert unchanged_segment.state == "RUNNING"


def _planned(export: RegisteredExport) -> PlannedVariant:
    (variant_id,) = export.variant_ids.values()
    return PlannedVariant(
        component_version_id=export.component_version_id,
        runtime_variant_id=variant_id,
        kind=export.kind,
        contract="fixture",
        provider="CPUExecutionProvider",
        device="CPU",
        package_key="fixture",
        model_path=Path("fixture.onnx"),
        sha256=b"x" * 32,
    )


def _snapshot_for(
    build: ModelFactory, detector: RegisteredExport, embedder: RegisteredExport
) -> ProcessingConfigurationSnapshot:
    assert embedder.representation_space_id is not None
    return build.add(
        ProcessingConfigurationSnapshot(
            id=build.new_id(),
            schema_version=1,
            canonical_json={
                "schema_version": 1,
                "detector": {
                    "component_version": {"id": str(detector.component_version_id)},
                    "export": {"id": str(detector.model_export_id)},
                },
                "embedder": {"export": {"id": str(embedder.model_export_id)}},
                "representation_space": {
                    "id": str(embedder.representation_space_id),
                    "dimension": 512,
                },
                "runtime_policy": {
                    "schema_version": 1,
                    "providers": ["CPUExecutionProvider"],
                },
                "decision_policy": {
                    "schema_version": 1,
                    "version": "fixture-v1",
                    "min_detection_score": 0.1,
                    "new_identity_ceiling": 0.2,
                    "match_threshold": 0.8,
                    "margin": 0.1,
                },
            },
            fingerprint_sha256=b"x" * 32,
            created_at=build.clock(),
        )
    )


def _one_face_execution(
    sqlite_engine: Engine,
    build: ModelFactory,
    file_store: Any,
    storage_roots: Any,
    tmp_path: Path,
    *,
    after_detect: Callable[[], None] | None = None,
) -> tuple[
    ExecuteProcessingJob,
    OneFaceClient,
    StartedProcessingJob,
    uuid.UUID,
    uuid.UUID,
    uuid.UUID,
]:
    package = register_package(
        build.session,
        installed(tmp_path / "package", manifest_dict("fixture")),
        new_id=build.new_id,
        clock=build.clock,
    )
    by_kind = {export.kind: export for export in package.exports}
    detector, embedder = by_kind["FACE_DETECTOR"], by_kind["FACE_REPRESENTATION"]
    assert embedder.representation_space_id is not None
    source = build.source()
    artifact = build.session.get(Artifact, source.original_artifact_id)
    assert artifact is not None
    artifact.storage_key = f"originals/{artifact.id.hex}"
    encoded = io.BytesIO()
    Image.new("RGB", (3, 2), "white").save(encoded, format="PNG")
    file_store.store(artifact.storage_key, io.BytesIO(encoded.getvalue()))
    snapshot = _snapshot_for(build, detector, embedder)
    run = build.run(source_id=source.id, configuration_snapshot_id=snapshot.id)
    segment = build.segment(run)
    job = build.job(processing_run_id=run.id, state="RUNNING")
    build.session.commit()

    detector_plan, embedder_plan = _planned(detector), _planned(embedder)
    plan = PerceptionPlan(embedder.representation_space_id, 512, (detector_plan,), (embedder_plan,))
    client = OneFaceClient(detector_plan, embedder_plan, after_detect=after_detect)
    executor = ExecuteProcessingJob(
        UnitOfWork(sqlite_engine, retry=TransactionRetry(1, lambda _: 0), sleep=lambda _: None),
        packages=RuntimePackageStore(storage_roots, new_id=build.new_id),
        files=file_store,
        client_for=lambda _: client,
        global_index_for=lambda space_id: RepresentationIndex.empty(
            storage_roots.local_state_root / "index",
            representation_space_id=space_id,
            ndim=512,
            metric="cos",
        ),
        new_id=build.new_id,
        clock=build.clock,
        max_pixels=100,
        recognition_k=2,
    )
    executor._plan = lambda _session, _frozen: plan  # type: ignore[method-assign, assignment]
    started = StartedProcessingJob(
        ClaimedJob(
            job.id,
            job.type,
            run.id,
            1,
            None,
            1,
            "worker",
            build.clock() + timedelta(seconds=1),
        ),
        segment.id,
    )
    return executor, client, started, source.id, run.id, job.id


def test_no_face_image_becomes_a_private_final_checkpoint(
    sqlite_engine: Engine, build: ModelFactory, file_store: Any, storage_roots: Any
) -> None:
    source = build.source()
    artifact = build.session.get(Artifact, source.original_artifact_id)
    assert artifact is not None
    artifact.storage_key = f"originals/{artifact.id.hex}"
    image = Image.new("RGB", (3, 2), "white")
    encoded = io.BytesIO()
    image.save(encoded, format="PNG")
    file_store.store(artifact.storage_key, io.BytesIO(encoded.getvalue()))
    snapshot = _snapshot(build)
    run = build.run(source_id=source.id, configuration_snapshot_id=snapshot.id)
    segment = build.segment(run)
    job = build.job(processing_run_id=run.id, state="RUNNING")
    build.session.commit()

    detector = PlannedVariant(
        component_version_id=uuid.uuid4(),
        runtime_variant_id=uuid.uuid4(),
        kind="FACE_DETECTOR",
        contract="fixture",
        provider="CPU",
        device="cpu",
        package_key="fixture",
        model_path=storage_roots.local_state_root / "unused.onnx",
        sha256=b"d" * 32,
    )
    plan = PerceptionPlan(uuid.uuid4(), 4, (detector,), ())
    client = NoFaceClient(detector)
    executor = ExecuteProcessingJob(
        UnitOfWork(sqlite_engine, retry=TransactionRetry(1, lambda _: 0), sleep=lambda _: None),
        packages=RuntimePackageStore(storage_roots, new_id=build.new_id),
        files=file_store,
        client_for=lambda _: client,
        global_index_for=lambda _: RepresentationIndex.empty(
            storage_roots.local_state_root / "unused",
            representation_space_id=uuid.uuid4(),
            ndim=4,
            metric="cos",
        ),
        new_id=build.new_id,
        clock=build.clock,
        max_pixels=100,
        recognition_k=2,
    )
    executor._plan = lambda _session, _frozen: plan  # type: ignore[method-assign, assignment]
    started = StartedProcessingJob(
        ClaimedJob(
            job.id, job.type, run.id, 1, None, 1, "worker", build.clock() + timedelta(seconds=1)
        ),
        segment.id,
    )

    result = executor.execute(started)

    assert client.detect_calls == client.represent_calls == 1
    assert result.observation_ids == result.representation_ids == ()
    with Session(sqlite_engine) as session:
        persisted_run = session.get(ProcessingRun, run.id)
        persisted_segment = session.get(ExecutionSegment, segment.id)
        checkpoint = session.get(ProcessingCheckpoint, result.final_checkpoint_id)
        assert persisted_run is not None
        assert persisted_run.state == "FINALIZING"
        assert persisted_run.current_checkpoint_id == result.final_checkpoint_id
        assert persisted_segment is not None
        assert persisted_segment.state == "COMPLETED"
        assert checkpoint is not None
        assert checkpoint.kind == "FINAL"
        assert checkpoint.payload_json == {"schema_version": 1, "observations": [], "decisions": []}


def test_face_output_stays_pending_and_its_new_identity_stays_private(
    sqlite_engine: Engine,
    build: ModelFactory,
    file_store: Any,
    storage_roots: Any,
    tmp_path: Path,
) -> None:
    executor, client, started, _source_id, _run_id, _job_id = _one_face_execution(
        sqlite_engine, build, file_store, storage_roots, tmp_path
    )
    result = executor.execute(started)

    assert len(result.observation_ids) == len(result.representation_ids) == 1
    with Session(sqlite_engine) as session:
        observation = session.get(Observation, result.observation_ids[0])
        representation = session.get(Representation, result.representation_ids[0])
        assert observation is not None
        assert observation.state == "PENDING"
        assert observation.runtime_variant_id == client._detector.runtime_variant_id
        assert representation is not None
        assert representation.state == "PENDING"
        assert representation.runtime_variant_id == client._embedder.runtime_variant_id
        assert representation.identity_id is not None
        identity = session.get(Identity, representation.identity_id)
        assert identity is not None
        assert identity.state == "PENDING"
        checkpoint = session.get(ProcessingCheckpoint, result.final_checkpoint_id)
        assert checkpoint is not None
        assert checkpoint.payload_json["decisions"][0]["outcome"] == "CREATE_NEW"
        segments = list(
            session.scalars(
                select(ExecutionSegment)
                .where(ExecutionSegment.processing_run_id == started.job.processing_run_id)
                .order_by(ExecutionSegment.ordinal)
            )
        )
        assert len(segments) == 1
        assert (
            observation.execution_segment_id
            == representation.execution_segment_id
            == segments[0].id
        )


def _provider_fallback(
    selected: PlannedVariant, *, message: str = "CUDA is unavailable"
) -> ProviderFallback:
    return ProviderFallback(
        (
            ProviderUnavailable(
                PlannedVariant(
                    component_version_id=selected.component_version_id,
                    runtime_variant_id=uuid.uuid4(),
                    kind=selected.kind,
                    contract=selected.contract,
                    provider="CUDAExecutionProvider",
                    device="cuda",
                    package_key=selected.package_key,
                    model_path=selected.model_path,
                    sha256=selected.sha256,
                ),
                MLErrorCode.RUNTIME_VARIANT_NOT_AVAILABLE,
                message,
            ),
        ),
        selected,
    )


def test_detector_provider_fallback_starts_a_cpu_execution_segment(
    sqlite_engine: Engine,
    build: ModelFactory,
    file_store: Any,
    storage_roots: Any,
    tmp_path: Path,
) -> None:
    executor, client, started, _source_id, run_id, _job_id = _one_face_execution(
        sqlite_engine, build, file_store, storage_roots, tmp_path
    )
    fallback = _provider_fallback(client._detector)
    client._detector_fallbacks = (fallback,)

    result = executor.execute(started)

    with Session(sqlite_engine) as session:
        segments = list(
            session.scalars(
                select(ExecutionSegment)
                .where(ExecutionSegment.processing_run_id == run_id)
                .order_by(ExecutionSegment.ordinal)
            )
        )
        observation = session.get(Observation, result.observation_ids[0])
        representation = session.get(Representation, result.representation_ids[0])
        assert len(segments) == 2
        assert segments[0].runtime_variant_id is None
        assert segments[0].state == "COMPLETED"
        assert segments[0].ended_reason == "FALLBACK"
        assert segments[1].runtime_variant_id == client._detector.runtime_variant_id
        assert segments[1].state == "COMPLETED"
        assert segments[1].ended_reason == "NORMAL"
        assert segments[1].runtime_details_json == {
            "schema_version": 1,
            "transition": "PROVIDER_FALLBACK",
            "failed_attempts": [
                {
                    "variant_id": str(fallback.failed[0].variant.runtime_variant_id),
                    "provider": "CUDAExecutionProvider",
                    "error_code": "RUNTIME_VARIANT_NOT_AVAILABLE",
                    "error_message": "CUDA is unavailable",
                }
            ],
            "selected_variant_id": str(client._detector.runtime_variant_id),
            "selected_provider": client._detector.provider,
        }
        assert observation is not None
        assert representation is not None
        assert observation.execution_segment_id == segments[1].id
        assert representation.execution_segment_id == segments[1].id


def test_embedder_provider_fallback_keeps_detection_in_its_original_segment(
    sqlite_engine: Engine,
    build: ModelFactory,
    file_store: Any,
    storage_roots: Any,
    tmp_path: Path,
) -> None:
    executor, client, started, _source_id, run_id, _job_id = _one_face_execution(
        sqlite_engine, build, file_store, storage_roots, tmp_path
    )
    client._embedder_fallbacks = (_provider_fallback(client._embedder),)

    result = executor.execute(started)

    with Session(sqlite_engine) as session:
        segments = list(
            session.scalars(
                select(ExecutionSegment)
                .where(ExecutionSegment.processing_run_id == run_id)
                .order_by(ExecutionSegment.ordinal)
            )
        )
        observation = session.get(Observation, result.observation_ids[0])
        representation = session.get(Representation, result.representation_ids[0])
        assert len(segments) == 2
        assert segments[0].ended_reason == "FALLBACK"
        assert segments[1].runtime_variant_id == client._embedder.runtime_variant_id
        assert observation is not None
        assert representation is not None
        assert observation.execution_segment_id == segments[0].id
        assert representation.execution_segment_id == segments[1].id


def test_failed_provider_transition_does_not_persist_private_output(
    sqlite_engine: Engine,
    build: ModelFactory,
    file_store: Any,
    storage_roots: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executor, client, started, _source_id, run_id, _job_id = _one_face_execution(
        sqlite_engine, build, file_store, storage_roots, tmp_path
    )
    client._detector_fallbacks = (_provider_fallback(client._detector),)
    close = SegmentRepository.close
    calls = 0

    def refuse_first_close(self: SegmentRepository, *args: Any, **kwargs: Any) -> bool:
        nonlocal calls
        calls += 1
        if calls == 1:
            return False
        return close(self, *args, **kwargs)

    monkeypatch.setattr(SegmentRepository, "close", refuse_first_close)

    with pytest.raises(ProcessingExecutionError, match="could not close for fallback"):
        executor.execute(started)

    with Session(sqlite_engine) as session:
        assert not list(
            session.scalars(select(Observation).where(Observation.processing_run_id == run_id))
        )
        run = session.get(ProcessingRun, run_id)
        job = session.get(Job, started.job.id)
        assert run is not None
        assert run.state == "FAILED"
        assert job is not None
        assert job.state == "FAILED"


def test_cancellation_after_detection_settlement_does_not_start_embedding(
    sqlite_engine: Engine,
    build: ModelFactory,
    file_store: Any,
    storage_roots: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executor, client, started, _source_id, run_id, job_id = _one_face_execution(
        sqlite_engine, build, file_store, storage_roots, tmp_path
    )
    write = executor._uow.write
    detection_settled = False

    def cancel_after_detection(work: Callable[[Session], Any]) -> Any:
        nonlocal detection_settled
        result = write(work)
        if not detection_settled:
            detection_settled = True
            with Session(sqlite_engine) as session:
                job = session.get(Job, job_id)
                assert job is not None
                job.state = "CANCELLING"
                session.commit()
        return result

    monkeypatch.setattr(executor._uow, "write", cancel_after_detection)

    with pytest.raises(ProcessingCancelledError, match="cancelled"):
        executor.execute(started)

    assert client.detect_calls == 1
    assert client.represent_calls == 0
    with Session(sqlite_engine) as session:
        run = session.get(ProcessingRun, run_id)
        job = session.get(Job, job_id)
        assert run is not None
        assert run.state == "CANCELLED"
        assert job is not None
        assert job.state == "CANCELLED"
        observations = list(
            session.scalars(select(Observation).where(Observation.processing_run_id == run_id))
        )
        assert len(observations) == 1
        assert observations[0].state == "PENDING"
        assert not list(
            session.scalars(
                select(Representation).where(Representation.processing_run_id == run_id)
            )
        )


def test_recycled_source_before_settlement_cannot_persist_detection(
    sqlite_engine: Engine,
    build: ModelFactory,
    file_store: Any,
    storage_roots: Any,
    tmp_path: Path,
) -> None:
    executor, client, started, source_id, run_id, _job_id = _one_face_execution(
        sqlite_engine, build, file_store, storage_roots, tmp_path
    )

    def recycle_source() -> None:
        with Session(sqlite_engine) as session:
            source = session.get(Source, source_id)
            assert source is not None
            source.state = "RECYCLED"
            session.commit()

    client._after_detect = recycle_source

    with pytest.raises(ProcessingExecutionError, match="active image"):
        executor.execute(started)

    assert client.detect_calls == 1
    assert client.represent_calls == 0
    with Session(sqlite_engine) as session:
        assert not list(
            session.scalars(select(Observation).where(Observation.processing_run_id == run_id))
        )


@pytest.mark.parametrize(
    ("changed", "expected"),
    [
        ("source", "active image"),
        ("artifact", "original is not available"),
        ("job", "job is no longer running"),
    ],
)
def test_private_settlement_revalidates_mutable_owners(
    build: ModelFactory, changed: str, expected: str
) -> None:
    executor, source, started = _finalizer(build)
    if changed == "source":
        current_source = build.session.get(Source, source.source_id)
        assert current_source is not None
        current_source.state = "RECYCLED"
    elif changed == "artifact":
        source_row = build.session.get(Source, source.source_id)
        assert source_row is not None
        current_artifact = build.session.get(Artifact, source_row.original_artifact_id)
        assert current_artifact is not None
        current_artifact.state = "MISSING"
    else:
        current_job = build.session.get(Job, started.job.id)
        assert current_job is not None
        current_job.state = "CANCELLED"
    build.session.flush()

    with pytest.raises(ProcessingExecutionError, match=expected):
        executor._revalidate_settlement_context(build.session, source, started)
