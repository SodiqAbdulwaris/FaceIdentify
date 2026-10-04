"""JobRepository: the persistence mechanics of `jobs` (PERSISTENCE_IMPLEMENTATION.md §26).

Narrow and explicit: add/get, atomic claim, progress and state transitions, the transient list. It
participates in the caller's transaction and never commits (API and Contracts §103); the use case
or scheduler that owns the unit of work commits. Every change is a guarded `UPDATE` evaluated by
the database, never a decision made on a cached object, so two writers cannot both win.

Claiming (§15): "choose an eligible queued row by priority and creation time, conditionally
transition it to RUNNING, record a lease/heartbeat". It is one `UPDATE ... RETURNING` whose row is
chosen by a subquery, so the choice and the transition cannot be separated by another writer, and
a transaction that has not read first starts with a write, so it has no stale read snapshot to
fail on. A caller that has already read in the same transaction is exposed: if another writer
commits a claim meanwhile, SQLite raises `OperationalError` (`SQLITE_BUSY_SNAPSHOT`) rather than
wait. Closing that is the unit of work's job (`BEGIN IMMEDIATE` and a whole-transaction retry,
CONTEXT open question 20), not something a repository can do inside a transaction it does not own.
The spec's "commit" belongs
to the caller, by the rule above: a claim that is never committed is rolled back with its
transaction and the job is still `QUEUED`.
"""

import uuid
from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import case, select, update
from sqlalchemy.orm import Session

from backend.app.jobs.models import Job, JobPriority, JobState

# A job in one of these states is over: nothing will resume it.
FINISHED_JOB_STATES = (JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED)

# States in which a worker holds the job and so a lease means something. A job in any other state
# has no lease.
LEASED_JOB_STATES = (JobState.RUNNING, JobState.PAUSING, JobState.CANCELLING)

# Most urgent first: the order of `JobPriority`.
_PRIORITY_RANK = case(
    {priority.value: rank for rank, priority in enumerate(JobPriority)}, value=Job.priority
)


@dataclass(frozen=True)
class ClaimedJob:
    """What a worker needs to run a job it has claimed; a value, not a live row."""

    id: uuid.UUID
    type: str
    processing_run_id: uuid.UUID | None
    payload_schema_version: int
    payload_json: dict[str, Any] | None
    attempt_number: int
    lease_owner: str
    lease_expires_at: datetime


class JobRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, job: Job) -> Job:
        """Stage a new job and flush, so its id and constraints are checked now."""
        self._session.add(job)
        self._session.flush()
        return job

    def get(self, job_id: uuid.UUID) -> Job | None:
        """The row as the database has it now, not as this session last saw it."""
        return self._session.get(Job, job_id, populate_existing=True)

    def claim_next(
        self,
        *,
        owner: str,
        now: datetime,
        lease_for: timedelta,
        types: Collection[str] | None = None,
    ) -> ClaimedJob | None:
        """Claim the most urgent, oldest `QUEUED` job for `owner`, or None if there is none.

        Ties on priority and creation time break by id, so the order is total. The job becomes
        `RUNNING` with a lease until `now + lease_for`, a first heartbeat and `started_at`.
        """
        expires = now + lease_for
        eligible = [Job.state == JobState.QUEUED]
        if types is not None:
            if not types:
                return None
            eligible.append(Job.type.in_(types))
        chosen = (
            select(Job.id)
            .where(*eligible)
            .order_by(_PRIORITY_RANK, Job.created_at, Job.id)
            .limit(1)
            .scalar_subquery()
        )
        row = self._session.execute(
            update(Job)
            .where(Job.id == chosen)
            .values(
                state=JobState.RUNNING,
                lease_owner=owner,
                lease_expires_at=expires,
                heartbeat_at=now,
                started_at=now,
                updated_at=now,
            )
            .returning(
                Job.id,
                Job.type,
                Job.processing_run_id,
                Job.payload_schema_version,
                Job.payload_json,
                Job.attempt_number,
            )
            .execution_options(synchronize_session=False)
        ).one_or_none()
        if row is None:
            return None
        job_id, job_type, run_id, schema_version, payload, attempt = row
        return ClaimedJob(
            job_id, job_type, run_id, schema_version, payload, attempt, owner, expires
        )

    def transition(
        self,
        job_id: uuid.UUID,
        from_states: Collection[str],
        to_state: str,
        *,
        now: datetime,
        failure_code: str | None = None,
        failure_detail: str | None = None,
    ) -> bool:
        """Move a job from one of `from_states` to `to_state`; False if it was in none of them.

        Whether the move is allowed is the caller's decision (it names the states), except that
        `RUNNING` is entered only by `claim_next`, which records the lease a running job must have
        (`ValueError` otherwise). Leaving the states a worker holds clears the lease; entering a
        finished state records `ended_at`.
        `failure_code` and `failure_detail`, when given, are recorded.
        """
        if to_state == JobState.RUNNING:
            raise ValueError("a job becomes RUNNING by being claimed: use claim_next")
        values: dict[str, Any] = {"state": to_state, "updated_at": now}
        if to_state not in LEASED_JOB_STATES:
            values |= {"lease_owner": None, "lease_expires_at": None, "heartbeat_at": None}
        if to_state in FINISHED_JOB_STATES:
            values["ended_at"] = now
        if failure_code is not None:
            values["failure_code"] = failure_code
        if failure_detail is not None:
            values["failure_detail"] = failure_detail
        result = self._session.execute(
            update(Job)
            .where(Job.id == job_id, Job.state.in_(from_states))
            .values(**values)
            .execution_options(synchronize_session=False)
        )
        return bool(result.rowcount)  # type: ignore[attr-defined]

    def set_progress(
        self, job_id: uuid.UUID, *, completed: int, total: int | None, now: datetime
    ) -> bool:
        """Record progress on a job that is not over; False if it is over or does not exist. The
        schema refuses a negative value or `completed > total` (`IntegrityError`)."""
        result = self._session.execute(
            update(Job)
            .where(Job.id == job_id, Job.state.not_in(FINISHED_JOB_STATES))
            .values(progress_completed=completed, progress_total=total, updated_at=now)
            .execution_options(synchronize_session=False)
        )
        return bool(result.rowcount)  # type: ignore[attr-defined]

    def transient(self) -> list[Job]:
        """Every job that is not over, oldest first: what a restart may have to deal with."""
        return list(
            self._session.scalars(
                select(Job)
                .where(Job.state.not_in(FINISHED_JOB_STATES))
                .order_by(Job.created_at, Job.id)
                .execution_options(populate_existing=True)
            )
        )
