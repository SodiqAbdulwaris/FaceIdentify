"""SourceRepository: the persistence mechanics of `sources`
(PERSISTENCE_IMPLEMENTATION.md §26: "add/get, library page, set current run, update lifecycle").

Like the other repositories it joins the caller's transaction and never commits, and every change
is one statement decided by the database. "Update lifecycle" is already `lifecycle.py` (recycle and
restore, which carry their own business rules); this adds the rest.

The library page is keyset-paginated (§22: "large/growing collection -> explicit cursor-paginated
query"): the cursor is the last row's `(created_at, id)`, so a source imported while someone is
paging cannot shift or repeat a page, which an offset would. It reads the
`(state, created_at DESC, id DESC)` index (§21).

Whether a source's original is missing is *derived from its artifact*, not stored on the source
(CONTEXT open question 24, decided 2026-10-01: `Source.UNAVAILABLE` stays unassigned, and API
Contracts §57 says a missing original "is handled by availability state rather than corrupting
Source history"). Each library entry therefore carries the original artifact's state, read in the
same query (a join, not one lookup per source, per API Contracts §101).

`set_current_run` enforces the one cross-row rule SQLite cannot express for it (§20): a source
points only to a completed accepted run *of that same source*. The rule is part of the `UPDATE`, so
a run that stops being valid in another session is seen, and no read precedes the write.

The acceptance transaction sets the pointer *before* it marks the run `COMPLETED` (§30: "set
`Source.current_processing_run_id`; then mark Run and Job `COMPLETED`"), so the guard accepts a run
that is being accepted (`FINALIZING`) as well as one that already is (`COMPLETED`). That leaves one
thing to the caller: in the same transaction it must mark the run `COMPLETED`, so that at commit the
pointer names a completed run. The repository cannot see the commit; the acceptance use case's test
must.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import and_, exists, or_, select
from sqlalchemy.orm import Session

from backend.app.processing.models import ProcessingRun, ProcessingRunState
from backend.app.sources.models import Artifact, Source
from backend.infrastructure.db.optimistic import optimistic_locked_update

# A run the pointer may name: one being accepted, or already accepted (§30).
_ACCEPTABLE_RUN_STATES = (ProcessingRunState.FINALIZING, ProcessingRunState.COMPLETED)


@dataclass(frozen=True)
class LibraryCursor:
    """Where the next page starts: after the row with this `created_at` and `id`."""

    created_at: datetime
    id: uuid.UUID


@dataclass(frozen=True)
class LibraryEntry:
    source: Source
    # The state of the source's original artifact (`AVAILABLE`, `MISSING`, ...): how "the original
    # is missing" is known, rather than a state of the source itself.
    original_state: str


@dataclass(frozen=True)
class LibraryPage:
    entries: list[LibraryEntry]
    # None when this was the last page.
    next_cursor: LibraryCursor | None


class SourceRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, source: Source) -> Source:
        """Stage a new source and flush, so its constraints are checked now."""
        self._session.add(source)
        self._session.flush()
        return source

    def get(self, source_id: uuid.UUID) -> Source | None:
        """The row as the database has it now, not as this session last saw it."""
        return self._session.get(Source, source_id, populate_existing=True)

    def library_page(
        self, *, state: str, limit: int, after: LibraryCursor | None = None
    ) -> LibraryPage:
        """Up to `limit` sources in `state`, newest first (ties by id, descending), starting after
        the cursor, each with its original artifact's state. `limit` must be at least 1."""
        if limit < 1:
            raise ValueError("a page holds at least one source")
        query = (
            select(Source, Artifact.state)
            .join(Artifact, Artifact.id == Source.original_artifact_id)
            .where(Source.state == state)
        )
        if after is not None:
            query = query.where(
                or_(
                    Source.created_at < after.created_at,
                    and_(Source.created_at == after.created_at, Source.id < after.id),
                )
            )
        rows = self._session.execute(
            query.order_by(Source.created_at.desc(), Source.id.desc())
            .limit(limit + 1)  # one more than asked: whether there is a next page
            .execution_options(populate_existing=True)
        ).all()
        entries = [LibraryEntry(source, original_state) for source, original_state in rows]
        page, more = entries[:limit], len(entries) > limit
        last = page[-1].source if more else None
        return LibraryPage(page, LibraryCursor(last.created_at, last.id) if last else None)

    def set_current_run(
        self, source_id: uuid.UUID, run_id: uuid.UUID, *, expected_revision: int, now: datetime
    ) -> bool:
        """Point the source at its accepted result. False, changing nothing, unless the source is at
        `expected_revision` and the run belongs to this same source and is `FINALIZING` (being
        accepted: the caller marks it `COMPLETED` in the same transaction) or already `COMPLETED`
        (§12, §30). On success the revision is bumped. A held `Source` object is stale afterwards:
        re-read it with `get`."""
        updated = optimistic_locked_update(
            self._session,
            Source,
            source_id,
            expected_revision=expected_revision,
            values={"current_processing_run_id": run_id, "updated_at": now},
            extra_where=[
                exists().where(
                    ProcessingRun.id == run_id,
                    ProcessingRun.source_id == source_id,
                    ProcessingRun.state.in_(_ACCEPTABLE_RUN_STATES),
                )
            ],
        )
        return bool(updated)
