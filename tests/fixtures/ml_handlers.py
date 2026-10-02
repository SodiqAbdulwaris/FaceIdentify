"""Fake ML handlers for the worker tests: deterministic, no model, controlled by `options`.

The request's `options["mode"]` makes a handler misbehave on purpose: raise (also with an empty or
an unprintable message), run out of memory, report a coded error (also with a code that is not one),
leave a view open on a segment it made, answer about an image that was not sent, hang, sleep, or
kill its own process. The last three are for the supervisor's tests, which run real processes.
"""

import os
import time
from typing import Any

from backend.infrastructure.resources.shared_memory import AttachedSegment
from backend.ml.contracts.messages import (
    DetectFacesOutput,
    Detection,
    ExecutionProvenance,
    GenerateRepresentationsInput,
    GenerateRepresentationsOutput,
    MLRequest,
    RepresentationResult,
)
from backend.ml.contracts.protocol import MLErrorCode, MLOperation
from backend.ml.worker.loop import Handler, HandlerContext, HandlerResult, WorkerError

PROVENANCE = ExecutionProvenance("cv-fake", "rv-fake", "FakeProvider", "cpu")
LEAKED_VIEWS: list[tuple[Any, Any]] = []  # (view, segment) a handler left open on purpose
EMBEDDING_DIMENSION = 4


class Unprintable(Exception):
    def __str__(self) -> str:
        raise RuntimeError("cannot even print")


def misbehave(request: MLRequest) -> None:
    mode = str(request.options.get("mode", ""))
    if mode == "raise":
        raise RuntimeError("the fake model failed")
    if mode == "raise-silently":
        raise RuntimeError
    if mode == "memory":
        raise MemoryError
    if mode == "coded":
        raise WorkerError(MLErrorCode.RUNTIME_INITIALIZATION_FAILED, "the provider would not start")
    if mode == "coded-blank":
        raise WorkerError(MLErrorCode.INTERNAL_WORKER_ERROR, "")
    if mode == "coded-invalid":
        raise WorkerError("BOOM", "not a code")  # type: ignore[arg-type]
    if mode == "unprintable":
        raise Unprintable
    if mode == "long":
        raise RuntimeError("x" * 5000)
    if mode == "hang":
        time.sleep(3600)
    if mode.startswith("sleep:"):
        time.sleep(float(mode.split(":")[1]))
    if mode == "exit":
        os._exit(3)


def detect(request: MLRequest, context: HandlerContext) -> HandlerResult:
    misbehave(request)
    detections = []
    if request.options.get("mode") == "wrong-answer":
        return HandlerResult(
            DetectFacesOutput((Detection(5, 0, (0.1, 0.1, 0.5, 0.6), 0.9),)), PROVENANCE
        )
    for index, descriptor in enumerate(request.input.images):
        with AttachedSegment(descriptor) as image, image.view() as pixels:
            if pixels.any():  # a blank image has no face
                detections.append(Detection(index, 0, (0.1, 0.1, 0.5, 0.6), 0.99))
    return HandlerResult(DetectFacesOutput(tuple(detections)), PROVENANCE)


def represent(request: MLRequest, context: HandlerContext) -> HandlerResult:
    misbehave(request)
    assert isinstance(request.input, GenerateRepresentationsInput)
    results = []
    for face in request.input.faces:
        with AttachedSegment(request.input.images[face.input_index]) as image:
            mean = float(image.copy().mean())
        segment = context.ledger.create("float32", (EMBEDDING_DIMENSION,))
        segment.write([mean, face.face_index, 0.0, 1.0])
        if request.options.get("mode") == "raise-after-output":
            raise RuntimeError("failed after making an output")
        if request.options.get("mode") == "view-leak":
            view = segment.view()
            view.__enter__()
            LEAKED_VIEWS.append((view, segment))  # kept, or garbage collection ends the view
            raise RuntimeError("failed with a view still open")
        results.append(
            RepresentationResult(
                face.input_index, face.face_index, EMBEDDING_DIMENSION, "float32", "l2",
                segment.descriptor,
            )
        )  # fmt: skip
    return HandlerResult(GenerateRepresentationsOutput(tuple(results)), PROVENANCE)


def build_handlers() -> dict[MLOperation, Handler]:
    return {MLOperation.DETECT_FACES: detect, MLOperation.GENERATE_REPRESENTATIONS: represent}


def build_detector_only() -> dict[MLOperation, Handler]:
    return {MLOperation.DETECT_FACES: detect}


def build_broken() -> dict[MLOperation, Handler]:
    raise RuntimeError("the models could not be loaded")
