"""TST-038 and TST-039: detection and representation through ONNX Runtime.

Generated fixture models (never real weights, see `tests/fixtures/onnx_models.py`) run through the
worker's real code: shared-memory images in, letterbox, a real ONNX session built from verified
bytes, decode or align, a canonical vector in a worker-made segment out. The last tests do it in a
real worker process behind the supervisor.
"""

import hashlib
import json
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import numpy as np
import onnxruntime as ort
import pytest

from backend.infrastructure.resources.shared_memory import AttachedSegment, SegmentLedger
from backend.ml.contracts.messages import (
    DetectFacesInput,
    DetectFacesOutput,
    ExecutionProvenance,
    FaceGeometry,
    GenerateRepresentationsInput,
    GenerateRepresentationsOutput,
    MLRequest,
    MLResponse,
)
from backend.ml.contracts.protocol import ContractError, MLErrorCode, MLOperation, MLStatus
from backend.ml.perception import alignment
from backend.ml.supervisor.process import ProcessWorker
from backend.ml.supervisor.supervisor import MLSupervisor, SupervisorPolicy
from backend.ml.worker.loop import Handler, HandlerContext, WorkerError
from backend.ml.worker.main import load_handlers
from backend.ml.worker.onnx_session import load_session
from backend.ml.worker.perception_handlers import (
    CONTRACTS,
    DETECTOR,
    EMBEDDER,
    ConfigError,
    build_handlers,
    parse_config,
)
from tests.fixtures.deterministic import SeededUUIDs
from tests.fixtures.onnx_models import (
    EMBEDDING_DIMENSION,
    FACE_OFFSETS,
    PlantedFace,
    detector_model,
    embedder_model,
    two_input_model,
)

CPU = "CPUExecutionProvider"
FACTORY = "backend.ml.worker.perception_handlers:build_handlers"
FACE = PlantedFace(level=0, column=40, row=30)  # centre (320, 240) in the 640 input, stride 8


def picture(width: int, height: int, seed: int = 3) -> np.ndarray[Any, Any]:
    rng = np.random.default_rng(seed)
    return rng.integers(30, 220, (height, width, 3), dtype=np.uint8)


def variant(
    path: Path,
    data: bytes,
    *,
    kind: str = DETECTOR,
    component: str | None = None,
    runtime_variant: str | None = None,
    provider: str = CPU,
    dimension: int | None = None,
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "component_version_id": component or f"cv-{kind}",
        "contract": CONTRACTS[kind],
        "kind": kind,
        "runtime_variant_id": runtime_variant or f"rv-{kind}-{provider}",
        "model_path": str(path),
        "sha256": hashlib.sha256(data).hexdigest(),
        "provider": provider,
        "device": "cpu",
    }
    if dimension is not None:
        entry["dimension"] = dimension
    return entry


def config_of(*variants: dict[str, Any]) -> str:
    return json.dumps({"variants": list(variants)})


@pytest.fixture
def models(tmp_path: Path) -> dict[str, Any]:
    """The detector (one planted face) and the embedder on disk, and a config naming both."""
    detector, embedder = detector_model((FACE,)), embedder_model()
    (tmp_path / "detector.onnx").write_bytes(detector)
    (tmp_path / "embedder.onnx").write_bytes(embedder)
    entries = [
        variant(tmp_path / "detector.onnx", detector),
        variant(tmp_path / "embedder.onnx", embedder, kind=EMBEDDER, dimension=EMBEDDING_DIMENSION),
    ]
    return {"config": config_of(*entries), "entries": entries, "dir": tmp_path}


@pytest.fixture
def ledger(new_id: SeededUUIDs) -> Iterator[SegmentLedger]:
    with SegmentLedger(new_id=new_id) as made:
        yield made


def image_segment(ledger: SegmentLedger, pixels: np.ndarray[Any, Any]) -> Any:
    segment = ledger.create("uint8", pixels.shape)
    segment.write(pixels)
    return segment.descriptor


def detect_request(
    images: tuple[Any, ...], component: str = f"cv-{DETECTOR}", **options: Any
) -> MLRequest:
    return MLRequest("d-1", MLOperation.DETECT_FACES, component, DetectFacesInput(images), options)


def represent_request(
    images: tuple[Any, ...],
    faces: tuple[FaceGeometry, ...],
    component: str = f"cv-{EMBEDDER}",
    **options: Any,
) -> MLRequest:
    return MLRequest(
        "r-1",
        MLOperation.GENERATE_REPRESENTATIONS,
        component,
        GenerateRepresentationsInput(images, faces),
        options,
    )


def run(handlers: dict[MLOperation, Handler], request: MLRequest, ledger: SegmentLedger) -> Any:
    return handlers[request.operation](request, HandlerContext(ledger)).output


def template_landmarks(scale: float, size: int) -> tuple[tuple[float, float], ...]:
    return tuple((float(x * scale / size), float(y * scale / size)) for x, y in alignment.TEMPLATE)


def vector_of(descriptor: Any) -> np.ndarray[Any, Any]:
    with AttachedSegment(descriptor) as segment:
        return segment.copy()


# --- the configuration ---------------------------------------------------------------------------


def test_a_valid_configuration_is_read(models: dict[str, Any]) -> None:
    detector, embedder = parse_config(models["config"])
    assert (detector.kind, detector.provider, detector.dimension) == (DETECTOR, CPU, None)
    assert embedder.dimension == EMBEDDING_DIMENSION
    assert detector.sha256 == bytes.fromhex(models["entries"][0]["sha256"])


@pytest.mark.parametrize(
    "mutate",
    [
        lambda e: e.pop("provider"),
        lambda e: e.update(extra=1),
        lambda e: e.update(kind="FACE_QUALITY"),
        lambda e: e.update(sha256="zz" * 32),
        lambda e: e.update(sha256="ab" * 31),
        lambda e: e.update(sha256="ab" * 32 + "c"),  # one character too many
        lambda e: e.update(sha256="x" + "ab" * 32),
        lambda e: e.update(
            sha256="ab" * 32 + chr(10)
        ),  # a trailing newline: `$` alone would let it by
        lambda e: e.update(sha256="AB" * 32),  # upper case: the manifest refuses it too
        lambda e: e.update(sha256=" ".join(["ab"] * 32)),  # (`bytes.fromhex` would accept this)
        lambda e: e.pop("contract"),
        lambda e: e.update(contract=""),
        lambda e: e.update(device=""),
        lambda e: e.update(model_path=5),
        lambda e: e.update(dimension=4),  # a detector has none
    ],
)
def test_a_bad_detector_entry_is_refused(
    models: dict[str, Any], mutate: Callable[[dict[str, Any]], Any]
) -> None:
    entry = dict(models["entries"][0])
    mutate(entry)
    with pytest.raises(ConfigError):
        parse_config(config_of(entry))


@pytest.mark.parametrize("dimension", [None, 0, -3, True, 2.5, "16"])
def test_an_embedder_needs_a_positive_integer_dimension(
    models: dict[str, Any], dimension: Any
) -> None:
    entry = dict(models["entries"][1])
    if dimension is None:
        del entry["dimension"]
    else:
        entry["dimension"] = dimension
    with pytest.raises(ConfigError):
        parse_config(config_of(entry))


@pytest.mark.parametrize("text", ["not json", "[]", '{"variants": 1}', '{"variants": [], "x": 1}'])
def test_a_configuration_that_is_not_a_list_of_variants_is_refused(text: str) -> None:
    with pytest.raises(ConfigError):
        parse_config(text)


def test_the_contracts_served_are_the_two_reference_ones() -> None:
    assert CONTRACTS == {
        DETECTOR: "scrfd-letterbox-v1",
        EMBEDDER: "arcface-112-similarity-v1",
    }


def test_a_variant_that_needs_another_pipeline_is_not_served_and_never_reported_as_served(
    models: dict[str, Any], ledger: SegmentLedger
) -> None:
    other = dict(models["entries"][0], contract="some-other-detector-v7")
    handlers = build_handlers(config_of(other))
    with pytest.raises(WorkerError, match="some-other-detector-v7") as refused:
        run(handlers, detect_request((image_segment(ledger, picture(640, 480)),)), ledger)
    assert refused.value.code is MLErrorCode.COMPONENT_NOT_AVAILABLE
    other_embedder = dict(models["entries"][1], contract="some-other-embedder-v7")
    handlers = build_handlers(config_of(other_embedder))
    face = FaceGeometry(0, 0, (0.2, 0.2, 0.8, 0.8), template_landmarks(2, 224))
    with pytest.raises(WorkerError, match="some-other-embedder-v7") as refused:
        run(
            handlers,
            represent_request((image_segment(ledger, picture(224, 224)),), (face,)),
            ledger,
        )
    assert refused.value.code is MLErrorCode.COMPONENT_NOT_AVAILABLE


def test_a_variant_with_the_right_contract_is_still_served_beside_one_with_another(
    models: dict[str, Any], ledger: SegmentLedger
) -> None:
    right = models["entries"][0]
    wrong = dict(right, runtime_variant_id="rv-wrong", contract="some-other-detector-v7")
    handlers = build_handlers(config_of(wrong, right))
    image = image_segment(ledger, picture(640, 480))
    # unnamed: only the served one is a candidate, so there is nothing to choose between
    assert len(run(handlers, detect_request((image,)), ledger).detections) == 1
    named = detect_request((image,), runtime_variant_id="rv-wrong")
    with pytest.raises(WorkerError) as refused:
        run(handlers, named, ledger)
    assert refused.value.code is MLErrorCode.COMPONENT_NOT_AVAILABLE


def test_a_variant_id_may_be_used_only_once(models: dict[str, Any]) -> None:
    twin = dict(models["entries"][0])
    with pytest.raises(ConfigError, match="twice"):
        parse_config(config_of(twin, twin))


def test_only_the_operations_there_is_a_variant_for_are_served(models: dict[str, Any]) -> None:
    assert set(build_handlers(config_of(models["entries"][0]))) == {MLOperation.DETECT_FACES}
    assert set(build_handlers(config_of(models["entries"][1]))) == {
        MLOperation.GENERATE_REPRESENTATIONS
    }
    assert set(build_handlers(models["config"])) == set(MLOperation)


def test_the_worker_entry_hands_the_configuration_to_the_factory(models: dict[str, Any]) -> None:
    assert set(load_handlers(FACTORY, models["config"])) == set(MLOperation)


# --- detection (TST-038) -------------------------------------------------------------------------


def test_the_planted_face_is_found_where_it_is(
    models: dict[str, Any], ledger: SegmentLedger
) -> None:
    handlers = build_handlers(models["config"])
    request = detect_request((image_segment(ledger, picture(640, 480)),))
    result = handlers[MLOperation.DETECT_FACES](request, HandlerContext(ledger))
    assert isinstance(result.output, DetectFacesOutput)
    (face,) = result.output.detections
    assert (face.input_index, face.detection_index) == (0, 0)
    assert face.score == pytest.approx(0.9)
    assert face.box == pytest.approx((304 / 640, 224 / 480, 336 / 640, 256 / 480))
    expected = [(320 + dx * 8, 240 + dy * 8) for dx, dy in np.reshape(FACE_OFFSETS, (5, 2))]
    assert np.array(face.landmarks).reshape(-1) == pytest.approx(
        [v for x, y in expected for v in (x / 640, y / 480)]
    )
    assert result.execution.provider == CPU
    assert (result.execution.component_version_id, result.execution.device) == (
        f"cv-{DETECTOR}",
        "cpu",
    )


def test_a_larger_image_is_scaled_and_the_face_comes_back_in_its_own_coordinates(
    models: dict[str, Any], ledger: SegmentLedger
) -> None:
    handlers = build_handlers(models["config"])
    request = detect_request((image_segment(ledger, picture(1280, 960)),))
    (face,) = run(handlers, request, ledger).detections
    assert face.box == pytest.approx((608 / 1280, 448 / 960, 672 / 1280, 512 / 960))


def test_an_image_with_no_light_has_no_face_and_that_is_a_success(
    models: dict[str, Any], ledger: SegmentLedger
) -> None:
    handlers = build_handlers(models["config"])
    request = detect_request((image_segment(ledger, np.zeros((480, 640, 3), np.uint8)),))
    assert run(handlers, request, ledger) == DetectFacesOutput(())


def test_several_images_keep_their_own_indexes(
    models: dict[str, Any], ledger: SegmentLedger
) -> None:
    handlers = build_handlers(models["config"])
    images = (
        image_segment(ledger, np.zeros((64, 64, 3), np.uint8)),
        image_segment(ledger, picture(640, 640)),
        image_segment(ledger, picture(320, 320)),
    )
    found = run(handlers, detect_request(images), ledger).detections
    assert [d.input_index for d in found] == [1, 2]
    assert found[0].box == pytest.approx((304 / 640, 224 / 640, 336 / 640, 256 / 640))
    assert found[1].box == pytest.approx((304 / 640, 224 / 640, 336 / 640, 256 / 640))


def test_two_planted_faces_come_back_best_first_numbered_per_image(
    tmp_path: Path, ledger: SegmentLedger
) -> None:
    data = detector_model((PlantedFace(0, 40, 30, score=0.7), PlantedFace(1, 10, 10, score=0.95)))
    (tmp_path / "d.onnx").write_bytes(data)
    handlers = build_handlers(config_of(variant(tmp_path / "d.onnx", data)))
    request = detect_request((image_segment(ledger, picture(640, 640)),))
    found = run(handlers, request, ledger).detections
    assert [(d.detection_index, round(d.score, 2)) for d in found] == [(0, 0.95), (1, 0.7)]


def test_a_detection_answers_only_the_images_the_request_contained(
    models: dict[str, Any], ledger: SegmentLedger
) -> None:
    request = detect_request((image_segment(ledger, picture(640, 480)),))
    result = build_handlers(models["config"])[MLOperation.DETECT_FACES](
        request, HandlerContext(ledger)
    )
    response = MLResponse(
        request_id=request.request_id,
        status=MLStatus.SUCCESS,
        operation=request.operation,
        execution=ExecutionProvenance("c", "v", "p", "d"),
        output=result.output,
    )
    response.check_answers(request)  # what the loop does before it answers


# --- representation (TST-039) --------------------------------------------------------------------


def test_a_representation_is_a_unit_float32_vector_of_the_models_dimension(
    models: dict[str, Any], ledger: SegmentLedger
) -> None:
    handlers = build_handlers(models["config"])
    image = image_segment(ledger, picture(224, 224))
    face = FaceGeometry(0, 0, (0.2, 0.2, 0.8, 0.8), template_landmarks(2, 224))
    before = set(ledger.names)
    result = handlers[MLOperation.GENERATE_REPRESENTATIONS](
        represent_request((image,), (face,)), HandlerContext(ledger)
    )
    assert isinstance(result.output, GenerateRepresentationsOutput)
    (representation,) = result.output.representations
    assert (representation.input_index, representation.face_index) == (0, 0)
    assert representation.dimension == EMBEDDING_DIMENSION
    assert representation.dtype == "float32"
    assert representation.normalization == "L2_NORMALIZED"
    assert len(set(ledger.names) - before) == 1  # exactly one segment was made for it
    vector = vector_of(representation.embedding)
    assert vector.dtype == np.dtype("<f4")
    assert vector.shape == (EMBEDDING_DIMENSION,)
    assert float(np.linalg.norm(vector)) == pytest.approx(1.0, abs=1e-6)
    assert np.isfinite(vector).all()
    assert result.execution.runtime_variant_id == f"rv-{EMBEDDER}-{CPU}"


def test_the_same_face_gives_the_same_vector_and_another_face_another(
    models: dict[str, Any], ledger: SegmentLedger
) -> None:
    handlers = build_handlers(models["config"])
    first = image_segment(ledger, picture(224, 224, seed=1))
    other = image_segment(ledger, picture(224, 224, seed=2))
    landmarks = template_landmarks(2, 224)
    faces = (
        FaceGeometry(0, 0, (0.2, 0.2, 0.8, 0.8), landmarks),
        FaceGeometry(0, 1, (0.2, 0.2, 0.8, 0.8), landmarks),
        FaceGeometry(1, 0, (0.2, 0.2, 0.8, 0.8), landmarks),
    )
    out = run(handlers, represent_request((first, other), faces), ledger).representations
    a, b, c = (vector_of(r.embedding) for r in out)
    assert np.array_equal(a, b)
    assert float(a @ c) < 0.99
    assert [(r.input_index, r.face_index) for r in out] == [(0, 0), (0, 1), (1, 0)]


def test_a_face_without_landmarks_cannot_be_represented(
    models: dict[str, Any], ledger: SegmentLedger
) -> None:
    handlers = build_handlers(models["config"])
    request = represent_request(
        (image_segment(ledger, picture(224, 224)),), (FaceGeometry(0, 0, (0.2, 0.2, 0.8, 0.8)),)
    )
    with pytest.raises(ContractError) as refused:
        run(handlers, request, ledger)
    assert refused.value.code is MLErrorCode.INVALID_INPUT


def test_a_model_that_answers_a_zero_vector_is_a_model_failure_and_leaves_no_segment(
    tmp_path: Path, ledger: SegmentLedger
) -> None:
    data = embedder_model(zero=True)
    (tmp_path / "e.onnx").write_bytes(data)
    handlers = build_handlers(
        config_of(variant(tmp_path / "e.onnx", data, kind=EMBEDDER, dimension=EMBEDDING_DIMENSION))
    )
    image = image_segment(ledger, picture(224, 224))
    before = set(ledger.names)
    request = represent_request(
        (image,), (FaceGeometry(0, 0, (0.2, 0.2, 0.8, 0.8), template_landmarks(2, 224)),)
    )
    with pytest.raises(ContractError) as refused:
        run(handlers, request, ledger)
    assert refused.value.code is MLErrorCode.INFERENCE_FAILED
    assert set(ledger.names) == before


# --- choosing and loading a variant -------------------------------------------------------------


def test_a_request_for_a_component_that_is_not_configured_is_not_available(
    models: dict[str, Any], ledger: SegmentLedger
) -> None:
    handlers = build_handlers(models["config"])
    request = detect_request((image_segment(ledger, picture(64, 64)),), component="cv-other")
    with pytest.raises(WorkerError) as refused:
        run(handlers, request, ledger)
    assert refused.value.code is MLErrorCode.COMPONENT_NOT_AVAILABLE


def test_a_detector_component_cannot_be_asked_to_embed(
    models: dict[str, Any], ledger: SegmentLedger
) -> None:
    handlers = build_handlers(models["config"])
    request = represent_request(
        (image_segment(ledger, picture(224, 224)),),
        (FaceGeometry(0, 0, (0.2, 0.2, 0.8, 0.8), template_landmarks(2, 224)),),
        component=f"cv-{DETECTOR}",
    )
    with pytest.raises(WorkerError) as refused:
        run(handlers, request, ledger)
    assert refused.value.code is MLErrorCode.COMPONENT_NOT_AVAILABLE


def test_several_variants_of_one_component_need_one_to_be_named(
    models: dict[str, Any], ledger: SegmentLedger
) -> None:
    first = models["entries"][0]
    second = dict(first, runtime_variant_id="rv-second", provider="NoSuchExecutionProvider")
    handlers = build_handlers(config_of(first, second))
    image = image_segment(ledger, picture(640, 480))
    with pytest.raises(WorkerError) as refused:
        run(handlers, detect_request((image,)), ledger)
    assert refused.value.code is MLErrorCode.INVALID_REQUEST
    named = detect_request((image,), runtime_variant_id=first["runtime_variant_id"])
    assert len(run(handlers, named, ledger).detections) == 1
    with pytest.raises(WorkerError) as unknown:
        run(handlers, detect_request((image,), runtime_variant_id="rv-nope"), ledger)
    assert unknown.value.code is MLErrorCode.COMPONENT_NOT_AVAILABLE


def test_a_provider_that_is_not_available_is_reported_not_replaced_by_the_cpu(
    models: dict[str, Any], ledger: SegmentLedger
) -> None:
    entry = dict(models["entries"][0], provider="NoSuchExecutionProvider")
    handlers = build_handlers(config_of(entry))
    with pytest.raises(WorkerError) as refused:
        run(handlers, detect_request((image_segment(ledger, picture(64, 64)),)), ledger)
    assert refused.value.code is MLErrorCode.RUNTIME_VARIANT_NOT_AVAILABLE


def test_a_session_is_loaded_once_and_then_reused(
    models: dict[str, Any], ledger: SegmentLedger
) -> None:
    loads: list[str] = []

    def loader(path: Path, digest: bytes, provider: str) -> ort.InferenceSession:
        loads.append(path.name)
        return load_session(path, digest, provider)

    handlers = build_handlers(models["config"], loader=loader)
    image = image_segment(ledger, picture(640, 480))
    for _ in range(3):
        run(handlers, detect_request((image,)), ledger)
    assert loads == ["detector.onnx"]


def test_nothing_is_loaded_until_a_request_needs_it(models: dict[str, Any]) -> None:
    def loader(path: Path, digest: bytes, provider: str) -> ort.InferenceSession:
        raise AssertionError("loaded at start")

    build_handlers(models["config"], loader=loader)


def test_a_failed_load_is_tried_again_by_the_next_request(
    models: dict[str, Any], ledger: SegmentLedger
) -> None:
    image = image_segment(ledger, picture(640, 480))
    path: Path = models["dir"] / "detector.onnx"
    good = path.read_bytes()
    handlers = build_handlers(models["config"])
    path.write_bytes(b"damaged")
    with pytest.raises(WorkerError):
        run(handlers, detect_request((image,)), ledger)
    path.write_bytes(good)
    assert len(run(handlers, detect_request((image,)), ledger).detections) == 1


def test_a_changed_model_file_is_refused_by_its_digest(
    models: dict[str, Any], ledger: SegmentLedger
) -> None:
    (models["dir"] / "detector.onnx").write_bytes(detector_model(()))  # another model
    handlers = build_handlers(models["config"])
    with pytest.raises(WorkerError, match="digest") as refused:
        run(handlers, detect_request((image_segment(ledger, picture(64, 64)),)), ledger)
    assert refused.value.code is MLErrorCode.COMPONENT_LOAD_FAILED


def test_a_missing_model_file_is_a_load_failure(
    models: dict[str, Any], ledger: SegmentLedger
) -> None:
    (models["dir"] / "detector.onnx").unlink()
    handlers = build_handlers(models["config"])
    with pytest.raises(WorkerError, match="cannot be read") as refused:
        run(handlers, detect_request((image_segment(ledger, picture(64, 64)),)), ledger)
    assert refused.value.code is MLErrorCode.COMPONENT_LOAD_FAILED


def test_a_model_path_that_cannot_be_read_as_a_file_is_a_load_failure(
    tmp_path: Path, ledger: SegmentLedger
) -> None:
    folder = tmp_path / "folder.onnx"
    folder.mkdir()
    handlers = build_handlers(config_of(variant(folder, b"")))
    with pytest.raises(WorkerError, match="cannot be read") as refused:
        run(handlers, detect_request((image_segment(ledger, picture(64, 64)),)), ledger)
    assert refused.value.code is MLErrorCode.COMPONENT_LOAD_FAILED


def test_an_embedder_whose_output_length_is_symbolic_is_accepted_and_checked_per_vector(
    tmp_path: Path, ledger: SegmentLedger
) -> None:
    class Described:
        name = "input"
        shape = [1, "length"]  # what a model with a dynamic output length reports

    class Session:
        def get_inputs(self) -> list[Described]:
            return [Described()]

        def get_outputs(self) -> list[Described]:
            return [Described()]

        def run(self, names: Any, feeds: Any) -> list[Any]:
            return [np.ones((1, EMBEDDING_DIMENSION), np.float32)]

    entry = variant(tmp_path / "unused.onnx", b"", kind=EMBEDDER, dimension=EMBEDDING_DIMENSION)
    handlers = build_handlers(config_of(entry), loader=lambda path, digest, provider: Session())
    image = image_segment(ledger, picture(224, 224))
    face = FaceGeometry(0, 0, (0.2, 0.2, 0.8, 0.8), template_landmarks(2, 224))
    (result,) = run(handlers, represent_request((image,), (face,)), ledger).representations
    assert result.dimension == EMBEDDING_DIMENSION


def test_bytes_that_are_not_a_model_are_a_load_failure_even_with_the_right_digest(
    tmp_path: Path, ledger: SegmentLedger
) -> None:
    junk = b"this is not an ONNX model"
    (tmp_path / "j.onnx").write_bytes(junk)
    handlers = build_handlers(config_of(variant(tmp_path / "j.onnx", junk)))
    with pytest.raises(WorkerError, match="cannot be loaded") as refused:
        run(handlers, detect_request((image_segment(ledger, picture(64, 64)),)), ledger)
    assert refused.value.code is MLErrorCode.COMPONENT_LOAD_FAILED


@pytest.mark.parametrize(
    ("kind", "data", "dimension", "why"),
    [
        (DETECTOR, embedder_model(), None, "outputs"),
        (DETECTOR, two_input_model(), None, "one input"),
        (EMBEDDER, embedder_model(), EMBEDDING_DIMENSION + 1, "configuration says"),
        (EMBEDDER, two_input_model(), 1, "one input"),
    ],
)
def test_a_model_that_cannot_be_what_the_configuration_says_is_refused_when_loaded(
    tmp_path: Path, ledger: SegmentLedger, kind: str, data: bytes, dimension: int | None, why: str
) -> None:
    (tmp_path / "m.onnx").write_bytes(data)
    handlers = build_handlers(
        config_of(variant(tmp_path / "m.onnx", data, kind=kind, dimension=dimension))
    )
    image = image_segment(ledger, picture(224, 224))
    if kind == DETECTOR:
        request = detect_request((image,))
    else:
        face = FaceGeometry(0, 0, (0.2, 0.2, 0.8, 0.8), template_landmarks(2, 224))
        request = represent_request((image,), (face,))
    with pytest.raises(WorkerError, match=why) as refused:
        run(handlers, request, ledger)
    assert refused.value.code is MLErrorCode.COMPONENT_LOAD_FAILED


# --- the session itself --------------------------------------------------------------------------


def test_the_session_is_made_from_the_bytes_that_were_hashed_not_from_the_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = embedder_model()
    path = tmp_path / "m.onnx"
    path.write_bytes(data)
    seen: list[Any] = []
    real = ort.InferenceSession

    def spy(model: Any, *args: Any, **kwargs: Any) -> Any:
        seen.append(model)
        return real(model, *args, **kwargs)

    monkeypatch.setattr(ort, "InferenceSession", spy)
    load_session(path, hashlib.sha256(data).digest(), CPU)
    assert seen == [data]


def test_a_session_that_runs_on_another_provider_than_asked_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = embedder_model()
    path = tmp_path / "m.onnx"
    path.write_bytes(data)

    class Fell:  # what ONNX Runtime does when an accelerator will not start: quietly use the CPU
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def get_providers(self) -> list[str]:
            return [CPU]

    monkeypatch.setattr(ort, "get_available_providers", lambda: ["CUDAExecutionProvider"])
    monkeypatch.setattr(ort, "InferenceSession", Fell)
    with pytest.raises(WorkerError, match="was requested") as refused:
        load_session(path, hashlib.sha256(data).digest(), "CUDAExecutionProvider")
    assert refused.value.code is MLErrorCode.RUNTIME_INITIALIZATION_FAILED


# --- in a real worker process, behind the supervisor ---------------------------------------------

POLICY = SupervisorPolicy(
    handshake_timeout=120,
    request_timeout=120,
    ping_timeout=10,
    shutdown_timeout=10,
    max_restarts=1,
    restart_window=600,
)


def test_detect_then_represent_in_a_real_worker_process(
    models: dict[str, Any], ledger: SegmentLedger
) -> None:
    worker_config = models["config"]
    workers: list[ProcessWorker] = []

    def spawn() -> ProcessWorker:
        workers.append(ProcessWorker(FACTORY, worker_config))
        return workers[-1]

    supervisor = MLSupervisor(spawn, POLICY)
    try:
        image = image_segment(ledger, picture(640, 480))
        found = supervisor.execute(detect_request((image,)))
        assert found.status is MLStatus.SUCCESS
        assert isinstance(found.output, DetectFacesOutput)
        (face,) = found.output.detections
        assert supervisor.capabilities == sorted(op.value for op in MLOperation)
        geometry = FaceGeometry(0, 0, face.box, face.landmarks)
        answer = supervisor.execute(represent_request((image,), (geometry,)))
        assert answer.status is MLStatus.SUCCESS
        assert isinstance(answer.output, GenerateRepresentationsOutput)
        (representation,) = answer.output.representations
        vector = vector_of(representation.embedding)  # (the worker made it; we read it)
        assert vector.shape == (EMBEDDING_DIMENSION,)
        assert float(np.linalg.norm(vector)) == pytest.approx(1.0, abs=1e-6)
        supervisor.release_output(answer.request_id)
    finally:
        supervisor.stop()
        for worker in workers:
            worker.kill()


def test_a_variant_that_cannot_load_in_the_real_worker_is_an_error_answer_not_a_dead_worker(
    models: dict[str, Any], ledger: SegmentLedger
) -> None:
    entry = dict(models["entries"][0], provider="NoSuchExecutionProvider")
    workers: list[ProcessWorker] = []

    def spawn() -> ProcessWorker:
        workers.append(ProcessWorker(FACTORY, config_of(entry)))
        return workers[-1]

    supervisor = MLSupervisor(spawn, POLICY)
    try:
        image = image_segment(ledger, picture(64, 64))
        response = supervisor.execute(detect_request((image,)))
        assert response.status is MLStatus.ERROR
        assert response.error is not None
        assert response.error.code is MLErrorCode.RUNTIME_VARIANT_NOT_AVAILABLE
        assert supervisor.ping()  # the worker is still there, and the backend may choose another
    finally:
        supervisor.stop()
        for worker in workers:
            worker.kill()
