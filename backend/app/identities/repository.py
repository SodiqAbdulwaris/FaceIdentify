"""Repositories for identities, occurrences and evidence
(PERSISTENCE_IMPLEMENTATION.md §26: "lock/get/create and append the semantic links needed by their
use cases").

Like the other repositories they join the caller's transaction and never commit, and every change
is one statement decided by the database. The Identity Manager's use cases (`use_cases.py`) still
work on the ORM objects directly; these are the persistence mechanics they and the later use cases
(forget, occurrence building) are built on, and nothing here decides business truth.

* `IdentityRepository.lock` is the "lock/reload" of §9 for SQLite, which has one writer and no row
  locks: it starts the caller's write transaction *before* it reads, with a write that changes
  nothing, then returns the row fresh. A transaction that has already read cannot do that: if
  another writer commits in between it fails at once with `SQLITE_BUSY_SNAPSHOT` (CONTEXT open
  question 20). `transition` is the shared optimistic-locked `UPDATE` (§2): the expected revision
  *and* the expected states are part of the statement, so a stale caller changes nothing.
* Evidence is append-only. `EvidenceRepository` has no update that touches a payload; the only
  change to an existing row is `mark_superseded`, the explanatory `superseded_at` marker, which is
  set once. (Immutability of evidence is a rule of this repository, not of the database.)
* Pages are keyset-paginated, newest first with ties by id (§22), so rows added between two page
  requests cannot shift or repeat a page.
"""

import uuid
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast

from sqlalchemy import CursorResult, and_, or_, select, update
from sqlalchemy.orm import Session

from backend.app.identities.models import (
    Evidence,
    EvidenceCandidate,
    EvidenceRepresentation,
    EvidenceRepresentationRole,
    Identity,
    IdentityLineage,
    IdentityState,
)
from backend.app.memory.models import Occurrence, OccurrenceObservation, OccurrenceState
from backend.infrastructure.db.optimistic import optimistic_locked_update


def _states(states: Collection[str]) -> list[str]:
    """A bare string is a `Collection[str]` too, and would silently become a list of letters."""
    if isinstance(states, str):
        raise TypeError("states must be a collection of state names, not a single string")
    return list(states)


@dataclass(frozen=True)
class Cursor:
    """Where the next page starts: after the row with this `created_at` and `id` (newest first)."""

    created_at: datetime
    id: uuid.UUID


def _older_than(model: type[Any], after: Cursor) -> Any:
    return or_(
        model.created_at < after.created_at,
        and_(model.created_at == after.created_at, model.id < after.id),
    )


def _next_cursor(rows: list[Any], limit: int) -> Cursor | None:
    """`rows` were read with `limit + 1`: a next page exists if the extra one came back."""
    if len(rows) <= limit:
        return None
    last = rows[limit - 1]
    return Cursor(last.created_at, last.id)


class IdentityRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, identity: Identity) -> Identity:
        """Stage a new identity and flush, so its constraints are checked now."""
        self._session.add(identity)
        self._session.flush()
        return identity

    def get(self, identity_id: uuid.UUID) -> Identity | None:
        """The row as the database has it now, not as this session last saw it."""
        return self._session.get(Identity, identity_id, populate_existing=True)

    def lock(self, identity_id: uuid.UUID) -> Identity | None:
        """Take the write lock, then return the identity fresh (None if there is none). Held until
        the caller commits or rolls back; call it as the first statement of the transaction: one
        that has already read keeps its snapshot and can fail with `SQLITE_BUSY_SNAPSHOT` when
        another writer commits in between (CONTEXT open question 20)."""
        self._session.execute(
            update(Identity)
            .where(Identity.id == identity_id)
            .values(revision=Identity.revision)  # a write that changes nothing
            .execution_options(synchronize_session=False)
        )
        return self.get(identity_id)

    def transition(
        self,
        identity_id: uuid.UUID,
        *,
        expected_revision: int,
        from_states: Collection[str],
        to_state: str,
        now: datetime,
        merged_into_identity_id: uuid.UUID | None = None,
    ) -> bool:
        """Move the identity to `to_state` if its revision is `expected_revision` and its state is
        one of `from_states` now: one guarded `UPDATE` that bumps the revision. `activated_at` is
        set on becoming `ACTIVE`, `forgotten_at` on `FORGOTTEN`, `merged_into_identity_id` when
        given (a `MERGED` identity must name its target: the schema enforces it). False if the
        revision or state no longer matched. Re-read the row with `get`: no in-memory copy is
        updated."""
        values: dict[str, Any] = {"state": to_state, "updated_at": now}
        if to_state == IdentityState.ACTIVE:
            values["activated_at"] = now
        if to_state == IdentityState.FORGOTTEN:
            values["forgotten_at"] = now
        if merged_into_identity_id is not None:
            values["merged_into_identity_id"] = merged_into_identity_id
        return bool(
            optimistic_locked_update(
                self._session,
                Identity,
                identity_id,
                expected_revision=expected_revision,
                values=values,
                extra_where=[Identity.state.in_(_states(from_states))],
            )
        )

    def add_lineage(self, lineage: IdentityLineage) -> IdentityLineage:
        """Record a merge or split edge (the structural history, §7) and flush."""
        self._session.add(lineage)
        self._session.flush()
        return lineage


class OccurrenceRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, occurrence: Occurrence, observation_ids: Sequence[uuid.UUID]) -> Occurrence:
        """Stage the occurrence with its observations, in the order given (`ordinal` 0, 1, ...),
        and flush. An observation listed twice is the database's `IntegrityError`. That the list is
        not empty, or contains the representative observation, is the use case's rule (§11)."""
        self._session.add(occurrence)
        self._session.flush()  # the membership rows reference the occurrence
        self._session.add_all(
            OccurrenceObservation(
                occurrence_id=occurrence.id, observation_id=observation_id, ordinal=ordinal
            )
            for ordinal, observation_id in enumerate(observation_ids)
        )
        self._session.flush()
        return occurrence

    def get(self, occurrence_id: uuid.UUID) -> Occurrence | None:
        return self._session.get(Occurrence, occurrence_id, populate_existing=True)

    def observation_ids(self, occurrence_id: uuid.UUID) -> list[uuid.UUID]:
        """The occurrence's observations in order."""
        return list(
            self._session.scalars(
                select(OccurrenceObservation.observation_id)
                .where(OccurrenceObservation.occurrence_id == occurrence_id)
                .order_by(OccurrenceObservation.ordinal)
            )
        )

    def page_for_source(
        self, source_id: uuid.UUID, *, state: str, limit: int, after: Cursor | None = None
    ) -> tuple[list[Occurrence], Cursor | None]:
        """Up to `limit` occurrences of a source in `state`, newest first, and the next cursor."""
        return self._page(Occurrence.source_id == source_id, state, limit, after)

    def page_for_identity(
        self, identity_id: uuid.UUID, *, state: str, limit: int, after: Cursor | None = None
    ) -> tuple[list[Occurrence], Cursor | None]:
        """Up to `limit` occurrences of an identity in `state`, newest first, and a cursor."""
        return self._page(Occurrence.identity_id == identity_id, state, limit, after)

    def _page(
        self, owner: Any, state: str, limit: int, after: Cursor | None
    ) -> tuple[list[Occurrence], Cursor | None]:
        if limit < 1:
            raise ValueError("a page holds at least one occurrence")
        query = select(Occurrence).where(owner, Occurrence.state == state)
        if after is not None:
            query = query.where(_older_than(Occurrence, after))
        rows = list(
            self._session.scalars(
                query.order_by(Occurrence.created_at.desc(), Occurrence.id.desc())
                .limit(limit + 1)  # one more than asked: whether there is a next page
                .execution_options(populate_existing=True)
            )
        )
        return rows[:limit], _next_cursor(rows, limit)

    def transition(
        self,
        occurrence_id: uuid.UUID,
        *,
        from_states: Collection[str],
        to_state: str,
        now: datetime,
    ) -> bool:
        """Move the occurrence to `to_state` only if it is in one of `from_states` now: one guarded
        `UPDATE`; `activated_at` is set on becoming `ACTIVE`. False if it was not."""
        values: dict[str, Any] = {"state": to_state}
        if to_state == OccurrenceState.ACTIVE:
            values["activated_at"] = now
        result = cast(
            "CursorResult[Any]",
            self._session.execute(
                update(Occurrence)
                .where(Occurrence.id == occurrence_id, Occurrence.state.in_(_states(from_states)))
                .values(**values)
                .execution_options(synchronize_session=False)
            ),
        )
        return bool(result.rowcount)


@dataclass(frozen=True)
class EvidenceLink:
    representation_id: uuid.UUID
    role: EvidenceRepresentationRole


class EvidenceRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def append(
        self,
        evidence: Evidence,
        *,
        representations: Sequence[EvidenceLink] = (),
        candidates: Sequence[EvidenceCandidate] = (),
    ) -> Evidence:
        """Append the evidence with the representations it cites and its ranked candidates, then
        flush. Candidates keep the `rank` they carry (their original order); their `evidence_id`
        is set here, on the caller's objects."""
        self._session.add(evidence)
        self._session.flush()  # the links and candidates reference the evidence
        self._session.add_all(
            EvidenceRepresentation(
                evidence_id=evidence.id, representation_id=link.representation_id, role=link.role
            )
            for link in representations
        )
        for candidate in candidates:
            candidate.evidence_id = evidence.id
        self._session.add_all(candidates)
        self._session.flush()
        return evidence

    def get(self, evidence_id: uuid.UUID) -> Evidence | None:
        return self._session.get(Evidence, evidence_id, populate_existing=True)

    def candidates(self, evidence_id: uuid.UUID) -> list[EvidenceCandidate]:
        """The evidence's candidates in their original rank order."""
        return list(
            self._session.scalars(
                select(EvidenceCandidate)
                .where(EvidenceCandidate.evidence_id == evidence_id)
                .order_by(EvidenceCandidate.rank)
                .execution_options(populate_existing=True)
            )
        )

    def links(self, evidence_id: uuid.UUID) -> list[EvidenceLink]:
        rows = self._session.execute(
            select(EvidenceRepresentation.representation_id, EvidenceRepresentation.role)
            .where(EvidenceRepresentation.evidence_id == evidence_id)
            .order_by(EvidenceRepresentation.role, EvidenceRepresentation.representation_id)
        ).all()
        return [
            EvidenceLink(representation_id, EvidenceRepresentationRole(role))
            for representation_id, role in rows
        ]

    def page_for_identity(
        self, identity_id: uuid.UUID, *, limit: int, after: Cursor | None = None
    ) -> tuple[list[Evidence], Cursor | None]:
        """Up to `limit` evidence rows about an identity, newest first (ties by id descending),
        and the next cursor (None on the last page)."""
        if limit < 1:
            raise ValueError("a page holds at least one evidence row")
        query = select(Evidence).where(Evidence.subject_identity_id == identity_id)
        if after is not None:
            query = query.where(_older_than(Evidence, after))
        rows = list(
            self._session.scalars(
                query.order_by(Evidence.created_at.desc(), Evidence.id.desc())
                .limit(limit + 1)
                .execution_options(populate_existing=True)
            )
        )
        return rows[:limit], _next_cursor(rows, limit)

    def mark_superseded(self, evidence_id: uuid.UUID, *, now: datetime) -> bool:
        """Set the explanatory `superseded_at` marker, once. The payload is never rewritten. False
        if it was already set or the evidence does not exist."""
        result = cast(
            "CursorResult[Any]",
            self._session.execute(
                update(Evidence)
                .where(Evidence.id == evidence_id, Evidence.superseded_at.is_(None))
                .values(superseded_at=now)
                .execution_options(synchronize_session=False)
            ),
        )
        return bool(result.rowcount)
