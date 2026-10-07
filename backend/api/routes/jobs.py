"""Jobs: the schedulable work behind a processing run (API section 13; M4 W3.4).

A job is read as its own resource (`/jobs`, `/jobs/{id}`) and cancelled through the run it belongs
to: the run is the logical history, the job its schedulable execution, and there is one rule for
cancelling them (`CancelProcessingUseCase`). A job with no run has nothing to cancel here.
"""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from backend.api.dependencies import Library, get_backend
from backend.api.errors import ApiError
from backend.api.pagination import Page, PageQuery, decode_cursor, invalid_cursor, paginate
from backend.api.routes.processing import (
    JobBrief,
    ProcessingRunDetail,
    cancel_command,
    job_brief,
)
from backend.api.startup import Backend
from backend.app.jobs.models import Job, JobState, JobType

router = APIRouter(tags=["jobs"])


class JobDetail(JobBrief):
    type: str
    processing_run_id: str | None
    previous_job_id: str | None
    failure_code: str | None
    created_at: datetime
    started_at: datetime | None
    ended_at: datetime | None


def job_not_found(job_id: uuid.UUID) -> ApiError:
    return ApiError(
        404, "JOB_NOT_FOUND", "The requested job could not be found.",
        details={"job_id": str(job_id)},
    )  # fmt: skip


def _detail(job: Job) -> JobDetail:
    return JobDetail(
        **job_brief(job).model_dump(),
        type=job.type,
        processing_run_id=None if job.processing_run_id is None else str(job.processing_run_id),
        previous_job_id=None if job.previous_job_id is None else str(job.previous_job_id),
        failure_code=job.failure_code,
        created_at=job.created_at,
        started_at=job.started_at,
        ended_at=job.ended_at,
    )


@router.get("/jobs")
def list_jobs(
    library: Library,
    page: PageQuery,
    state: Annotated[JobState | None, Query()] = None,
    type: Annotated[JobType | None, Query()] = None,  # noqa: A002 - the API's filter name
) -> Page[JobDetail]:
    context = f"jobs:{state}:{type}"
    after: tuple[datetime, uuid.UUID] | None = None
    if page.cursor is not None:
        key = decode_cursor(page.cursor, context)
        try:
            after = (datetime.fromisoformat(key[0]), uuid.UUID(key[1]))
        except (IndexError, TypeError, ValueError):
            raise invalid_cursor() from None

    def read(session: Session) -> Page[JobDetail]:
        query = select(Job)
        if state is not None:
            query = query.where(Job.state == state)
        if type is not None:
            query = query.where(Job.type == type)
        if after is not None:
            query = query.where(
                or_(Job.created_at < after[0], and_(Job.created_at == after[0], Job.id < after[1]))
            )
        jobs = list(
            session.scalars(
                query.order_by(Job.created_at.desc(), Job.id.desc())
                .limit(page.limit + 1)
                .execution_options(populate_existing=True)
            )
        )
        return paginate(
            jobs,
            page.limit,
            context=context,
            key=lambda job: [job.created_at.isoformat(), str(job.id)],
            item=_detail,
        )

    return library.unit_of_work.read(read)


def _get(session: Session, job_id: uuid.UUID) -> Job:
    job = session.get(Job, job_id, populate_existing=True)
    if job is None:
        raise job_not_found(job_id)
    return job


@router.get("/jobs/{job_id}")
def get_job(job_id: uuid.UUID, library: Library) -> JobDetail:
    return library.unit_of_work.read(lambda session: _detail(_get(session, job_id)))


@router.post("/jobs/{job_id}/cancel", status_code=202)
def cancel_job(
    job_id: uuid.UUID, library: Library, backend: Annotated[Backend, Depends(get_backend)]
) -> ProcessingRunDetail:
    run_id = library.unit_of_work.read(lambda session: _get(session, job_id).processing_run_id)
    if run_id is None:
        raise ApiError(
            409, "JOB_NOT_CANCELLABLE", "The job has no processing run to cancel.",
            details={"job_id": str(job_id)},
        )  # fmt: skip
    return cancel_command(library, backend, run_id)
