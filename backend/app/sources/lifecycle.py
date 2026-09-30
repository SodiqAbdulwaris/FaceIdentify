"""Logical Source recycle and restore (API and Contracts.md §5.5-§5.6, §60).

"Logical recycle is primarily database state. Files are not normally physically moved merely
because a Source was recycled" (§60). Recycling only changes the Source's own row: its artifacts,
observations, evidence and processing history are left exactly as they are, so restoring "should
normally avoid reprocessing" (processing-architecture-v1.md §30). Permanent deletion is a separate
use case (PERSISTENCE_IMPLEMENTATION.md §4.2).

Functions flush but do not commit: the caller owns the transaction (§26). Each takes the revision
the caller last read (§2 optimistic locking).
"""

import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Any

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from backend.app.sources.models import Artifact, ArtifactState, Source, SourceState
from backend.infrastructure.db.optimistic import optimistic_locked_update

# An original in one of these states is in, or has been through, permanent deletion (a failed one
# may still have bytes, and is retried). Restoring would hand back a Source that can never be
# displayed or processed ("Restores... where possible", §5.6), and recycling one is pointless, so
# neither moves it.
BYTES_GONE = {ArtifactState.DELETING, ArtifactState.DELETE_FAILED, ArtifactState.DELETED}


class SourceLifecycleError(Exception):
    """A Source lifecycle change that is not valid for the Source's current state."""


class StaleSourceRevisionError(SourceLifecycleError):
    """The Source's revision no longer matches what the caller last read."""


def _original_is_going(original_artifact_id: Any) -> Any:
    return exists(
        select(Artifact.id).where(
            Artifact.id == original_artifact_id, Artifact.state.in_(BYTES_GONE)
        )
    )


def _move(
    session: Session,
    source_id: uuid.UUID,
    *,
    from_state: SourceState,
    to_state: SourceState,
    expected_revision: int,
    values: dict[str, Any],
) -> Source:
    rowcount = optimistic_locked_update(
        session,
        Source,
        source_id,
        expected_revision=expected_revision,
        values={"state": to_state, **values},
        # Evaluated by the database inside the same UPDATE, never against a cached object, so a
        # deletion that begins in another session is seen, and no read precedes the write.
        extra_where=[Source.state == from_state, ~_original_is_going(Source.original_artifact_id)],
    )
    if rowcount == 0:
        current = session.get(Source, source_id, populate_existing=True)
        if current is None:
            raise SourceLifecycleError(f"source {source_id} does not exist")
        if current.revision != expected_revision:
            raise StaleSourceRevisionError(
                f"source {source_id} is at revision {current.revision}, "
                f"expected {expected_revision}"
            )
        if current.state != from_state:
            raise SourceLifecycleError(
                f"source {source_id} is {current.state}; expected {from_state} to become {to_state}"
            )
        original = session.get(Artifact, current.original_artifact_id, populate_existing=True)
        assert original is not None  # RESTRICT foreign key: a Source's original cannot vanish
        raise SourceLifecycleError(
            f"source {source_id} cannot become {to_state}: its original is {original.state}"
        )
    session.flush()
    # populate_existing: optimistic_locked_update disables session-sync (see its docstring).
    source = session.get(Source, source_id, populate_existing=True)
    assert source is not None  # the UPDATE above just matched this row
    return source


def recycle_source(
    session: Session,
    source_id: uuid.UUID,
    *,
    expected_revision: int,
    clock: Callable[[], datetime],
) -> Source:
    """Move an ACTIVE Source to the Recycle Bin. Touches nothing but the Source row. Refused, like a
    restore, for a Source whose original is being or has been permanently deleted."""
    now = clock()
    return _move(
        session, source_id,
        from_state=SourceState.ACTIVE, to_state=SourceState.RECYCLED,
        expected_revision=expected_revision,
        values={"recycled_at": now, "updated_at": now},
    )  # fmt: skip


def restore_source(
    session: Session,
    source_id: uuid.UUID,
    *,
    expected_revision: int,
    clock: Callable[[], datetime],
) -> Source:
    """Bring a RECYCLED Source back, unless its original is being or has been deleted."""
    now = clock()
    return _move(
        session, source_id,
        from_state=SourceState.RECYCLED, to_state=SourceState.ACTIVE,
        expected_revision=expected_revision,
        values={"recycled_at": None, "updated_at": now},
    )  # fmt: skip
