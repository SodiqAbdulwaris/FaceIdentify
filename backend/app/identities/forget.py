"""Forgetting an identity (identity model §46-§49; API and Contracts.md §8.3 and §116; M5 step 4c).

`ForgetIdentity` is the only operation that removes biometric memory while the media stays. "Forget
person" is the user-facing phrase for running it on each identity of a Person: the Person record,
its name and its notes are user-authored and stay, without visual support.

The order is the owner's ("authoritative forgetting happens before physical cleanup; a cleanup
failure must not cause the forgotten identity to remain recognizable"):

1. *Authoritative forget* (one transaction, for the whole batch): each identity becomes
   `FORGOTTEN`, its Person link ends (with its own history entry), its occurrences stop being
   authoritative, every representation it owns, and every one still left on an identity merged into
   it, is queued for erasure (out of retrieval from this commit on), the face crops tied to those
   faces get their deletion intent, and `IDENTITY_FORGOTTEN` Evidence records that it happened, with
   ids only.
2. *Erasure*: `RepresentationEraser` removes the vectors from the row, the index files and the
   write-ahead log, once for the whole batch (one rebuild per space), and the crops' bytes go. A
   crash or a locked file leaves the representations `ERASING` and the crops `DELETING`; startup
   recovery finishes both, and a repeat of the request does too (also for a Person whose links are
   already gone: the work still owed is found through the forgotten identities).

The faces themselves (observations, their boxes and the source media) stay as media-analysis data,
but no longer resolve to anyone. Nothing is remembered of what the face looked like, so a later
image of the same person is a new unknown identity (§47): ERASED vectors are not retrievable, and
nothing here reconnects them.
"""

import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from backend.app.identities.models import Evidence, EvidenceKind, Identity, IdentityState
from backend.app.identities.use_cases import (
    IdentityManagerError,
    StaleRevisionError,
    _active_association,
)
from backend.app.memory.erasure import CHUNK, RepresentationEraser
from backend.app.memory.models import (
    Observation,
    Occurrence,
    OccurrenceState,
    Representation,
    RepresentationState,
)
from backend.app.people.models import IdentityPersonAssociation, Person, PersonState
from backend.app.people.use_cases import remove_identity_from_person
from backend.app.sources.artifact_storage import (
    DELETABLE_STATES,
    complete_artifact_deletion,
    request_artifact_deletion,
    transition_artifact,
)
from backend.app.sources.models import Artifact, ArtifactState, StorageMode
from backend.infrastructure.db.unit_of_work import UnitOfWork
from backend.infrastructure.storage.files import ManagedFileStore
from backend.infrastructure.storage.layout import UnsafeStorageKeyError


class IdentityNotFoundError(IdentityManagerError):
    """No such identity, or one that is not (or no longer) there to forget."""


class PersonNotFoundError(IdentityManagerError):
    """No such Person, or one that is not active."""


# The representations whose vectors a forget has to remove, whatever they are doing now.
_WITH_VECTOR = (
    RepresentationState.ACTIVE,
    RepresentationState.PENDING,
    RepresentationState.SUPERSEDED,
    RepresentationState.ERASING,
    RepresentationState.DELETED,
)


@dataclass
class ForgetReport:
    identity_ids: list[uuid.UUID]
    # True when every vector is erased (the index files and the log included) and every crop's bytes
    # are gone.
    complete: bool
    # What is still owed (a locked index file or crop, a log that could not be truncated); the next
    # start and a repeat of the request retry it. The identities are already forgotten and
    # unrecognizable.
    outstanding: list[str] = field(default_factory=list)
    # False for a repeat that found everything already forgotten and nothing left to do.
    changed: bool = True


@dataclass
class _Plan:
    changed: bool = False
    identity_ids: list[uuid.UUID] = field(default_factory=list)
    vectors: list[uuid.UUID] = field(default_factory=list)
    crops: list[tuple[uuid.UUID, str]] = field(default_factory=list)


class ForgetIdentityUseCase:
    def __init__(
        self,
        unit_of_work: UnitOfWork,
        eraser: RepresentationEraser,
        store: ManagedFileStore,
        *,
        clock: Callable[[], datetime],
        new_id: Callable[[], uuid.UUID],
    ) -> None:
        self._uow = unit_of_work
        self._eraser = eraser
        self._store = store
        self._clock = clock
        self._new_id = new_id

    def forget(
        self, identity_id: uuid.UUID, *, expected_revision: int | None = None
    ) -> ForgetReport:
        """Forget one identity. Safe to repeat: a `FORGOTTEN` one only has its cleanup finished.
        With `expected_revision`, a changed identity is `StaleRevisionError`, not forgotten."""

        def plan(session: Session, now: datetime) -> _Plan:
            result = _Plan()
            self._one(session, identity_id, expected_revision, now, result)
            self._eraser.queue_in(session, result.vectors)
            return result

        return self._run(plan)

    def forget_person(self, person_id: uuid.UUID) -> ForgetReport:
        """Forget every identity linked to the Person, in one transaction and one erasure. The
        Person, their name and their notes stay. A repeat finishes the cleanup still owed."""

        def plan(session: Session, now: datetime) -> _Plan:
            person = session.get(Person, person_id)
            if person is None or person.state != PersonState.ACTIVE:
                raise PersonNotFoundError(f"person {person_id} does not exist")
            result = _Plan()
            linked = list(
                session.scalars(
                    select(IdentityPersonAssociation.identity_id)
                    .where(IdentityPersonAssociation.person_id == person_id)
                    .distinct()
                )
            )
            for identity_id in linked:
                state = session.scalar(select(Identity.state).where(Identity.id == identity_id))
                link = _active_association(session, identity_id)
                belongs = link is not None and link.person_id == person_id
                # a forgotten one only has its owed cleanup collected; an active one that was
                # moved to someone else since is not this Person's any more
                if state == IdentityState.FORGOTTEN or (state == IdentityState.ACTIVE and belongs):
                    self._one(session, identity_id, None, now, result)
            self._eraser.queue_in(session, result.vectors)
            return result

        return self._run(plan)

    # --- the two steps ------------------------------------------------------------------

    def _run(self, plan: Callable[[Session, datetime], _Plan]) -> ForgetReport:
        now = self._clock()
        done = self._uow.write(lambda session: plan(session, now))
        outstanding: list[str] = []
        for artifact_id, key in done.crops:
            try:
                complete_artifact_deletion(self._uow, self._store, artifact_id, clock=self._clock)
                self._store.staging_path(key).unlink(missing_ok=True)  # a write that never finished
            except (OSError, UnsafeStorageKeyError) as error:
                outstanding.append(f"crop {artifact_id}: {type(error).__name__}: {error}")
        changed = done.changed
        if done.vectors:
            report = self._eraser.erase(done.vectors)
            outstanding += report.outstanding_cleanup
            # A repeat that finished an erasure that was owed did change something.
            changed = changed or bool(report.erased)
        else:  # nothing to erase, but the log of an earlier try may still be owed
            outstanding += self._eraser.settle_log()
        return ForgetReport(done.identity_ids, not outstanding, outstanding, changed=changed)

    def _one(
        self,
        session: Session,
        identity_id: uuid.UUID,
        expected_revision: int | None,
        now: datetime,
        plan: _Plan,
    ) -> None:
        """Forget one identity inside the batch's transaction, or collect what its earlier
        forgetting still owes."""
        identity = session.get(Identity, identity_id, populate_existing=True)
        if identity is None:
            raise IdentityNotFoundError(f"identity {identity_id} does not exist")
        family = _family(session, identity_id)
        plan.identity_ids.append(identity_id)
        if identity.state == IdentityState.FORGOTTEN:
            for chunk in _chunks(family):
                plan.vectors += session.scalars(
                    select(Representation.id).where(
                        Representation.identity_id.in_(chunk),
                        Representation.state == RepresentationState.ERASING,
                    )
                )
            plan.crops += _retire_crops(session, family, now)
            return
        if identity.state != IdentityState.ACTIVE:
            raise IdentityNotFoundError(
                f"identity {identity_id} is {identity.state}; only an active one can be forgotten"
            )
        if expected_revision is not None and identity.revision != expected_revision:
            raise StaleRevisionError(
                f"identity {identity_id} changed since it was read"
                f" (it is no longer at revision {expected_revision})"
            )

        link = _active_association(session, identity_id)
        person_id = None if link is None else link.person_id
        if link is not None:
            remove_identity_from_person(
                session, identity_id, new_id=self._new_id, clock=self._clock
            )
        # Every vector of the identity, and of each identity merged into it: a merge moves only the
        # active ones, so the others (superseded, pending, deleted) are still on the predecessors.
        vectors = [
            vector_id
            for chunk in _chunks(family)
            for vector_id in session.scalars(
                select(Representation.id).where(
                    Representation.identity_id.in_(chunk),
                    Representation.state.in_(_WITH_VECTOR),
                )
            )
        ]
        faces = list(
            session.scalars(
                select(Occurrence.id).where(
                    Occurrence.identity_id == identity_id,
                    Occurrence.state == OccurrenceState.ACTIVE,
                )
            )
        )
        crops = _retire_crops(session, family, now)  # the face crops are face material too
        session.add(
            Evidence(
                id=self._new_id(),
                kind=EvidenceKind.IDENTITY_FORGOTTEN,
                subject_identity_id=identity_id,
                subject_person_id=person_id,
                payload_schema_version=1,
                payload_json={
                    "representation_ids": [str(v) for v in vectors],
                    "occurrence_ids": [str(f) for f in faces],
                },
                created_at=now,
            )
        )
        no_sync = {"synchronize_session": False}
        for chunk in _chunks(faces):
            session.execute(
                update(Occurrence)
                .where(Occurrence.id.in_(chunk))
                .values(state=OccurrenceState.DELETED),
                execution_options=no_sync,
            )
        # (not optimistic_locked_update: the revision was checked above, and ending the Person link
        # has changed it since, inside this same write)
        for chunk in _chunks(family):
            session.execute(
                update(Identity)
                .where(Identity.id.in_(chunk))
                .values(representative_observation_id=None),
                execution_options=no_sync,
            )
        session.execute(
            update(Identity)
            .where(Identity.id == identity_id)
            .values(
                state=IdentityState.FORGOTTEN,
                forgotten_at=now,
                updated_at=now,
                revision=Identity.revision + 1,
            ),
            execution_options=no_sync,
        )
        plan.changed = True
        plan.vectors += vectors
        plan.crops += crops


def _chunks(items: Sequence[uuid.UUID]) -> list[Sequence[uuid.UUID]]:
    """Bound parameters per statement stay under the database limit however large the family."""
    return [items[start : start + CHUNK] for start in range(0, len(items), CHUNK)]


def _family(session: Session, identity_id: uuid.UUID) -> list[uuid.UUID]:
    """The identity and every identity merged into it, directly or through others."""
    family = [identity_id]
    seen = {identity_id}
    frontier = [identity_id]
    while frontier:
        found = [
            found_id
            for chunk in _chunks(frontier)
            for found_id in session.scalars(
                select(Identity.id).where(Identity.merged_into_identity_id.in_(chunk))
            )
            if found_id not in seen
        ]
        seen.update(found)
        family += found
        frontier = found
    return family


# Every state in which a managed crop still has bytes, or an intent to delete them, to finish.
_UNFINISHED = (
    ArtifactState.PENDING,
    *DELETABLE_STATES,
    ArtifactState.DELETING,
    ArtifactState.DELETED,  # (finished, but a half-written copy may still be left to remove)
)


def _retire_crops(
    session: Session, family: Sequence[uuid.UUID], now: datetime
) -> list[tuple[uuid.UUID, str]]:
    """The face crops of the faces these identities own that are still to be deleted, each with its
    storage key: an available or missing one gets its deletion intent, a pending write is turned
    into one, one already being deleted is just collected so its bytes are finished. A crop that a
    face of someone else still shows is theirs too and is left alone."""
    members = set(family)
    candidates: dict[uuid.UUID, tuple[str, str]] = {}
    for chunk in _chunks(family):
        for artifact_id, state, key in session.execute(
            select(Artifact.id, Artifact.state, Artifact.storage_key)
            .join(Observation, Observation.face_crop_artifact_id == Artifact.id)
            .join(Representation, Representation.observation_id == Observation.id)
            .where(
                Representation.identity_id.in_(chunk),
                Artifact.storage_mode == StorageMode.MANAGED,
                Artifact.state.in_(_UNFINISHED),
            )
            .distinct()
        ):
            assert key is not None  # (a managed artifact always has its storage key)
            candidates[artifact_id] = (state, key)
    shared: set[uuid.UUID] = set()
    for chunk in _chunks(list(candidates)):
        shared.update(
            artifact_id
            for artifact_id, owner in session.execute(
                select(Observation.face_crop_artifact_id, Representation.identity_id)
                .join(Representation, Representation.observation_id == Observation.id)
                .where(
                    Observation.face_crop_artifact_id.in_(chunk),
                    # a face already erased (or forgotten) no longer needs its crop
                    Representation.state.in_(_WITH_VECTOR),
                )
            )
            if owner not in members
        )
    crops: list[tuple[uuid.UUID, str]] = []
    for artifact_id, (state, key) in candidates.items():
        if artifact_id in shared:
            continue
        if state == ArtifactState.PENDING:
            transition_artifact(
                session,
                artifact_id,
                {ArtifactState.PENDING},
                {"state": ArtifactState.DELETING, "delete_requested_at": now},
            )
        elif state in DELETABLE_STATES:
            request_artifact_deletion(session, artifact_id, clock=lambda: now)
        crops.append((artifact_id, key))
    return crops
