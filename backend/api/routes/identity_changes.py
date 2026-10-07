"""Merging identities and splitting faces off one (API section 8; M5 step 3).

Each is one use case in one transaction (merge: the identities' states and lineage, representations,
occurrences, person link, Evidence and the representative faces; split: the new identity, the
selected faces and what rests on them, Evidence and lineage), so nothing is ever seen half done. The
index is untouched: ownership is not part of it. A split that would cut a face's evidence in two is
refused as a conflict that names those faces (`409 SPLIT_CONFLICT`).
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.api.dependencies import Library, get_backend
from backend.api.errors import ApiError
from backend.api.routes.memory import IdentitySummary, identity_not_found, identity_summaries
from backend.api.startup import Backend
from backend.app.identities.models import Identity, IdentityState
from backend.app.identities.use_cases import (
    SplitConflictError,
    StaleRevisionError,
    merge_identities,
    occurrence_support,
    split_identity,
)
from backend.app.memory.models import Occurrence, OccurrenceState

router = APIRouter(tags=["identities"])


class MergeMember(BaseModel):
    id: uuid.UUID
    revision: int  # the revision the caller saw: a changed identity is refused, not merged


class Merge(BaseModel):
    identities: list[MergeMember]  # every identity involved, the survivor included
    preferred_identity_id: uuid.UUID  # the survivor


class Split(BaseModel):
    occurrence_ids: list[uuid.UUID]
    expected_revision: (
        int  # the revision of the person the faces are split from, as the caller saw it
    )


def _active(session: Session, identity_id: uuid.UUID) -> Identity:
    identity = session.get(Identity, identity_id, populate_existing=True)
    if identity is None or identity.state != IdentityState.ACTIVE:
        raise identity_not_found(identity_id)
    return identity


@router.post("/identities/merge")
def merge(
    body: Merge, library: Library, backend: Annotated[Backend, Depends(get_backend)]
) -> IdentitySummary:
    settings = backend.settings
    members = {m.id: m for m in body.identities}
    if (
        body.preferred_identity_id not in members
        or len(members) < 2
        or len(members) != len(body.identities)
    ):
        raise ApiError(
            422,
            "INVALID_MERGE",
            "Choose at least two different identities, the survivor among them.",
        )

    def write(session: Session) -> IdentitySummary:
        survivor = _active(session, body.preferred_identity_id)
        for member in members.values():
            _active(session, member.id)
        survivor_revision: int | None = members[survivor.id].revision  # checked once, by the first
        try:
            for member in members.values():
                if member.id != survivor.id:
                    merge_identities(
                        session, member.id, survivor.id, expected_revision=member.revision,
                        expected_survivor_revision=survivor_revision,
                        new_id=settings.new_id, clock=settings.clock,
                    )  # fmt: skip
                    survivor_revision = None
        except StaleRevisionError as error:
            raise ApiError(
                409, "IDENTITY_CHANGED", "One of the people changed since you looked. Reload.",
                details={"reason": str(error)},
            ) from None  # fmt: skip
        session.expire_all()
        return identity_summaries(session, [_active(session, survivor.id)])[0]

    result = library.unit_of_work.write(write)
    backend.announce("identity.updated", "identity", result.id)
    return result  # (every other refusal is checked above, in this transaction)


@router.post("/identities/{identity_id}/split", status_code=201)
def split(
    identity_id: uuid.UUID,
    body: Split,
    library: Library,
    backend: Annotated[Backend, Depends(get_backend)],
) -> IdentitySummary:
    settings = backend.settings
    if not body.occurrence_ids:
        raise ApiError(422, "INVALID_SPLIT", "Choose at least one face to split off.")

    def write(session: Session) -> IdentitySummary:
        _active(session, identity_id)
        support = occurrence_support(session, identity_id)
        wanted = list(dict.fromkeys(body.occurrence_ids))
        for occurrence_id in wanted:
            occurrence = session.get(Occurrence, occurrence_id)
            if (
                occurrence is None
                or occurrence.state != OccurrenceState.ACTIVE
                or occurrence.identity_id != identity_id
            ):
                raise ApiError(
                    404, "OCCURRENCE_NOT_FOUND", "A chosen face is not one of this person's.",
                    details={"occurrence_id": str(occurrence_id)},
                )  # fmt: skip
        bare = [o for o in wanted if not support.get(o)]
        if bare:
            raise ApiError(
                422, "INVALID_SPLIT", "Some chosen faces have nothing to split off.",
                details={"occurrence_ids": [str(o) for o in bare]},
            )  # fmt: skip
        representation_ids = sorted({r for o in wanted for r in support[o]})
        try:
            created = split_identity(
                session, identity_id, representation_ids,
                expected_revision=body.expected_revision,
                new_id=settings.new_id, clock=settings.clock,
            )  # fmt: skip
        except StaleRevisionError as error:
            raise ApiError(
                409, "IDENTITY_CHANGED", "This person changed since you looked. Reload.",
                details={"reason": str(error)},
            ) from None  # fmt: skip
        except SplitConflictError as error:
            raise ApiError(
                409, "SPLIT_CONFLICT",
                "Some faces share what they rest on with faces you did not choose.",
                details={"occurrence_ids": [str(o) for o in error.occurrence_ids]},
            ) from None  # fmt: skip
        return identity_summaries(session, [created])[0]

    result = library.unit_of_work.write(write)
    backend.announce("identity.updated", "identity", result.id)
    backend.announce("identity.updated", "identity", str(identity_id))
    return result
