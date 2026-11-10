"""The real pipeline on a synthetic video, with painted "faces" (M6 steps 4 to 7).

A clip made by the pinned ffmpeg shows coloured squares on black: a red one moving right for the
whole clip and, from one second on, a green one standing still. `PaintedPerception` "detects" each
square by its colour and embeds it as that colour's vector, so tracks, selection, recognition and
occurrences are tested on real decoding, the real executor and the real worker lease, with no face
and no model. Its turns are a real `WorkerLease`, so cancellation and arbitration are the real ones.
"""

import uuid
from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from backend.app.processing.execute_job import ExecuteProcessingJob
from backend.app.processing.video_chunks import VideoProcessing
from backend.app.runtime.package_store import RuntimePackageStore
from backend.app.runtime.perception_client import Detected, FaceVector, Represented
from backend.app.runtime.worker_config import PlannedVariant
from backend.app.sources.import_source import ImportSourceUseCase, VideoImport
from backend.infrastructure.media.video import probe_video
from backend.ml.contracts.messages import Detection
from backend.ml.supervisor.lease import WorkerLease
from tests.fixtures.media import installed_tools, make_clip
from tests.fixtures.pipeline import Pipeline, unit

RED = unit(1, 0, 0, 0)
GREEN = unit(0, 1, 0, 0)
# (pixel test, vector) per painted colour; the order is the detection order
COLOURS: tuple[tuple[Callable[[NDArray[np.uint8]], NDArray[np.bool_]], NDArray[Any]], ...] = (
    (lambda p: (p[..., 0] > 150) & (p[..., 1] < 100) & (p[..., 2] < 100), RED),
    (lambda p: (p[..., 1] > 150) & (p[..., 0] < 100) & (p[..., 2] < 100), GREEN),
)


def painted_clip(path: Path, *, seconds: float = 3) -> Path:
    graph = (
        "[0:v]drawbox=x=110:y=70:w=30:h=30:color=lime:t=fill:enable='gte(t,1)'[still];"
        "color=c=red:size=30x30:rate=25[square];"
        "[still][square]overlay=x='10+t*20':y=30:shortest=1"
    )
    return make_clip(
        path,
        seconds=seconds,
        source="color=c=black",
        encode=("-filter_complex", graph, "-c:v", "mpeg4", "-q:v", "2"),
    )


class PaintedPerception:
    def __init__(self, detector: PlannedVariant, embedder: PlannedVariant) -> None:
        self.detector, self.embedder = detector, embedder
        self.lease = WorkerLease()
        self.log: list[str] = []  # "turn", "detect", "represent", in order
        self.on_detect: Callable[[int], None] | None = None  # told the detect call's number
        self.drop_vector = False  # represent one face fewer than asked

    def turn(self) -> Any:
        self.log.append("turn")
        return self.lease.held()

    def detect(self, pixels: NDArray[np.uint8]) -> Detected:
        self.log.append("detect")
        if self.on_detect is not None:
            self.on_detect(self.log.count("detect"))
        height, width = pixels.shape[:2]
        found = []
        for index, (painted, _vector) in enumerate(COLOURS):
            ys, xs = np.nonzero(painted(pixels))
            if len(xs) > 20:
                box = (xs.min() / width, ys.min() / height, (xs.max() + 1) / width,
                       (ys.max() + 1) / height)  # fmt: skip
                found.append(Detection(0, index, tuple(float(v) for v in box), 0.9, None))  # type: ignore[arg-type]
        return Detected(tuple(found), self.detector)

    def represent(self, pixels: Any, detections: tuple[Detection, ...]) -> Represented:
        self.log.append("represent")
        vectors = tuple(
            FaceVector(d.detection_index, COLOURS[d.detection_index][1], "L2_NORMALIZED")
            for d in detections
        )
        return Represented(vectors[1:] if self.drop_vector else vectors, self.embedder, ())


def video_perception(pipeline: Pipeline) -> PaintedPerception:
    perception = PaintedPerception(pipeline.perception.detector, pipeline.perception.embedder)
    pipeline.perception = perception  # type: ignore[assignment]
    return perception


def import_video(pipeline: Pipeline, path: Path, *, referenced: bool = False) -> uuid.UUID:
    importer = ImportSourceUseCase(
        pipeline.lib.unit_of_work,
        pipeline.lib.store,
        new_id=pipeline.new_id,
        clock=pipeline.clock,
        max_pixels=1,
        max_bytes=1,
        video=lambda: VideoImport(partial(probe_video, installed_tools()), 100_000_000),
    )
    importing = importer.import_referenced if referenced else importer.import_managed
    return importing(path).source_id


def video_executor(
    pipeline: Pipeline, *, max_pixels: int = 1_000_000, tools: bool = True, **settings: Any
) -> ExecuteProcessingJob:
    lib = pipeline.lib
    executor = ExecuteProcessingJob(
        lib.unit_of_work,
        packages=RuntimePackageStore(lib.roots, new_id=pipeline.new_id),
        files=lib.store,
        client_for=lambda _plan: pipeline.perception,
        global_index_for=pipeline.global_index,
        new_id=pipeline.new_id,
        clock=pipeline.clock,
        max_pixels=max_pixels,
        recognition_k=2,
        video_tools=installed_tools if tools else None,
        video=VideoProcessing(**{"chunk_frames": 4, "frames_per_turn": 2, **settings}),
    )
    executor._plan = lambda _session, _frozen: pipeline.plan  # type: ignore[method-assign, assignment]
    return executor
