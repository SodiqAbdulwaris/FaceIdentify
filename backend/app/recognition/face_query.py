"""Face search: who might the faces in this picture be? A query, never an ingest (API and Contracts
section 12.2; search architecture sections 2 and 4; M5 step 5b; TST-056).

The picture is decoded, its faces are found and embedded under the *current* processing
configuration, and each face is looked up in the global index; SQLite then revalidates every
candidate and the policy's reasoner judges the shortlist, exactly as when an image is processed. All
of it happens in memory and in read-only transactions: no Source, Observation, Representation,
Identity, Evidence, job, run or file is made, so repeating a search cannot grow the library, and the
picture's bytes and vectors are dropped when the call returns.
"""

import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any, TypeVar

from sqlalchemy.orm import Session

from backend.app.processing.configuration import ProcessingRequestV1, resolve
from backend.app.processing.execute_job import (
    PerceptionPlanner,
    _frozen,
    _FrozenConfiguration,
    _Perception,
)
from backend.app.recognition.assessment import (
    INTERPRETATION,
    ObservationQuality,
    RecognitionService,
)
from backend.app.recognition.reasoner import IdentityReasoner, RecognitionDecision
from backend.app.runtime.package_store import RuntimePackageStore
from backend.app.runtime.worker_config import PerceptionPlan
from backend.infrastructure.db.unit_of_work import UnitOfWork
from backend.infrastructure.indexing.representation_index import RepresentationIndex
from backend.infrastructure.media.image import decode_image

# A query belongs to no processing run; this is the id retrieval is told when it needs one (it only
# matters to a run-local pool, which a query does not have).
_NO_RUN = uuid.UUID(int=0)

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class QueriedFace:
    index: int
    box: tuple[float, float, float, float]  # x0, y0, x1, y1, as fractions of the picture
    detection_score: float
    decision: RecognitionDecision


@dataclass(frozen=True, slots=True)
class FaceQueryResult:
    faces: tuple[QueriedFace, ...]  # empty is a successful "no face found"
    policy_version: str
    interpretation: str


class FaceQuery:
    def __init__(
        self,
        uow: UnitOfWork,
        *,
        packages: RuntimePackageStore,
        client_for: Callable[[PerceptionPlan], _Perception],
        global_index_for: Callable[[uuid.UUID], RepresentationIndex],
        exclusive: Callable[[], AbstractContextManager[object]],
        planner: PerceptionPlanner,
        request_for: Callable[[Session], dict[str, Any]],
        max_pixels: int,
        recognition_k: int,
    ) -> None:
        self._uow = uow
        self._packages = packages
        self._client_for = client_for
        self._global_index_for = global_index_for
        self._exclusive = exclusive
        self._planner = planner
        self._request_for = request_for
        self._max_pixels = max_pixels
        self._recognition = RecognitionService(recognition_k)

    def search(self, image: bytes, present: Callable[[Session, FaceQueryResult], T]) -> T:
        """Answer for the picture. `present` builds the response from the result inside the very
        read transaction that validated the candidates, so a forget, delete or merge that commits
        later can never be mixed into an answer, and the index is opened under the coordinator's
        lock so no pass can publish or clean up the generation being loaded."""
        pixels = decode_image(image, max_pixels=self._max_pixels).pixels

        def configure(session: Session) -> tuple[_FrozenConfiguration, PerceptionPlan]:
            request = ProcessingRequestV1.parse(self._request_for(session))
            frozen = _frozen(resolve(session, request))
            plan = self._planner(
                session,
                self._packages,
                detector_component_version_id=frozen.detector_component_version_id,
                detector_model_export_id=frozen.detector_export_id,
                embedder_model_export_id=frozen.embedder_export_id,
                representation_space_id=frozen.representation_space_id,
                providers=frozen.providers,
            )
            return frozen, plan

        frozen, plan = self._uow.read(configure)
        client = self._client_for(plan)
        detected = client.detect(pixels)
        policy = frozen.decision_policy
        if not detected.detections:
            empty = FaceQueryResult((), policy.version, INTERPRETATION)
            return self._uow.read(lambda session: present(session, empty))
        represented = client.represent(pixels, detected.detections)
        space_id = frozen.representation_space_id

        def decide(session: Session) -> T:
            index = self._global_index_for(space_id)
            faces = []
            for detection, face in zip(detected.detections, represented.vectors, strict=True):
                assessment = self._recognition.assess(
                    session,
                    representation_space_id=space_id,
                    dimension=frozen.dimension,
                    vector=face.vector,
                    quality=ObservationQuality(detection.score),
                    global_index=index,
                    processing_run_id=_NO_RUN,
                )
                faces.append(
                    QueriedFace(
                        detection.detection_index,
                        detection.box,
                        detection.score,
                        IdentityReasoner(policy).decide(assessment),
                    )
                )
            return present(session, FaceQueryResult(tuple(faces), policy.version, INTERPRETATION))

        with self._exclusive():
            return self._uow.read(decide)
