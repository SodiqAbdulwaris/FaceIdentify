"""Person and Identity-Person association mutations (PERSISTENCE_IMPLEMENTATION.md §8-§9).

Reassigning which Person an Identity is linked to is how a previously wrong link is corrected
(TST-013 / TESTING_STRATEGY.md ID-03): ending the current active association and creating a new
one preserves why the earlier decision was made, rather than overwriting it. Renaming a Person
changes only its display name; it never touches any linked Identity's own identifier or history
(TST-014).

Functions flush but do not commit: the caller owns the transaction boundary
(PERSISTENCE_IMPLEMENTATION.md §26).
"""

import uuid
from collections.abc import Callable
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.identities.models import Evidence, EvidenceKind, Identity, IdentityState
from backend.app.identities.use_cases import IdentityManagerError, StaleRevisionError
from backend.app.people.models import (
    AssociationState,
    IdentityPersonAssociation,
    Person,
    PersonState,
)
from backend.infrastructure.db.optimistic import optimistic_locked_update


def _active_association(
    session: Session, identity_id: uuid.UUID
) -> IdentityPersonAssociation | None:
    return session.scalar(
        select(IdentityPersonAssociation).where(
            IdentityPersonAssociation.identity_id == identity_id,
            IdentityPersonAssociation.state == AssociationState.ACTIVE,
        )
    )


def assign_identity_to_person(
    session: Session,
    identity_id: uuid.UUID,
    person_id: uuid.UUID,
    *,
    new_id: Callable[[], uuid.UUID],
    clock: Callable[[], datetime],
    payload_schema_version: int = 1,
) -> IdentityPersonAssociation:
    """Link an Identity to a Person, ending any current active link first (§9).

    Calling this again for an identity that already has an active link to a *different* person
    is how a wrong link gets corrected: the old association becomes `SUPERSEDED`, never deleted,
    and its own `Evidence` row is untouched — only a new `Evidence` row is added, explaining the
    change.

    Deliberately does not take an `expected_revision` for the identity, so it checks state
    (`session.get` + a plain read) rather than §9's literal "lock/reload" wording. This matches
    `assign_representation_to_identity`'s already-established precedent (PR #6); the unique
    active-association index still rejects a genuine race.
    """
    identity = session.get(Identity, identity_id)
    if identity is None:
        raise IdentityManagerError(f"identity {identity_id} does not exist")
    if identity.state != IdentityState.ACTIVE:
        # Symmetric with assign_representation_to_identity's rule (identities/use_cases.py):
        # only an active identity receives a new authoritative link.
        raise IdentityManagerError(
            f"identity {identity_id} is {identity.state}, not ACTIVE; only an active identity"
            " can be linked to a person"
        )
    person = session.get(Person, person_id)
    if person is None:
        raise IdentityManagerError(f"person {person_id} does not exist")
    if person.state != PersonState.ACTIVE:
        raise IdentityManagerError(f"person {person_id} is {person.state}, not ACTIVE")

    current = _active_association(session, identity_id)
    if current is not None and current.person_id == person_id:
        raise IdentityManagerError(
            f"identity {identity_id} is already linked to person {person_id}"
        )

    now = clock()
    previous_person_id = current.person_id if current is not None else None
    if current is not None:
        # A plain increment, not optimistic_locked_update: `current` was fetched by this same
        # transaction moments ago, so there is nothing to race against under SQLite's
        # single-writer model. A future multi-writer backend would need this guarded too.
        current.state = AssociationState.SUPERSEDED
        current.ended_at = now
        current.revision += 1

    evidence = Evidence(
        id=new_id(),
        kind=EvidenceKind.IDENTITY_ASSIGNED_TO_PERSON,
        subject_identity_id=identity_id,
        subject_person_id=person_id,
        payload_schema_version=payload_schema_version,
        payload_json={
            "previous_person_id": str(previous_person_id) if previous_person_id else None
        },
        created_at=now,
    )
    session.add(evidence)
    session.flush()  # evidence.id is set by default, but the row must exist for the FK below

    association = IdentityPersonAssociation(
        id=new_id(),
        identity_id=identity_id,
        person_id=person_id,
        state=AssociationState.ACTIVE,
        evidence_id=evidence.id,
        created_at=now,
    )
    session.add(association)
    session.flush()
    return association


def remove_identity_from_person(
    session: Session,
    identity_id: uuid.UUID,
    *,
    new_id: Callable[[], uuid.UUID],
    clock: Callable[[], datetime],
    payload_schema_version: int = 1,
) -> IdentityPersonAssociation:
    """End an Identity's current Person link without creating a new one.

    Unlike assignment, this does not require the identity to be `ACTIVE`: it only ends an
    existing row, so it cannot create an invalid new link regardless of the identity's state.
    """
    current = _active_association(session, identity_id)
    if current is None:
        raise IdentityManagerError(f"identity {identity_id} has no active person association")

    now = clock()
    evidence = Evidence(
        id=new_id(),
        kind=EvidenceKind.IDENTITY_REMOVED_FROM_PERSON,
        subject_identity_id=identity_id,
        subject_person_id=current.person_id,
        payload_schema_version=payload_schema_version,
        payload_json={"association_id": str(current.id)},
        created_at=now,
    )
    session.add(evidence)
    session.flush()

    # A plain increment; see the matching comment in assign_identity_to_person for why an
    # optimistic-locked UPDATE isn't needed here under SQLite's single-writer model.
    current.state = AssociationState.REMOVED
    current.ended_at = now
    current.revision += 1
    session.flush()
    return current


def name_identity(
    session: Session,
    identity_id: uuid.UUID,
    display_name: str,
    *,
    new_id: Callable[[], uuid.UUID],
    clock: Callable[[], datetime],
) -> tuple[Person, IdentityPersonAssociation]:
    """Name an unnamed Identity: create the Person and link it, in the caller's one transaction.

    This is the normal way a Person comes to exist (owner decision 2026-10-07): an unknown
    Identity never has a placeholder Person, and a Person is never created without the Identity
    that prompted it. An Identity that already has a Person is refused (rename that Person, or
    correct the link with `assign_identity_to_person`).
    """
    name = display_name.strip()
    if not name:
        raise IdentityManagerError("a person's name cannot be empty")
    identity = session.get(Identity, identity_id)
    if identity is None:
        raise IdentityManagerError(f"identity {identity_id} does not exist")
    if identity.state != IdentityState.ACTIVE:  # (checked first: no person is made for nothing)
        raise IdentityManagerError(
            f"identity {identity_id} is {identity.state}, not ACTIVE; only an active identity"
            " can be named"
        )
    if _active_association(session, identity_id) is not None:
        raise IdentityManagerError(
            f"identity {identity_id} already has a person; rename that person instead"
        )
    now = clock()
    person = Person(
        id=new_id(),
        state=PersonState.ACTIVE,
        display_name=name,
        normalized_name=name.casefold(),
        created_at=now,
        updated_at=now,
    )
    session.add(person)
    session.flush()
    association = assign_identity_to_person(
        session, identity_id, person.id, new_id=new_id, clock=clock
    )
    return person, association


def rename_person(
    session: Session,
    person_id: uuid.UUID,
    display_name: str,
    *,
    expected_revision: int,
    new_id: Callable[[], uuid.UUID],
    clock: Callable[[], datetime],
) -> Person:
    """Change a Person's display name (§38: a semantic event, never visual evidence).

    Never touches any linked Identity's own identifier or state (TST-014): renaming only updates
    this one `people` row and appends one `PERSON_RENAMED` Evidence row (owner decision
    2026-10-07). The Evidence records the revisions, not the names: it is immutable, and a name is
    personal data that must stay changeable.
    """
    name = display_name.strip()
    if not name:
        raise IdentityManagerError("a person's name cannot be empty")
    display_name = name
    normalized_name = display_name.casefold()
    rowcount = optimistic_locked_update(
        session,
        Person,
        person_id,
        expected_revision=expected_revision,
        values={
            "display_name": display_name,
            "normalized_name": normalized_name,
            "updated_at": clock(),
        },
    )
    if rowcount == 0:
        _raise_rename_conflict(session, person_id, expected_revision)
    session.flush()
    # populate_existing: optimistic_locked_update disables session-sync (see its docstring), so
    # this session's cached copy cannot be trusted otherwise.
    person = session.get(Person, person_id, populate_existing=True)
    assert person is not None  # the UPDATE above just matched this row
    session.add(
        Evidence(
            id=new_id(),
            kind=EvidenceKind.PERSON_RENAMED,
            subject_person_id=person_id,
            payload_schema_version=1,
            payload_json={"previous_revision": expected_revision, "revision": person.revision},
            created_at=person.updated_at,
        )
    )
    session.flush()
    return person


def _raise_rename_conflict(session: Session, person_id: uuid.UUID, expected_revision: int) -> None:
    person = session.get(Person, person_id, populate_existing=True)
    if person is None:
        raise IdentityManagerError(f"person {person_id} does not exist")
    raise StaleRevisionError(
        f"person {person_id} is at revision {person.revision}, expected {expected_revision}"
    )
