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
from collections.abc import Callable, Sequence
from datetime import datetime

from sqlalchemy import exists, insert, select, update
from sqlalchemy.orm import Session

from backend.app.identities.models import (
    Evidence,
    EvidenceKind,
    EvidenceRepresentation,
    EvidenceRepresentationRole,
    Identity,
    IdentityLineage,
    IdentityLineageKind,
    IdentityState,
)
from backend.app.memory.models import (
    AnnKeySequence,
    IndexOperation,
    Representation,
    RepresentationState,
)
from backend.app.people.models import AssociationState, IdentityPersonAssociation
from backend.infrastructure.db.optimistic import optimistic_locked_update


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
    rowcount = optimistic_locked_update(
        session,
        Identity,
        identity_id,
        expected_revision=expected_revision,
        values={"state": IdentityState.ACTIVE, "activated_at": now, "updated_at": now},
        extra_where=(Identity.state == IdentityState.PENDING,),
    )
    if rowcount == 0:
        _raise_activation_conflict(session, identity_id, expected_revision)
    session.flush()
    # populate_existing forces a fresh read; optimistic_locked_update disables session-sync
    # (see its docstring), so this session's cached copy cannot be trusted otherwise.
    identity = session.get(Identity, identity_id, populate_existing=True)
    assert identity is not None  # the UPDATE above just matched this row
    return identity


def _raise_activation_conflict(
    session: Session, identity_id: uuid.UUID, expected_revision: int
) -> None:
    """Distinguish a stale revision from an identity that was never PENDING.

    `populate_existing=True`, for the same reason as `activate_identity`'s own re-fetch: the
    caller almost always already holds this row (it read `expected_revision` from it), and
    without forcing a fresh read this would compare against the caller's own stale in-memory
    copy rather than what is actually in the database right now.
    """
    identity = session.get(Identity, identity_id, populate_existing=True)
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
    """Allocate the next positive ANN key for a space (§6.3). Guarded and race-safe.

    Allocation happens inside the caller's transaction, so a committed key is never handed out
    again, but a rolled-back allocation is (see `.agents/CONTEXT.md` open question 21).

    The sequence row is created lazily on first allocation: no spec text assigns that
    responsibility elsewhere, and RepresentationSpace creation (PR #4) does not create it.
    """
    session.execute(
        insert(AnnKeySequence)
        .prefix_with("OR IGNORE")
        .values(representation_space_id=representation_space_id, next_ann_key=1)
    )
    # scalar_one() is intentional, not scalar_one_or_none(): nothing deletes ann_key_sequences
    # rows and its FK to representation_spaces is RESTRICT, so the row this UPDATE targets
    # (just INSERT-OR-IGNORE'd above) cannot be missing. If that ever stops being true, this
    # fails loudly with NoResultFound rather than silently returning a wrong key.
    return session.execute(
        update(AnnKeySequence)
        .where(AnnKeySequence.representation_space_id == representation_space_id)
        .values(next_ann_key=AnnKeySequence.next_ann_key + 1)
        .returning(AnnKeySequence.next_ann_key - 1)
    ).scalar_one()


def _has_creation_evidence(session: Session, identity_id: uuid.UUID) -> bool:
    return bool(
        session.scalar(
            select(
                exists().where(
                    Evidence.subject_identity_id == identity_id,
                    Evidence.kind == EvidenceKind.IDENTITY_CREATED,
                )
            )
        )
    )


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
    if evidence_kind == EvidenceKind.IDENTITY_CREATED and _has_creation_evidence(
        session, identity_id
    ):
        # IDENTITY_CREATED is the founding evidence for an identity, recorded once. Every later
        # assignment to that identity, even moments afterwards in the same run, is a match
        # against an identity that already exists by the time this call happens.
        raise IdentityManagerError(
            f"identity {identity_id} already has IDENTITY_CREATED evidence;"
            " use IDENTITY_MATCHED for a later assignment to an existing identity"
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


# --- merge -----------------------------------------------------------------------------------


def _active_association(
    session: Session, identity_id: uuid.UUID
) -> IdentityPersonAssociation | None:
    return session.scalar(
        select(IdentityPersonAssociation).where(
            IdentityPersonAssociation.identity_id == identity_id,
            IdentityPersonAssociation.state == AssociationState.ACTIVE,
        )
    )


def _reconcile_person_on_merge(
    session: Session,
    losing_identity_id: uuid.UUID,
    surviving_identity_id: uuid.UUID,
    *,
    new_id: Callable[[], uuid.UUID],
    clock: Callable[[], datetime],
) -> None:
    """§114 "reconcile Person relationship": the survivor's own naming always wins.

    If only the losing identity had an active Person link, that naming carries over to the
    survivor (a fresh association + `Evidence`, exactly as `assign_identity_to_person` would
    create — duplicated in miniature here rather than imported, to avoid a circular import
    between `identities.use_cases` and `people.use_cases`, which itself imports this module).
    Either way, the losing identity's own association can no longer be current once its identity
    is merged away.
    """
    loser_association = _active_association(session, losing_identity_id)
    if loser_association is None:
        return
    now = clock()
    if _active_association(session, surviving_identity_id) is None:
        evidence = Evidence(
            id=new_id(),
            kind=EvidenceKind.IDENTITY_ASSIGNED_TO_PERSON,
            subject_identity_id=surviving_identity_id,
            subject_person_id=loser_association.person_id,
            payload_schema_version=1,
            payload_json={"carried_over_from_identity_id": str(losing_identity_id)},
            created_at=now,
        )
        session.add(evidence)
        session.flush()
        session.add(
            IdentityPersonAssociation(
                id=new_id(),
                identity_id=surviving_identity_id,
                person_id=loser_association.person_id,
                state=AssociationState.ACTIVE,
                evidence_id=evidence.id,
                created_at=now,
            )
        )
    # A plain increment: freshly fetched in this same transaction (see people/use_cases.py's
    # matching comment for why that is safe under SQLite's single-writer model).
    loser_association.state = AssociationState.SUPERSEDED
    loser_association.ended_at = now
    loser_association.revision += 1


def merge_identities(
    session: Session,
    losing_identity_id: uuid.UUID,
    surviving_identity_id: uuid.UUID,
    *,
    expected_revision: int,
    new_id: Callable[[], uuid.UUID],
    clock: Callable[[], datetime],
    payload_schema_version: int = 1,
) -> Identity:
    """Merge one Identity into another (§114). The losing identity keeps its row and history.

    Merge is Identity-level (identity-and-memory-model-v1.md §18, decision 2026-09-23): the
    losing identity becomes `MERGED` with `merged_into_identity_id` set and an `identity_lineage`
    `MERGED_INTO` edge, never deleted. Its active representations move to the survivor (their
    `ann_key` is untouched — merge does not change ANN eligibility, only ownership, so no
    `IndexOperation` is created). A three-or-more-way merge is done by calling this once per
    losing identity: each call is independently atomic and history-preserving, so composing them
    reaches the same end state as a single N-way operation without this function having to
    arbitrate which of several losing identities' Person links should win.

    `expected_revision` guards the losing identity only: it is the one whose own row changes.
    The survivor's row is not touched by a merge (only its representations/associations), so it
    takes no revision.
    """
    if losing_identity_id == surviving_identity_id:
        raise IdentityManagerError("cannot merge an identity into itself")

    survivor = session.get(Identity, surviving_identity_id)
    if survivor is None:
        raise IdentityManagerError(f"identity {surviving_identity_id} does not exist")
    if survivor.state != IdentityState.ACTIVE:
        raise IdentityManagerError(
            f"identity {surviving_identity_id} is {survivor.state}, not ACTIVE;"
            " only an active identity can survive a merge"
        )
    loser = session.get(Identity, losing_identity_id)
    if loser is None:
        raise IdentityManagerError(f"identity {losing_identity_id} does not exist")
    if loser.state != IdentityState.ACTIVE:
        raise IdentityManagerError(
            f"identity {losing_identity_id} is {loser.state}, not ACTIVE;"
            " only an active identity can be merged away"
        )

    _reconcile_person_on_merge(
        session, losing_identity_id, surviving_identity_id, new_id=new_id, clock=clock
    )

    now = clock()
    moved_representation_ids = session.scalars(
        select(Representation.id).where(
            Representation.identity_id == losing_identity_id,
            Representation.state == RepresentationState.ACTIVE,
        )
    ).all()
    session.execute(
        update(Representation)
        .where(
            Representation.identity_id == losing_identity_id,
            Representation.state == RepresentationState.ACTIVE,
        )
        .values(identity_id=surviving_identity_id),
        execution_options={"synchronize_session": False},
    )

    evidence = Evidence(
        id=new_id(),
        kind=EvidenceKind.IDENTITY_MERGED,
        subject_identity_id=losing_identity_id,
        payload_schema_version=payload_schema_version,
        payload_json={
            "merged_into_identity_id": str(surviving_identity_id),
            "moved_representation_ids": [str(rep_id) for rep_id in moved_representation_ids],
        },
        created_at=now,
    )
    session.add(evidence)
    session.flush()
    for representation_id in moved_representation_ids:
        session.add(
            EvidenceRepresentation(
                evidence_id=evidence.id,
                representation_id=representation_id,
                role=EvidenceRepresentationRole.SUBJECT,
            )
        )
    session.add(
        IdentityLineage(
            id=new_id(),
            from_identity_id=losing_identity_id,
            to_identity_id=surviving_identity_id,
            kind=IdentityLineageKind.MERGED_INTO,
            evidence_id=evidence.id,
            created_at=now,
        )
    )

    rowcount = optimistic_locked_update(
        session,
        Identity,
        losing_identity_id,
        expected_revision=expected_revision,
        values={
            "state": IdentityState.MERGED,
            "merged_into_identity_id": surviving_identity_id,
            "updated_at": now,
        },
        extra_where=(Identity.state == IdentityState.ACTIVE,),
    )
    if rowcount == 0:
        # Re-validated above under the same transaction; only a concurrent revision change
        # between that check and here can land here (single-writer SQLite makes this
        # unreachable in practice, but the guard is cheap and matches activate_identity's).
        raise StaleRevisionError(
            f"identity {losing_identity_id} changed since it was read for this merge"
        )
    session.flush()
    return survivor


# --- split -----------------------------------------------------------------------------------


def split_identity(
    session: Session,
    source_identity_id: uuid.UUID,
    representation_ids: Sequence[uuid.UUID],
    *,
    new_id: Callable[[], uuid.UUID],
    clock: Callable[[], datetime],
    payload_schema_version: int = 1,
) -> Identity:
    """Split selected representations of one Identity into a new one (§19.2, §115).

    `representation_ids` is the caller's decision (API and Contracts §8.2: "A split identifies
    selected observations/evidence that should form a new Identity" — the backend does not
    decide which). The source identity keeps everything not listed and stays `ACTIVE`; nothing
    requires it to retain at least one representation, so the caller may split away all of them.
    The new identity is created directly `ACTIVE` (not `PENDING`): unlike recognition-created
    identities (§7, "only an accepted processing run may activate a pending identity"), this is
    an already-decided human action with no processing run to accept it.

    `identities.state = SPLIT` is not used here: neither identity stops being independently
    current (the conceptual example in identity-and-memory-model-v1.md §19.2 has the source keep
    some evidence), so nothing here warrants a terminal state. See `.agents/CONTEXT.md` for this
    as an open question if that reading is wrong.
    """
    source = session.get(Identity, source_identity_id)
    if source is None:
        raise IdentityManagerError(f"identity {source_identity_id} does not exist")
    if source.state != IdentityState.ACTIVE:
        raise IdentityManagerError(
            f"identity {source_identity_id} is {source.state}, not ACTIVE;"
            " only an active identity can be split"
        )
    if not representation_ids:
        raise IdentityManagerError("split requires at least one representation to move")

    representations = [session.get(Representation, rep_id) for rep_id in representation_ids]
    for representation_id, representation in zip(representation_ids, representations, strict=True):
        if representation is None:
            raise IdentityManagerError(f"representation {representation_id} does not exist")
        if representation.identity_id != source_identity_id:
            raise IdentityManagerError(
                f"representation {representation_id} does not belong to identity"
                f" {source_identity_id}"
            )
        if representation.state != RepresentationState.ACTIVE:
            raise IdentityManagerError(
                f"representation {representation_id} is {representation.state}, not ACTIVE"
            )

    now = clock()
    new_identity = Identity(
        id=new_id(),
        state=IdentityState.ACTIVE,
        created_by_processing_run_id=None,
        created_at=now,
        activated_at=now,
        updated_at=now,
    )
    session.add(new_identity)
    session.flush()

    evidence = Evidence(
        id=new_id(),
        kind=EvidenceKind.IDENTITY_SPLIT,
        subject_identity_id=new_identity.id,
        payload_schema_version=payload_schema_version,
        payload_json={
            "split_from_identity_id": str(source_identity_id),
            "moved_representation_ids": [str(rep_id) for rep_id in representation_ids],
        },
        created_at=now,
    )
    session.add(evidence)
    session.flush()

    for representation_id, representation in zip(representation_ids, representations, strict=True):
        assert representation is not None  # validated above
        representation.identity_id = new_identity.id
        session.add(
            EvidenceRepresentation(
                evidence_id=evidence.id,
                representation_id=representation_id,
                role=EvidenceRepresentationRole.SUBJECT,
            )
        )
    session.add(
        IdentityLineage(
            id=new_id(),
            from_identity_id=source_identity_id,
            to_identity_id=new_identity.id,
            kind=IdentityLineageKind.SPLIT_FROM,
            evidence_id=evidence.id,
            created_at=now,
        )
    )
    session.flush()
    return new_identity


# --- query-only recognition --------------------------------------------------------------------


def resolve_recognition_candidates(
    session: Session, candidate_identity_ids: Sequence[uuid.UUID]
) -> list[Identity]:
    """Revalidate ANN-retrieved candidates against authoritative SQLite state (`API and
    Contracts.md` §12.2: "ANN candidate retrieval -> authoritative SQLite revalidation"), for a
    face *query* (`POST /api/v1/search/face`). A query is read-only by contract: it "creates no
    Source, Observation, Identity, Evidence, persistent memory" — this function only ever reads
    (`session.get`), never writes, so it cannot violate that regardless of what candidates it is
    given (IMPLEMENTATION_ARCHITECTURE.md §32 rule 7: "never allow query-only recognition to
    silently become ingest").

    The derived ANN index can be stale relative to SQLite: a candidate identity may since have
    been merged away, forgotten, or deleted. Each candidate is resolved to its current, ACTIVE
    identity or dropped; input order is preserved and duplicate resolutions collapse to one.

    `populate_existing=True` forces a fresh read on every fetch: "authoritative revalidation" is
    the function's entire purpose, so it must not answer from a stale, already-cached copy of a
    row this same session merged, forgot, or deleted moments earlier.
    """
    resolved: list[Identity] = []
    seen: set[uuid.UUID] = set()
    for candidate_id in candidate_identity_ids:
        identity = session.get(Identity, candidate_id, populate_existing=True)
        while identity is not None and identity.state == IdentityState.MERGED:
            identity = (
                session.get(Identity, identity.merged_into_identity_id, populate_existing=True)
                if identity.merged_into_identity_id is not None
                else None
            )
        if identity is None or identity.state != IdentityState.ACTIVE:
            continue
        if identity.id in seen:
            continue
        seen.add(identity.id)
        resolved.append(identity)
    return resolved
