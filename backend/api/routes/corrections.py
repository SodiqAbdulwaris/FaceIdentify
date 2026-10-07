"""Correcting a recognised face: confirm it, move it, or separate it (M5 step 2).

The API spec says human corrections must leave correction history and gives no route for them, so
these two commands are the agent's design (flagged in the implementation entry): they name the
occurrence (the face in a source), carry the identity the user saw it under so a stale view is
refused, and return the occurrence as it now is. Each is one use case with one Evidence row.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.api.dependencies import Library, get_backend
from backend.api.errors import ApiError
from backend.api.routes.memory import OccurrenceSummary, identity_not_found, occurrence_summaries
from backend.api.startup import Backend
from backend.app.identities.corrections import confirm_occurrence, reassign_occurrence
from backend.app.identities.models import Identity, IdentityState
from backend.app.identities.use_cases import IdentityManagerError, StaleRevisionError
from backend.app.memory.models import Occurrence, OccurrenceState
from backend.app.sources.models import Source

router = APIRouter(tags=["corrections"])


class Confirm(BaseModel):
    expected_identity_id: uuid.UUID


class Reassign(BaseModel):
    expected_identity_id: uuid.UUID
    identity_id: uuid.UUID | None  # None: separate the face into a new unknown identity


def _not_found(occurrence_id: uuid.UUID) -> ApiError:
    return ApiError(
        404, "OCCURRENCE_NOT_FOUND", "The requested face could not be found.",
        details={"occurrence_id": str(occurrence_id)},
    )  # fmt: skip


def _moved(error: StaleRevisionError) -> ApiError:
    return ApiError(
        409, "OCCURRENCE_MOVED", "This face now belongs to someone else. Reload and try again.",
        details={"reason": str(error)},
    )  # fmt: skip


def _summary(session: Session, occurrence_id: uuid.UUID) -> OccurrenceSummary:
    row = session.execute(
        select(Occurrence, Source)
        .join(Source, Source.id == Occurrence.source_id)
        .where(Occurrence.id == occurrence_id, Occurrence.state == OccurrenceState.ACTIVE)
        .execution_options(populate_existing=True)
    ).tuples().one_or_none()  # fmt: skip
    if row is None:
        raise _not_found(occurrence_id)
    return occurrence_summaries(session, [row])[0]


@router.get("/occurrences/{occurrence_id}")
def get_occurrence(occurrence_id: uuid.UUID, library: Library) -> OccurrenceSummary:
    return library.unit_of_work.read(lambda session: _summary(session, occurrence_id))


@router.post("/occurrences/{occurrence_id}/confirm")
def confirm(
    occurrence_id: uuid.UUID,
    body: Confirm,
    library: Library,
    backend: Annotated[Backend, Depends(get_backend)],
) -> OccurrenceSummary:
    settings = backend.settings

    def write(session: Session) -> OccurrenceSummary:
        _summary(session, occurrence_id)  # 404 if it is not an active face
        try:
            confirm_occurrence(
                session, occurrence_id, expected_identity_id=body.expected_identity_id,
                new_id=settings.new_id, clock=settings.clock,
            )  # fmt: skip
        except StaleRevisionError as error:
            raise _moved(error) from None
        except IdentityManagerError as error:
            raise ApiError(
                409, "FACE_NOT_CORRECTABLE", "This face cannot be confirmed now.",
                details={"reason": str(error)},
            ) from None  # fmt: skip
        return _summary(session, occurrence_id)

    result = library.unit_of_work.write(write)
    backend.announce("occurrence.updated", "occurrence", str(occurrence_id))
    return result


@router.post("/occurrences/{occurrence_id}/reassign")
def reassign(
    occurrence_id: uuid.UUID,
    body: Reassign,
    library: Library,
    backend: Annotated[Backend, Depends(get_backend)],
) -> OccurrenceSummary:
    settings = backend.settings

    def write(session: Session) -> OccurrenceSummary:
        _summary(session, occurrence_id)
        if body.identity_id is not None:
            target = session.get(Identity, body.identity_id)
            if target is None or target.state != IdentityState.ACTIVE:
                raise identity_not_found(body.identity_id)
        try:
            reassign_occurrence(
                session, occurrence_id, body.identity_id,
                expected_identity_id=body.expected_identity_id,
                new_id=settings.new_id, clock=settings.clock,
            )  # fmt: skip
        except StaleRevisionError as error:
            raise _moved(error) from None
        except IdentityManagerError as error:
            raise ApiError(
                409, "FACE_NOT_CORRECTABLE", "This face cannot be moved there.",
                details={"reason": str(error)},
            ) from None  # fmt: skip
        return _summary(session, occurrence_id)

    result = library.unit_of_work.write(write)
    backend.announce("occurrence.updated", "occurrence", str(occurrence_id))
    return result
