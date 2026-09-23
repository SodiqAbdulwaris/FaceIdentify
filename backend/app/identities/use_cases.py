"""Identity Manager: the sole authority for identity lifecycle mutations.

Per docs/plans/IDENTITY_DECISION_ENGINE_PLAN.md §1: "The Identity Manager is authoritative for
identity lifecycle, user-visible state, persistence, and consequential mutations. A decision
engine estimates evidence; it does not create, merge, confirm, or delete identities directly."

These use cases therefore take the recognition *decision* as an explicit input (`new_identity`,
`identity_id`) rather than computing one. The decision engine that will call them does not exist
yet (M3+); until then, callers (tests, and later the recognition pipeline) supply the decision.

Functions flush but do not commit: the caller owns the transaction boundary
(PERSISTENCE_IMPLEMENTATION.md §26).
"""

import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Any, cast

from sqlalchemy import CursorResult, insert, update
from sqlalchemy.orm import Session

from backend.app.identities.models import (
    Evidence,
    EvidenceKind,
    EvidenceRepresentation,
    EvidenceRepresentationRole,
    Identity,
    IdentityState,
)
from backend.app.memory.models import (
    AnnKeySequence,
    IndexOperation,
    Representation,
    RepresentationState,
)


class IdentityManagerError(Exception):
    """A requested identity-lifecycle mutation is not authoritatively valid."""


class StaleRevisionError(IdentityManagerError):
    """The row's revision no longer matches what the caller last read (§2 optimistic locking)."""


def create_pending_identity(
    session: Session,
    *,
    new_id: Callable[[], uuid.UUID],
    clock: Callable[[], datetime],
    created_by_processing_run_id: uuid.UUID,
    representative_observation_id: uuid.UUID | None = None,
) -> Identity:
    """Create a new PENDING identity. Recognition creates one; it never assigns a Person (§7)."""
    identity = Identity(
        id=new_id(),
        state=IdentityState.PENDING,
        created_by_processing_run_id=created_by_processing_run_id,
        representative_observation_id=representative_observation_id,
        created_at=clock(),
        updated_at=clock(),
    )
    session.add(identity)
    session.flush()
    return identity


def activate_identity(
    session: Session,
    identity_id: uuid.UUID,
    *,
    expected_revision: int,
    clock: Callable[[], datetime],
) -> Identity:
    """Activate a PENDING identity. Only an accepted processing run may do this (§7).

    `expected_revision` is the revision the caller last read; a mismatch means another writer
    already changed the row (PERSISTENCE_IMPLEMENTATION.md §2), so this raises rather than
    silently overwriting a concurrent change.
    """
    now = clock()
    # session.execute() on a Core UPDATE always returns a CursorResult; the ORM's general
    # overload just can't express that statically.
    result = cast(
        "CursorResult[Any]",
        session.execute(
            update(Identity)
            .where(
                Identity.id == identity_id,
                Identity.revision == expected_revision,
                Identity.state == IdentityState.PENDING,
            )
            .values(
                state=IdentityState.ACTIVE,
                activated_at=now,
                updated_at=now,
                revision=Identity.revision + 1,
            )
        ),
    )
    if result.rowcount == 0:
        _raise_activation_conflict(session, identity_id, expected_revision)
    session.flush()
    # This bypasses the ORM's normal attribute tracking, so an already-loaded Identity in the
    # session's identity map (e.g. the one this same caller just created) would otherwise keep
    # showing its pre-update values. `populate_existing` forces a fresh read.
    identity = session.get(Identity, identity_id, populate_existing=True)
    assert identity is not None  # the UPDATE above just matched this row
    return identity


def _raise_activation_conflict(
    session: Session, identity_id: uuid.UUID, expected_revision: int
) -> None:
    """Distinguish a stale revision from an identity that was never PENDING."""
    identity = session.get(Identity, identity_id)
    if identity is None:
        raise IdentityManagerError(f"identity {identity_id} does not exist")
    if identity.revision != expected_revision:
        raise StaleRevisionError(
            f"identity {identity_id} is at revision {identity.revision},"
            f" expected {expected_revision}"
        )
    raise IdentityManagerError(
        f"identity {identity_id} is {identity.state}, not PENDING;"
        " only a PENDING identity can be activated"
    )


def allocate_ann_key(session: Session, representation_space_id: uuid.UUID) -> int:
    """Allocate the next positive ANN key for a space (§6.3). Guarded, race-safe, never reused.

    The sequence row is created lazily on first allocation: no spec text assigns that
    responsibility elsewhere, and RepresentationSpace creation (PR #4) does not create it.
    """
    session.execute(
        insert(AnnKeySequence)
        .prefix_with("OR IGNORE")
        .values(representation_space_id=representation_space_id, next_ann_key=1)
    )
    allocated = session.execute(
        update(AnnKeySequence)
        .where(AnnKeySequence.representation_space_id == representation_space_id)
        .values(next_ann_key=AnnKeySequence.next_ann_key + 1)
        .returning(AnnKeySequence.next_ann_key - 1)
    ).scalar_one()
    return allocated


def assign_representation_to_identity(
    session: Session,
    representation_id: uuid.UUID,
    identity_id: uuid.UUID,
    *,
    new_id: Callable[[], uuid.UUID],
    clock: Callable[[], datetime],
    evidence_kind: EvidenceKind,
    payload_schema_version: int = 1,
) -> Representation:
    """Commit a PENDING representation to an ACTIVE identity, with Evidence and an index intent.

    This is the one place a representation becomes ANN-eligible; the same transaction creates
    the durable ADD IndexOperation (PERSISTENCE_IMPLEMENTATION.md §1 rule 4). `evidence_kind`
    must be `IDENTITY_CREATED` (the identity was just created for this representation) or
    `IDENTITY_MATCHED` (recognition matched an existing identity) — the caller states which,
    since only the caller (eventually the decision engine's caller) knows which happened.
    """
    if evidence_kind not in (EvidenceKind.IDENTITY_CREATED, EvidenceKind.IDENTITY_MATCHED):
        raise IdentityManagerError(
            f"assignment must be IDENTITY_CREATED or IDENTITY_MATCHED, not {evidence_kind}"
        )

    representation = session.get(Representation, representation_id)
    if representation is None:
        raise IdentityManagerError(f"representation {representation_id} does not exist")
    if representation.state != RepresentationState.PENDING:
        raise IdentityManagerError(
            f"representation {representation_id} is {representation.state}, not PENDING"
        )

    identity = session.get(Identity, identity_id)
    if identity is None:
        raise IdentityManagerError(f"identity {identity_id} does not exist")
    if identity.state != IdentityState.ACTIVE:
        # An active representation requires an active identity (§20); assigning to a
        # pending/merged/forgotten identity would create an invalid row the CHECK constraints
        # cannot express (they only see this table's own columns).
        raise IdentityManagerError(
            f"identity {identity_id} is {identity.state}, not ACTIVE; only an active identity"
            " can receive a new assignment"
        )

    ann_key = allocate_ann_key(session, representation.representation_space_id)
    now = clock()
    representation.state = RepresentationState.ACTIVE
    representation.identity_id = identity_id
    representation.ann_key = ann_key
    representation.activated_at = now

    evidence = Evidence(
        id=new_id(),
        kind=evidence_kind,
        processing_run_id=representation.processing_run_id,
        subject_identity_id=identity_id,
        payload_schema_version=payload_schema_version,
        payload_json={"representation_id": str(representation_id), "ann_key": ann_key},
        created_at=now,
    )
    session.add(evidence)
    session.flush()  # evidence.id is set by default, but the row must exist for the FK below
    session.add(
        EvidenceRepresentation(
            evidence_id=evidence.id,
            representation_id=representation_id,
            role=EvidenceRepresentationRole.SUBJECT,
        )
    )
    session.add(
        IndexOperation(
            id=new_id(),
            representation_id=representation_id,
            representation_space_id=representation.representation_space_id,
            operation="ADD",
            state="PENDING",
            attempt_count=0,
            not_before_at=now,
            created_at=now,
            updated_at=now,
        )
    )
    session.flush()
    return representation
