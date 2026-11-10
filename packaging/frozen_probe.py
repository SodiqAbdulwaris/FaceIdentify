"""A model-free worker for the frozen build's check: detects a face in every lit image.

`packaging/frozen_entry.py --probe-worker` starts the real worker (`ProcessWorker`, `worker_entry`,
the supervisor's handshake and the shared-memory protocol) with these handlers, not the models.
"""

from backend.infrastructure.resources.shared_memory import AttachedSegment
from backend.ml.contracts.messages import (
    DetectFacesOutput,
    Detection,
    ExecutionProvenance,
    MLRequest,
)
from backend.ml.contracts.protocol import MLOperation
from backend.ml.worker.loop import Handler, HandlerContext, HandlerResult

PROVENANCE = ExecutionProvenance("probe", "probe", "ProbeProvider", "cpu")


def detect(request: MLRequest, context: HandlerContext) -> HandlerResult:
    detections = []
    for index, descriptor in enumerate(request.input.images):  # type: ignore[union-attr]
        with AttachedSegment(descriptor) as image, image.view() as pixels:
            if pixels.any():
                detections.append(Detection(index, 0, (0.1, 0.1, 0.5, 0.6), 0.99))
    return HandlerResult(DetectFacesOutput(tuple(detections)), PROVENANCE)


def build_handlers() -> dict[MLOperation, Handler]:
    return {MLOperation.DETECT_FACES: detect}
