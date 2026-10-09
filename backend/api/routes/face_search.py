"""Face search: `POST /api/v1/search/face` (API and Contracts section 12.2; M5 step 5b; TST-056).

A query, never an ingest: the picture is read, its faces are looked up in the memory and the
answer is made, with nothing written (see `backend.app.recognition.face_query`). The picture
comes either as JSON `{"path": "..."}` (a file on this computer, read once and never copied) or
as the image bytes themselves in the body. Every face found gets its own answer. A match the
policy accepts would be an `IDENTITY_ANSWER`; otherwise the nearest known people are offered as
`POSSIBLE_PEOPLE`, with their similarity (a cosine similarity, not a probability), and a face
nobody resembles is `UNKNOWN`.
"""

import json
import uuid
from pathlib import Path
from typing import Annotated, Literal

import anyio
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.api.dependencies import Library, get_backend
from backend.api.errors import ApiError
from backend.api.routes.memory import BoundingBox, IdentitySummary, identity_summaries
from backend.api.routes.processing import processing_settings
from backend.api.routes.sources import media_limits
from backend.api.startup import (
    Backend,
    MediaLimits,
    ProcessingSettings,
    ProcessingUnavailableError,
)
from backend.app.identities.models import Identity
from backend.app.processing.configuration import ProcessingConfigurationError
from backend.app.recognition.face_query import FaceQuery, FaceQueryResult, QueriedFace
from backend.app.recognition.reasoner import RecognitionOutcome
from backend.app.runtime.perception_client import PerceptionError
from backend.app.runtime.worker_config import RuntimeUnavailableError
from backend.infrastructure.indexing.representation_index import IndexUnusableError
from backend.infrastructure.media.image import (
    CorruptImageError,
    ImageTooLargeError,
    UnsupportedImageError,
)
from backend.ml.contracts.protocol import ContractError
from backend.ml.supervisor.supervisor import MLUnavailableError, WorkerFailedError

router = APIRouter(tags=["search"])


class PossiblePerson(BaseModel):
    identity: IdentitySummary
    # The best cosine similarity to any remembered face of them. Not a probability.
    similarity: float
    matching_faces: int


class FaceAnswer(BaseModel):
    index: int
    bounding_box: BoundingBox
    detection_score: float
    status: Literal["IDENTITY_ANSWER", "POSSIBLE_PEOPLE", "UNKNOWN"]
    reason: str
    identity_answer: IdentitySummary | None
    possible_people: list[PossiblePerson]
    # False when the index could not be trusted to hold the nearest faces (it was catching up).
    retrieval_complete: bool


class FaceRanking(BaseModel):
    plan: str
    policy_version: str
    similarity: str


class FaceSearchResponse(BaseModel):
    faces: list[FaceAnswer]
    ranking: FaceRanking


# A JSON body only names a file; anything longer than this is not one.
JSON_BODY_LIMIT = 8192


def too_large() -> ApiError:
    return ApiError(413, "MEDIA_TOO_LARGE", "The image is larger than is allowed.")


def _read_query(raw: bytes, content_type: str, limits: MediaLimits) -> bytes:
    """The picture's bytes: the body itself, or the file a JSON body names.

    Trust boundary: the bearer token already lets its holder read any file on this computer
    through import, so a path is accepted as is, except that a network path (UNC or device) is
    refused: it could make this computer reach out and authenticate to another one. The file is
    read through one handle and never more than the limit, whatever it grows into after a check.
    """
    if "json" not in content_type:
        return raw
    try:
        path = json.loads(raw)["path"]
        # (Windows reads / as \ too, so //server and \\/server are network paths as well)
        if not isinstance(path, str) or path.replace("/", "\\").startswith("\\\\"):
            raise ValueError
        with Path(path).open("rb") as handle:
            data = handle.read(limits.max_bytes + 1)
    except (ValueError, KeyError, TypeError, OSError):
        raise ApiError(400, "QUERY_IMAGE_UNREADABLE", "The image could not be read.") from None
    if len(data) > limits.max_bytes:
        raise too_large()
    return data


def _answer(session: Session, result: FaceQueryResult) -> FaceSearchResponse:
    wanted = {
        group.identity_id
        for face in result.faces
        for group in face.decision.assessment.groups
        if group.identity_id is not None
    }
    rows = list(session.scalars(select(Identity).where(Identity.id.in_(wanted)))) if wanted else []
    summaries = {uuid.UUID(s.id): s for s in identity_summaries(session, rows)}

    def one(face: QueriedFace) -> FaceAnswer:
        decision = face.decision
        possible = [
            PossiblePerson(
                identity=summaries[group.identity_id],
                similarity=group.best_similarity,
                matching_faces=len(group.members),
            )
            for group in decision.assessment.groups
            if group.identity_id in summaries
        ]
        accepted = (
            summaries.get(decision.identity_id)
            if decision.outcome == RecognitionOutcome.MATCH_EXISTING and decision.identity_id
            else None
        )
        x0, y0, x1, y1 = face.box
        return FaceAnswer(
            index=face.index,
            bounding_box=BoundingBox(x=x0, y=y0, width=x1 - x0, height=y1 - y0),
            detection_score=face.detection_score,
            status="IDENTITY_ANSWER" if accepted else "POSSIBLE_PEOPLE" if possible else "UNKNOWN",
            reason=decision.reason.value,
            identity_answer=accepted,
            possible_people=possible,
            retrieval_complete=decision.assessment.complete,
        )

    return FaceSearchResponse(
        faces=[one(face) for face in result.faces],
        ranking=FaceRanking(
            plan="FACE_QUERY",
            policy_version=result.policy_version,
            similarity=result.interpretation,
        ),
    )


_BODY = {
    "requestBody": {
        "required": True,
        "content": {
            "application/json": {
                "schema": {
                    "type": "object",
                    "required": ["path"],
                    "properties": {"path": {"type": "string"}},
                }
            },
            "image/*": {"schema": {"type": "string", "format": "binary"}},
            "application/octet-stream": {"schema": {"type": "string", "format": "binary"}},
        },
    }
}


@router.post("/search/face", openapi_extra=_BODY)
async def search_face(
    request: Request,
    library: Library,
    backend: Annotated[Backend, Depends(get_backend)],
    limits: Annotated[MediaLimits, Depends(media_limits)],
) -> FaceSearchResponse:
    settings = processing_settings(backend)
    if not backend.face_search_slots.acquire(blocking=False):
        raise ApiError(
            429, "FACE_SEARCH_BUSY", "Other pictures are being searched. Try again in a moment.",
            retryable=True,
        )  # fmt: skip
    try:
        return await _search(request, library, backend, limits, settings)
    finally:
        backend.face_search_slots.release()


async def _search(
    request: Request,
    library: Library,
    backend: Backend,
    limits: MediaLimits,
    settings: ProcessingSettings,
) -> FaceSearchResponse:
    content_type = request.headers.get("content-type", "")
    ceiling = JSON_BODY_LIMIT if "json" in content_type else limits.max_bytes
    received = bytearray()
    async for chunk in request.stream():  # (counted as it arrives: nothing over the limit is kept)
        if len(received) + len(chunk) > ceiling:
            raise too_large()
        received += chunk
    raw = bytes(received)
    del received  # (one copy, not two, while the picture waits for the worker)

    def run() -> FaceSearchResponse:
        image = _read_query(raw, content_type, limits)
        query = FaceQuery(
            library.unit_of_work,
            packages=library.packages,
            client_for=settings.client_for,
            global_index_for=library.coordinator.open_for_recognition,
            exclusive=library.coordinator.exclusive,
            planner=settings.planner,
            request_for=settings.request_for,
            max_pixels=settings.max_pixels,
            recognition_k=settings.recognition_k,
        )
        try:
            with backend.face_search_gate:
                return query.search(image, _answer)
        except UnsupportedImageError:
            raise ApiError(
                415,
                "MEDIA_FORMAT_UNSUPPORTED",
                "Only JPEG, PNG, BMP and WebP images are supported.",
            ) from None
        except CorruptImageError:
            raise ApiError(422, "MEDIA_CORRUPT", "The image could not be read.") from None
        except ImageTooLargeError:
            raise ApiError(
                413, "MEDIA_TOO_LARGE", "The image has more pixels than is allowed."
            ) from None
        except (ProcessingUnavailableError, ProcessingConfigurationError, RuntimeUnavailableError):
            raise ApiError(
                503, "PROCESSING_UNAVAILABLE", "No processing configuration is available."
            ) from None
        except (PerceptionError, WorkerFailedError, MLUnavailableError, ContractError):
            raise ApiError(
                503, "PERCEPTION_UNAVAILABLE", "The faces could not be looked for just now.",
                retryable=True,
            ) from None  # fmt: skip
        except IndexUnusableError:
            raise ApiError(
                503, "SEARCH_INDEX_UNAVAILABLE",
                "The memory's search index is not usable. It is rebuilt when the app starts.",
            ) from None  # fmt: skip

    return await anyio.to_thread.run_sync(run)
