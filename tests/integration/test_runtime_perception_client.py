"""TST-038 and TST-039 (backend side): running a perception plan against the worker.

Some tests use a real worker process with generated ONNX models (never real weights): they show
that a variant whose provider is missing is skipped and the next one runs, with the variant that
ran reported. The rest script the supervisor's answers, to reach what a real worker cannot be made
to say on demand (an initialisation failure, an answer for the wrong variant, a short answer).
"""

import hashlib
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, cast

import numpy as np
import pytest

from backend.app.runtime.perception_client import (
    PROVIDER_UNAVAILABLE,
    PerceptionClient,
    PerceptionError,
    supervisor_for,
)
from backend.app.runtime.worker_config import (
    PerceptionPlan,
    PlannedVariant,
    RuntimeUnavailableError,
)
from backend.infrastructure.resources.shared_memory import AttachedSegment, SegmentLedger
from backend.ml.contracts.messages import (
    DetectFacesOutput,
    Detection,
    ExecutionContext,
    ExecutionProvenance,
    GenerateRepresentationsOutput,
    MLError,
    MLRequest,
    MLResponse,
    RepresentationResult,
)
from backend.ml.contracts.protocol import ContractError, MLErrorCode, MLStatus
from backend.ml.perception import alignment, detection
from backend.ml.supervisor.supervisor import MLSupervisor, SupervisorPolicy, WorkerFailedError
from backend.ml.worker.perception_handlers import DETECTOR, EMBEDDER
from tests.fixtures.deterministic import SeededUUIDs
from tests.fixtures.onnx_models import (
    EMBEDDING_DIMENSION,
    PlantedFace,
    detector_model,
    embedder_model,
)

CPU = "CPUExecutionProvider"
MISSING = "NoSuchExecutionProvider"
FACE = PlantedFace(level=0, column=40, row=30)
POLICY = SupervisorPolicy(
    handshake_timeout=120,
    request_timeout=120,
    ping_timeout=10,
    shutdown_timeout=10,
    max_restarts=1,
    restart_window=600,
)
LANDMARKS = ((0.3, 0.3), (0.7, 0.3), (0.5, 0.5), (0.3, 0.7), (0.7, 0.7))


def planned(
    path: Path,
    data: bytes,
    kind: str,
    provider: str,
    *,
    component: uuid.UUID,
    runtime_variant: uuid.UUID | None = None,
) -> PlannedVariant:
    return PlannedVariant(
        component_version_id=component,
        runtime_variant_id=runtime_variant or uuid.uuid4(),
        kind=kind,
        contract=detection.VERSION if kind == DETECTOR else alignment.VERSION,
        provider=provider,
        device="cpu",
        package_key="pkg-test",
        model_path=path,
        sha256=hashlib.sha256(data).digest(),
    )


def plan_of(
    detectors: tuple[PlannedVariant, ...], embedders: tuple[PlannedVariant, ...]
) -> PerceptionPlan:
    return PerceptionPlan(uuid.uuid4(), EMBEDDING_DIMENSION, detectors, embedders)


def picture(width: int = 640, height: int = 480) -> np.ndarray[Any, Any]:
    return np.random.default_rng(3).integers(30, 220, (height, width, 3), dtype=np.uint8)


@pytest.fixture(scope="module")
def models(tmp_path_factory: pytest.TempPathFactory) -> dict[str, tuple[Path, bytes]]:
    root = tmp_path_factory.mktemp("models")
    made = {"detector": detector_model((FACE,)), "embedder": embedder_model()}
    paths = {}
    for name, data in made.items():
        paths[name] = root / f"{name}.onnx"
        paths[name].write_bytes(data)
    return {name: (paths[name], made[name]) for name in made}


@pytest.fixture(scope="module")
def two_providers(models: dict[str, tuple[Path, bytes]]) -> PerceptionPlan:
    """Per stage, a variant whose provider does not exist here, then one on the CPU."""
    (dpath, ddata), (epath, edata) = models["detector"], models["embedder"]
    dcomp, ecomp = uuid.uuid4(), uuid.uuid4()
    return plan_of(
        (
            planned(dpath, ddata, DETECTOR, MISSING, component=dcomp),
            planned(dpath, ddata, DETECTOR, CPU, component=dcomp),
        ),
        (
            planned(epath, edata, EMBEDDER, MISSING, component=ecomp),
            planned(epath, edata, EMBEDDER, CPU, component=ecomp),
        ),
    )


@pytest.fixture(scope="module")
def supervisor(two_providers: PerceptionPlan) -> Iterator[MLSupervisor]:
    running = supervisor_for(two_providers, POLICY)
    try:
        yield running
    finally:
        running.stop()


# --- a real worker -------------------------------------------------------------------------------


def test_detect_then_represent_runs_the_variant_whose_provider_exists(
    two_providers: PerceptionPlan, supervisor: MLSupervisor, new_id: SeededUUIDs
) -> None:
    client = PerceptionClient(supervisor, two_providers, new_id=new_id)
    found = client.detect(picture(), context=ExecutionContext(job_id="job-1"))
    (face,) = found.detections
    assert found.ran is two_providers.detector[1]  # (the missing provider was skipped)
    assert found.ran.provider == CPU
    result = client.represent(picture(), found.detections)
    assert result.ran is two_providers.embedder[1]
    (vector,) = result.vectors
    assert vector.detection_index == face.detection_index
    assert vector.vector.shape == (EMBEDDING_DIMENSION,)
    assert vector.vector.dtype == np.dtype("<f4")
    assert float(np.linalg.norm(vector.vector)) == pytest.approx(1.0, abs=1e-6)
    assert vector.normalization == alignment.NORMALIZATION
    again = client.represent(
        picture(), found.detections
    )  # (deterministic, and the worker is reused)
    assert np.array_equal(again.vectors[0].vector, vector.vector)


def test_a_picture_with_no_face_is_a_result_and_nothing_is_embedded(
    two_providers: PerceptionPlan, supervisor: MLSupervisor, new_id: SeededUUIDs
) -> None:
    client = PerceptionClient(supervisor, two_providers, new_id=new_id)
    empty = client.detect(np.zeros((480, 640, 3), np.uint8))
    assert empty.detections == ()
    assert empty.ran is two_providers.detector[1]
    nothing = client.represent(np.zeros((480, 640, 3), np.uint8), empty.detections)
    assert nothing.vectors == ()
    assert nothing.ran is None  # (no worker call was made)


def test_every_provider_missing_is_reported_with_a_reason_each_and_nothing_is_substituted(
    models: dict[str, tuple[Path, bytes]], new_id: SeededUUIDs
) -> None:
    (dpath, ddata), (epath, edata) = models["detector"], models["embedder"]
    component = uuid.uuid4()
    plan = plan_of(
        (
            planned(dpath, ddata, DETECTOR, MISSING, component=component),
            planned(dpath, ddata, DETECTOR, "AnotherMissingProvider", component=component),
        ),
        (planned(epath, edata, EMBEDDER, CPU, component=uuid.uuid4()),),
    )
    running = supervisor_for(plan, POLICY)
    try:
        with pytest.raises(RuntimeUnavailableError) as raised:
            PerceptionClient(running, plan, new_id=new_id).detect(picture())
        assert raised.value.what == "the face detector"
        assert len(raised.value.reasons) == 2
        assert MISSING in raised.value.reasons[0]
        assert "pkg-test" in raised.value.reasons[0]
        assert "AnotherMissingProvider" in raised.value.reasons[1]
    finally:
        running.stop()


def test_a_model_that_does_not_match_its_digest_is_an_error_not_a_reason_to_try_another(
    models: dict[str, tuple[Path, bytes]], new_id: SeededUUIDs
) -> None:
    (dpath, ddata), (epath, edata) = models["detector"], models["embedder"]
    component = uuid.uuid4()
    damaged = planned(dpath, b"not the model", DETECTOR, CPU, component=component)
    good = planned(dpath, ddata, DETECTOR, CPU, component=component)
    plan = plan_of((damaged, good), (planned(epath, edata, EMBEDDER, CPU, component=uuid.uuid4()),))
    running = supervisor_for(plan, POLICY)
    try:
        with pytest.raises(PerceptionError) as raised:
            PerceptionClient(running, plan, new_id=new_id).detect(picture())
        assert raised.value.code is MLErrorCode.COMPONENT_LOAD_FAILED
    finally:
        running.stop()


# --- scripted answers -------------------------------------------------------------------------


class Scripted:
    """A supervisor that answers from a script and remembers what it was asked and told."""

    def __init__(self, answer: Callable[[MLRequest], MLResponse]) -> None:
        self.answer = answer
        self.requests: list[MLRequest] = []
        self.released: list[str] = []

    def execute(self, request: MLRequest) -> MLResponse:
        self.requests.append(request)
        return self.answer(request)

    def release_output(self, request_id: str) -> None:
        self.released.append(request_id)


def variant(provider: str, kind: str = DETECTOR) -> PlannedVariant:
    return planned(Path("model.onnx"), b"x", kind, provider, component=uuid.uuid4())


def error_response(request: MLRequest, code: MLErrorCode, message: str = "no") -> MLResponse:
    return MLResponse(
        request.request_id, MLStatus.ERROR, request.operation, error=MLError(code, message)
    )


def ran(request: MLRequest, **override: str) -> ExecutionProvenance:
    fields = {
        "component_version_id": request.component,
        "runtime_variant_id": request.options["runtime_variant_id"],
        "provider": CPU,
        "device": "cpu",
    } | override
    return ExecutionProvenance(**fields)


def detected(request: MLRequest, count: int = 1) -> MLResponse:
    faces = tuple(Detection(0, n, (0.1, 0.1, 0.5, 0.5), 0.9, LANDMARKS) for n in range(count))
    return MLResponse(
        request.request_id,
        MLStatus.SUCCESS,
        request.operation,
        execution=ran(request),
        output=DetectFacesOutput(faces),
    )


def client_of(script: Scripted, plan: PerceptionPlan, new_id: SeededUUIDs) -> PerceptionClient:
    return PerceptionClient(cast(MLSupervisor, script), plan, new_id=new_id)


@pytest.mark.parametrize("code", sorted(PROVIDER_UNAVAILABLE))
def test_only_a_provider_that_cannot_run_moves_on_to_the_next_variant(
    code: MLErrorCode, new_id: SeededUUIDs
) -> None:
    first, second = variant(MISSING), variant(CPU)
    plan = plan_of((first, second), ())
    script = Scripted(
        lambda r: error_response(r, code, "cannot") if len(script.requests) == 1 else detected(r)
    )
    found = client_of(script, plan, new_id).detect(picture(64, 64))
    assert found.ran is second
    assert [r.options["runtime_variant_id"] for r in script.requests] == [
        str(first.runtime_variant_id),
        str(second.runtime_variant_id),
    ]


def test_the_two_provider_codes_are_exactly_these() -> None:
    assert PROVIDER_UNAVAILABLE == {
        MLErrorCode.RUNTIME_VARIANT_NOT_AVAILABLE,
        MLErrorCode.RUNTIME_INITIALIZATION_FAILED,
    }


@pytest.mark.parametrize(
    "code", [c for c in MLErrorCode if c not in PROVIDER_UNAVAILABLE], ids=lambda c: c.value
)
def test_every_other_error_is_raised_and_no_other_variant_is_tried(
    code: MLErrorCode, new_id: SeededUUIDs
) -> None:
    plan = plan_of((variant(CPU), variant(CPU)), ())
    script = Scripted(lambda r: error_response(r, code, "it failed"))
    with pytest.raises(PerceptionError) as raised:
        client_of(script, plan, new_id).detect(picture(64, 64))
    assert raised.value.code is code
    assert raised.value.message == "it failed"
    assert len(script.requests) == 1


def test_a_variant_ruled_out_stays_out_for_later_calls_and_the_reasons_are_kept(
    new_id: SeededUUIDs,
) -> None:
    first, second = variant(MISSING), variant(CPU)
    plan = plan_of((first, second), ())
    script = Scripted(
        lambda r: (
            error_response(r, MLErrorCode.RUNTIME_VARIANT_NOT_AVAILABLE, "no such provider")
            if r.options["runtime_variant_id"] == str(first.runtime_variant_id)
            else detected(r)
        )
    )
    client = client_of(script, plan, new_id)
    client.detect(picture(64, 64))
    client.detect(picture(64, 64))
    asked = [r.options["runtime_variant_id"] for r in script.requests]
    assert asked == [str(first.runtime_variant_id), str(second.runtime_variant_id)] + [
        str(second.runtime_variant_id)
    ]


def test_when_everything_is_ruled_out_the_reasons_name_each_variant(new_id: SeededUUIDs) -> None:
    plan = plan_of((variant(MISSING), variant("Other")), ())
    script = Scripted(
        lambda r: error_response(r, MLErrorCode.RUNTIME_INITIALIZATION_FAILED, "ran on the CPU")
    )
    client = client_of(script, plan, new_id)
    with pytest.raises(RuntimeUnavailableError) as raised:
        client.detect(picture(64, 64))
    assert [reason.split(" ")[0] for reason in raised.value.reasons] == [MISSING, "Other"]
    assert all("ran on the CPU" in reason for reason in raised.value.reasons)
    with pytest.raises(RuntimeUnavailableError):  # (and a second call asks nobody)
        client.detect(picture(64, 64))
    assert len(script.requests) == 2


def test_a_worker_failure_is_the_supervisors_to_report_and_nothing_is_retried(
    new_id: SeededUUIDs,
) -> None:
    plan = plan_of((variant(CPU), variant(CPU)), ())

    def die(request: MLRequest) -> MLResponse:
        raise WorkerFailedError("the worker died")

    script = Scripted(die)
    with pytest.raises(WorkerFailedError):
        client_of(script, plan, new_id).detect(picture(64, 64))
    assert len(script.requests) == 1


def test_an_answer_from_another_variant_is_refused_and_not_recorded_as_this_one(
    new_id: SeededUUIDs,
) -> None:
    plan = plan_of((variant(CPU),), ())
    other = str(uuid.uuid4())
    script = Scripted(
        lambda r: MLResponse(
            r.request_id,
            MLStatus.SUCCESS,
            r.operation,
            execution=ran(r, runtime_variant_id=other),
            output=DetectFacesOutput(()),
        )
    )
    with pytest.raises(PerceptionError) as raised:
        client_of(script, plan, new_id).detect(picture(64, 64))
    assert raised.value.code is MLErrorCode.INTERNAL_WORKER_ERROR
    assert other in raised.value.message
    assert script.released == [script.requests[0].request_id]


def test_an_answer_for_another_component_is_refused_too(new_id: SeededUUIDs) -> None:
    plan = plan_of((variant(CPU),), ())
    script = Scripted(
        lambda r: MLResponse(
            r.request_id,
            MLStatus.SUCCESS,
            r.operation,
            execution=ran(r, component_version_id=str(uuid.uuid4())),
            output=DetectFacesOutput(()),
        )
    )
    with pytest.raises(PerceptionError):
        client_of(script, plan, new_id).detect(picture(64, 64))


def test_the_pixels_segment_is_released_when_the_call_ends_either_way(new_id: SeededUUIDs) -> None:
    plan = plan_of((variant(CPU),), ())
    script = Scripted(lambda r: detected(r))
    client_of(script, plan, new_id).detect(picture(64, 64))
    failing = Scripted(lambda r: error_response(r, MLErrorCode.INFERENCE_FAILED))
    with pytest.raises(PerceptionError):
        client_of(failing, plan, new_id).detect(picture(64, 64))
    for asked in (script, failing):
        (request,) = asked.requests
        (image,) = request.input.images
        with pytest.raises(ContractError) as raised:
            AttachedSegment(image)
        assert raised.value.code is MLErrorCode.SHARED_MEMORY_UNAVAILABLE


def test_pixels_must_be_uint8(new_id: SeededUUIDs) -> None:
    plan = plan_of((variant(CPU),), ())
    script = Scripted(lambda r: detected(r))
    with pytest.raises(ValueError, match="uint8"):
        client_of(script, plan, new_id).detect(picture(8, 8).astype(np.float32))
    assert script.requests == []


class Embedder:
    """A stand-in for the worker's side of GENERATE_REPRESENTATIONS: its own segments."""

    def __init__(self, new_id: SeededUUIDs, *, dimension: int = EMBEDDING_DIMENSION) -> None:
        self.ledger = SegmentLedger(new_id=SeededUUIDs(99))
        self.dimension = dimension

    def answer(
        self,
        request: MLRequest,
        *,
        skip: tuple[int, ...] = (),
        repeat: bool = False,
        dtype: str = "float32",
    ) -> MLResponse:
        faces = [f for f in request.input.faces if f.face_index not in skip]  # type: ignore[union-attr]
        results = []
        for face in faces * (2 if repeat else 1):
            segment = self.ledger.create(dtype, (self.dimension,))
            segment.write(np.full(self.dimension, face.face_index + 1, dtype))
            results.append(
                RepresentationResult(
                    0, face.face_index, self.dimension, dtype, "L2_NORMALIZED", segment.descriptor
                )
            )
        return MLResponse(
            request.request_id,
            MLStatus.SUCCESS,
            request.operation,
            execution=ran(request),
            output=GenerateRepresentationsOutput(tuple(results)),
        )


def three_faces() -> tuple[Detection, ...]:
    return tuple(Detection(0, n, (0.1, 0.1, 0.5, 0.5), 0.9, LANDMARKS) for n in (4, 7, 9))


def test_vectors_come_back_per_face_in_the_order_asked_and_outputs_are_released(
    new_id: SeededUUIDs,
) -> None:
    plan = plan_of((), (variant(CPU, EMBEDDER),))
    side = Embedder(new_id)
    script = Scripted(side.answer)
    with side.ledger:
        out = client_of(script, plan, new_id).represent(picture(64, 64), three_faces())
    assert [v.detection_index for v in out.vectors] == [4, 7, 9]
    assert [float(v.vector[0]) for v in out.vectors] == [5.0, 8.0, 10.0]
    assert script.released == [script.requests[0].request_id]
    (request,) = script.requests
    assert [f.face_index for f in request.input.faces] == [4, 7, 9]  # type: ignore[union-attr]
    assert all(f.input_index == 0 for f in request.input.faces)  # type: ignore[union-attr]


@pytest.mark.parametrize(
    "answer",
    [
        pytest.param(lambda side, r: side.answer(r, skip=(7,)), id="a face is missing"),
        pytest.param(lambda side, r: side.answer(r, repeat=True), id="a face is answered twice"),
    ],
)
def test_an_answer_that_is_not_exactly_for_the_faces_asked_is_refused_and_still_released(
    answer: Callable[[Embedder, MLRequest], MLResponse], new_id: SeededUUIDs
) -> None:
    plan = plan_of((), (variant(CPU, EMBEDDER),))
    side = Embedder(new_id)
    script = Scripted(lambda r: answer(side, r))
    with side.ledger, pytest.raises(PerceptionError) as raised:
        client_of(script, plan, new_id).represent(picture(64, 64), three_faces())
    assert raised.value.code is MLErrorCode.INTERNAL_WORKER_ERROR
    assert script.released == [script.requests[0].request_id]


def test_a_vector_of_the_wrong_length_is_refused_and_still_released(new_id: SeededUUIDs) -> None:
    plan = plan_of((), (variant(CPU, EMBEDDER),))
    side = Embedder(new_id, dimension=EMBEDDING_DIMENSION + 1)
    script = Scripted(side.answer)
    with side.ledger, pytest.raises(PerceptionError) as raised:
        client_of(script, plan, new_id).represent(picture(64, 64), three_faces())
    assert str(EMBEDDING_DIMENSION) in raised.value.message
    assert script.released == [script.requests[0].request_id]


def test_a_vector_that_is_not_float32_is_refused(new_id: SeededUUIDs) -> None:
    plan = plan_of((), (variant(CPU, EMBEDDER),))
    side = Embedder(new_id)
    script = Scripted(lambda r: side.answer(r, dtype="float64"))
    with side.ledger, pytest.raises(PerceptionError) as raised:
        client_of(script, plan, new_id).represent(picture(64, 64), three_faces())
    assert "float64" in raised.value.message


def test_a_detection_without_landmarks_is_the_workers_to_refuse(new_id: SeededUUIDs) -> None:
    plan = plan_of((), (variant(CPU, EMBEDDER),))
    script = Scripted(
        lambda r: error_response(r, MLErrorCode.INVALID_INPUT, "a representation needs landmarks")
    )
    bare = (Detection(0, 0, (0.1, 0.1, 0.5, 0.5), 0.9),)
    with pytest.raises(PerceptionError) as raised:
        client_of(script, plan, new_id).represent(picture(64, 64), bare)
    assert raised.value.code is MLErrorCode.INVALID_INPUT
    assert script.released == []  # (an error has no output to release)


def test_the_execution_context_travels_with_the_request_for_diagnostics(
    new_id: SeededUUIDs,
) -> None:
    plan = plan_of((variant(CPU),), (variant(CPU, EMBEDDER),))
    side = Embedder(new_id)
    script = Scripted(
        lambda r: (
            detected(r)
            if r.component == str(plan.detector[0].component_version_id)
            else side.answer(r)
        )
    )
    context = ExecutionContext(job_id="job-1", processing_run_id="run-1")
    client = client_of(script, plan, new_id)
    with side.ledger:
        client.detect(picture(64, 64), context=context)
        client.represent(picture(64, 64), three_faces(), context=context)
        client.detect(picture(64, 64))
    assert [r.execution_context for r in script.requests] == [context, context, ExecutionContext()]
