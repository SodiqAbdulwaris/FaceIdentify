"""A camera session on the real pipeline with painted "faces" and scripted frames (M7 step 4).

No camera and no model: frames are NumPy pictures of coloured squares on black, given in order as a
`LiveCamera` would give them (`LiveFrame`, or a `Gap` where the stream broke), and
`PaintedCameraPerception` "detects" each square by its colour and embeds a face crop as the
colour it shows. The worker turns are a real `WorkerLease`, so the live class is the real one.
"""

import uuid
from collections.abc import Callable, Iterator
from typing import Any

import numpy as np
from numpy.typing import NDArray
from sqlalchemy.orm import Session

from backend.app.cameras.capture import Gap
from backend.app.cameras.session import (
    CameraSessionExecutor,
    CameraSettings,
    start_camera_session,
)
from backend.app.processing.accept_run import AcceptProcessingRunUseCase
from backend.app.processing.scheduler import StartedProcessingJob
from backend.app.runtime.package_store import RuntimePackageStore
from backend.app.runtime.perception_client import Detected, FaceVector, Represented
from backend.app.runtime.worker_config import PlannedVariant
from backend.infrastructure.media.camera import LiveFrame
from backend.ml.contracts.messages import Detection
from backend.ml.supervisor.lease import WorkerLease, service_class
from tests.factories.models import ModelFactory
from tests.fixtures.pipeline import Pipeline
from tests.fixtures.video_pipeline import COLOURS

SIZE = (120, 160)  # height, width
FPS = 5.0


def picture(*squares: tuple[str, int, int]) -> NDArray[np.uint8]:
    """Black, with a 30-pixel square of each named colour ("red", "green") at (x, y)."""
    pixels = np.zeros((*SIZE, 3), dtype=np.uint8)
    for colour, x, y in squares:
        pixels[y : y + 30, x : x + 30] = (255, 0, 0) if colour == "red" else (0, 255, 0)
    return pixels


def frames(*scenes: tuple[float, NDArray[np.uint8] | None]) -> Iterator[LiveFrame | Gap]:
    """`(seconds, picture)` in order; a None picture is a gap in the stream."""
    for sequence, (seconds, pixels) in enumerate(scenes, start=1):
        yield Gap("the stream broke") if pixels is None else LiveFrame(sequence, seconds, pixels)


def visit(colour: str, start: float, seconds: float, x: int = 20) -> list[tuple[float, Any]]:
    """A square standing in front of the camera for `seconds`, one frame per sample."""
    count = round(seconds * FPS)
    return [(start + n / FPS, picture((colour, x, 40))) for n in range(count)]


def empty(start: float, seconds: float) -> list[tuple[float, Any]]:
    count = round(seconds * FPS)
    return [(start + n / FPS, picture()) for n in range(count)]


class PaintedCameraPerception:
    def __init__(self, detector: PlannedVariant, embedder: PlannedVariant) -> None:
        self.detector, self.embedder = detector, embedder
        self.lease = WorkerLease()
        self.classes: list[str] = []  # the lease class of each request, in order
        self.fallbacks: list[Any] = []  # given with the next detection, then cleared
        self.represent_fallbacks: list[Any] = []  # given with the next embedding
        self.represented = 0  # how many faces were embedded
        self.fail_represent: Exception | None = None
        self.drop_vector = False  # embed nothing for the face asked

    def turn(self) -> Any:
        return self.lease.held()

    def detect(self, pixels: NDArray[np.uint8]) -> Detected:
        self.classes.append(f"detect:{service_class()}")
        height, width = pixels.shape[:2]
        found = []
        for index, (painted, _vector) in enumerate(COLOURS):
            ys, xs = np.nonzero(painted(pixels))
            if len(xs) > 20:
                box = (xs.min() / width, ys.min() / height, (xs.max() + 1) / width,
                       (ys.max() + 1) / height)  # fmt: skip
                landmarks = ((box[0] + 0.01, box[1] + 0.01),)
                found.append(Detection(0, index, tuple(float(v) for v in box), 0.9, landmarks))  # type: ignore[arg-type]
        fallbacks, self.fallbacks = tuple(self.fallbacks), []
        return Detected(tuple(found), self.detector, fallbacks)

    def represent(
        self, pixels: NDArray[np.uint8], detections: tuple[Detection, ...]
    ) -> Represented:
        self.classes.append(f"represent:{service_class()}")
        if self.fail_represent is not None:
            raise self.fail_represent
        (detection,) = detections
        if self.drop_vector:
            return Represented((), self.embedder)
        colour = next(vector for painted, vector in COLOURS if painted(pixels).sum() > 20)
        self.represented += 1
        fallbacks, self.represent_fallbacks = tuple(self.represent_fallbacks), []
        return Represented(
            (FaceVector(detection.detection_index, colour, "L2_NORMALIZED"),),
            self.embedder,
            fallbacks,
        )


class Camera:
    """A configured camera on a pipeline's library, and what runs its sessions."""

    def __init__(
        self,
        pipeline: Pipeline,
        *,
        settings: CameraSettings | None = None,
        camera_id: uuid.UUID | None = None,
    ) -> None:
        """A new camera, or the one `camera_id` names."""
        self.pipeline = pipeline
        self.settings = settings or CameraSettings(sample_fps=FPS, encounter_gap_seconds=1.0)
        self.perception = PaintedCameraPerception(
            pipeline.perception.detector, pipeline.perception.embedder
        )
        if camera_id is not None:
            self.id = camera_id
        else:
            with Session(pipeline.lib.engine) as session:
                build = ModelFactory(session, pipeline.clock, pipeline.new_id)  # type: ignore[arg-type]
                self.id = build.camera().source_id
                session.commit()
        self.closed: list[uuid.UUID | None] = []

    def start(self, camera_id: uuid.UUID | None = None) -> StartedProcessingJob:
        return self.pipeline.lib.unit_of_work.write(
            lambda session: start_camera_session(
                session,
                camera_id or self.id,
                processing_request=self.pipeline.request,
                settings=self.settings,
                new_id=self.pipeline.new_id,
                now=self.pipeline.clock(),
            )
        )

    def executor(self, *, utc_ms: Callable[[], Any] | None = None) -> CameraSessionExecutor:
        pipeline, lib = self.pipeline, self.pipeline.lib
        executor = CameraSessionExecutor(
            lib.unit_of_work,
            packages=RuntimePackageStore(lib.roots, new_id=pipeline.new_id),
            files=lib.store,
            client_for=lambda _plan: self.perception,
            global_index_for=pipeline.global_index,
            new_id=pipeline.new_id,
            clock=pipeline.clock,
            max_pixels=1_000_000,
            recognition_k=2,
            accept=AcceptProcessingRunUseCase(
                lib.unit_of_work, new_id=pipeline.new_id, clock=pipeline.clock
            ),
            wake_index=pipeline.apply_index,
            utc_now=utc_ms,
        )
        executor._plan = lambda _session, _frozen: pipeline.plan  # type: ignore[method-assign, assignment]
        return executor

    def run(self, *scenes: tuple[float, Any], **options: Any) -> str:
        started = self.start()
        return self.executor(**options).run(started, frames(*scenes), closed=self.closed.append)
