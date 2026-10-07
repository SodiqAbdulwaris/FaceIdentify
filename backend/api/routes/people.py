"""People: naming an identity, reading and renaming a Person, linking and unlinking (API section 7).

A Person exists because someone named an Identity: `POST /people` takes the name and the identity
and creates both the Person and the link in one transaction (an unknown identity never has a
placeholder Person, and no Person is created alone; owner decision 2026-10-07). Linking another
identity to an existing Person and unlinking one are separate commands. Each is a use case with
Evidence; the routes only translate.
"""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, StringConstraints
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.api.dependencies import Library, get_backend
from backend.api.errors import ApiError
from backend.api.pagination import (
    Page,
    PageQuery,
    created_cursor,
    created_key,
    older_than,
    paginate,
)
from backend.api.routes.memory import identity_not_found
from backend.api.startup import Backend
from backend.app.identities.models import Identity, IdentityState
from backend.app.identities.use_cases import IdentityManagerError, StaleRevisionError
from backend.app.people.models import (
    AssociationState,
    IdentityPersonAssociation,
    Person,
    PersonState,
)
from backend.app.people.use_cases import (
    assign_identity_to_person,
    name_identity,
    remove_identity_from_person,
    rename_person,
)

router = APIRouter(tags=["people"])

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class PersonSummary(BaseModel):
    id: str
    display_name: str
    revision: int
    identity_count: int
    created_at: datetime
    updated_at: datetime


class NamePerson(BaseModel):
    display_name: Name
    identity_id: uuid.UUID


class RenamePerson(BaseModel):
    display_name: Name
    expected_revision: int


class IdentityLink(BaseModel):
    identity_id: uuid.UUID


def person_not_found(person_id: uuid.UUID) -> ApiError:
    return ApiError(
        404,
        "PERSON_NOT_FOUND",
        "The requested person could not be found.",
        details={"person_id": str(person_id)},
    )


def _active_person(session: Session, person_id: uuid.UUID) -> Person:
    person = session.get(Person, person_id, populate_existing=True)
    if person is None or person.state != PersonState.ACTIVE:
        raise person_not_found(person_id)
    return person


def _active_identity(session: Session, identity_id: uuid.UUID) -> Identity:
    identity = session.get(Identity, identity_id, populate_existing=True)
    if identity is None or identity.state != IdentityState.ACTIVE:
        raise identity_not_found(identity_id)
    return identity


def _summaries(session: Session, people: list[Person]) -> list[PersonSummary]:
    counts = {
        person_id: count
        for person_id, count in session.execute(
            select(IdentityPersonAssociation.person_id, func.count())
            .where(
                IdentityPersonAssociation.person_id.in_([p.id for p in people]),
                IdentityPersonAssociation.state == AssociationState.ACTIVE,
            )
            .group_by(IdentityPersonAssociation.person_id)
        ).tuples()
    }
    return [
        PersonSummary(
            id=str(person.id),
            display_name=person.display_name,
            revision=person.revision,
            identity_count=counts.get(person.id, 0),
            created_at=person.created_at,
            updated_at=person.updated_at,
        )
        for person in people
    ]


def _announced(backend: Backend, summary: PersonSummary) -> PersonSummary:
    """Tell connected screens a person changed (after the commit; they refetch by id)."""
    backend.announce("person.updated", "person", summary.id)
    return summary


def _conflict(code: str, message: str, error: IdentityManagerError) -> ApiError:
    return ApiError(409, code, message, details={"reason": str(error)})


@router.post("/people", status_code=201)
def name_an_identity(
    body: NamePerson, library: Library, backend: Annotated[Backend, Depends(get_backend)]
) -> PersonSummary:
    settings = backend.settings

    def write(session: Session) -> PersonSummary:
        _active_identity(session, body.identity_id)
        try:
            person, _ = name_identity(
                session,
                body.identity_id,
                body.display_name,
                new_id=settings.new_id,
                clock=settings.clock,
            )
        except IdentityManagerError as error:
            raise _conflict(
                "IDENTITY_ALREADY_NAMED", "The identity already has a person.", error
            ) from None
        return _summaries(session, [person])[0]

    return _announced(backend, library.unit_of_work.write(write))


@router.get("/people")
def list_people(library: Library, page: PageQuery) -> Page[PersonSummary]:
    context = "people"
    after = created_cursor(page.cursor, context)

    def read(session: Session) -> Page[PersonSummary]:
        query = select(Person).where(Person.state == PersonState.ACTIVE)
        if after is not None:
            query = query.where(older_than(Person.created_at, Person.id, after))
        people = list(
            session.scalars(
                query.order_by(Person.created_at.desc(), Person.id.desc())
                .limit(page.limit + 1)
                .execution_options(populate_existing=True)
            )
        )
        summaries = {s.id: s for s in _summaries(session, people)}
        return paginate(
            people,
            page.limit,
            context=context,
            key=lambda person: created_key(person.created_at, person.id),
            item=lambda person: summaries[str(person.id)],
        )

    return library.unit_of_work.read(read)


@router.get("/people/{person_id}")
def get_person(person_id: uuid.UUID, library: Library) -> PersonSummary:
    return library.unit_of_work.read(
        lambda session: _summaries(session, [_active_person(session, person_id)])[0]
    )


@router.patch("/people/{person_id}")
def rename(
    person_id: uuid.UUID,
    body: RenamePerson,
    library: Library,
    backend: Annotated[Backend, Depends(get_backend)],
) -> PersonSummary:
    settings = backend.settings

    def write(session: Session) -> PersonSummary:
        _active_person(session, person_id)
        try:
            person = rename_person(
                session,
                person_id,
                body.display_name,
                expected_revision=body.expected_revision,
                new_id=settings.new_id,
                clock=settings.clock,
            )
        except StaleRevisionError as error:
            raise _conflict(
                "PERSON_REVISION_CONFLICT", "The person was changed by something else.", error
            ) from None
        return _summaries(session, [person])[0]

    return _announced(backend, library.unit_of_work.write(write))


@router.post("/people/{person_id}/assign-identity")
def assign_identity(
    person_id: uuid.UUID,
    body: IdentityLink,
    library: Library,
    backend: Annotated[Backend, Depends(get_backend)],
) -> PersonSummary:
    settings = backend.settings

    def write(session: Session) -> PersonSummary:
        person = _active_person(session, person_id)
        _active_identity(session, body.identity_id)
        try:
            assign_identity_to_person(
                session,
                body.identity_id,
                person_id,
                new_id=settings.new_id,
                clock=settings.clock,
            )
        except IdentityManagerError as error:
            raise _conflict(
                "IDENTITY_NOT_ASSIGNABLE", "The identity cannot be linked.", error
            ) from None
        return _summaries(session, [person])[0]

    return _announced(backend, library.unit_of_work.write(write))


@router.post("/people/{person_id}/remove-identity")
def remove_identity(
    person_id: uuid.UUID,
    body: IdentityLink,
    library: Library,
    backend: Annotated[Backend, Depends(get_backend)],
) -> PersonSummary:
    settings = backend.settings

    def write(session: Session) -> PersonSummary:
        person = _active_person(session, person_id)
        _active_identity(session, body.identity_id)
        linked = session.scalar(
            select(IdentityPersonAssociation.person_id).where(
                IdentityPersonAssociation.identity_id == body.identity_id,
                IdentityPersonAssociation.state == AssociationState.ACTIVE,
            )
        )
        if linked != person_id:
            raise ApiError(
                409,
                "IDENTITY_NOT_LINKED",
                "The identity is not linked to this person.",
                details={"identity_id": str(body.identity_id)},
            )
        remove_identity_from_person(
            session, body.identity_id, new_id=settings.new_id, clock=settings.clock
        )
        return _summaries(session, [person])[0]

    return _announced(backend, library.unit_of_work.write(write))
