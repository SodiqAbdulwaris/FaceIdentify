"""Processing: request processing of a source, read processing runs, retry one (API sections 5.3
and 6; M4 W3.3).

* `POST /sources/{id}/process` is asynchronous: it commits a snapshot, a run and a queued job
  atomically, wakes the scheduler, and answers `202` with the run (and its job) to track. The
  request it runs under comes from the host's development policy profile
  (`ProcessingSettings.request_for`), never from the client. A source that already has a result
  is `409 SOURCE_ALREADY_PROCESSED`: it is reprocessed instead.
* `POST /sources/{id}/reprocess` (API 5.4, persistence 12.1) does the same for a source that has a
  result: the new run names the generation it will replace (`supersedes_run_id`), and until it is
  accepted the current result stays what every view shows. `409 SOURCE_STATE_CONFLICT` when the
  source has no result or cannot be processed, `409 SOURCE_BUSY` while a run of it is in flight.
* A run is read with its job: the job is what is scheduled, the run is the logical history.
  `failure_code` is shown; failure detail text stays in the database.
* `POST /processing-runs/{id}/cancel` cancels a queued run at once and asks a running one to stop
  (`CancelProcessingUseCase`); a repeat is harmless; a run being made authoritative or already over
  is refused.
* `POST /processing-runs/{id}/retry` queues a new attempt for a failed, interrupted or
  not-resumable run (a new job and run, linked; the old attempt is left as it ended).
"""

import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import Select, exists, select
from sqlalchemy.orm import Session, aliased

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
from backend.api.routes.memory import person_references
from backend.api.routes.sources import gone_sources, recheck_if_missing, require_visible_source
from backend.api.startup import Backend, ProcessingSettings, ProcessingUnavailableError
from backend.app.identities.models import Evidence, EvidenceKind, Identity, IdentityState
from backend.app.jobs.models import SOURCE_JOB_TYPES, Job, JobPriority
from backend.app.processing.cancel import (
    CancelError,
    CancelOutcome,
    CancelProcessingUseCase,
    RunNotFoundError,
)
from backend.app.processing.configuration import UNCALIBRATED
from backend.app.processing.models import (
    ProcessingConfigurationSnapshot,
    ProcessingRun,
    ProcessingRunState,
)
from backend.app.processing.process_source import (
    ProcessSourceError,
    ProcessSourceUseCase,
    ScheduledProcessing,
    SourceAlreadyProcessedError,
    SourceBusyError,
)
from backend.app.processing.retry import RetryProcessingUseCase
from backend.app.recognition.reasoner import MAX_SIMILARITY

router = APIRouter(tags=["processing"])


class Progress(BaseModel):
    completed: int
    total: int | None


class JobBrief(BaseModel):
    id: str
    state: str
    priority: str
    attempt_number: int
    progress: Progress | None


class PolicyProvenance(BaseModel):
    """What the run's frozen configuration says about its decision policy, so a screen can tell
    the user when results come from an uncalibrated, non-release policy (plan decision 1)."""

    calibration_mode: str
    decision_policy_version: str | None
    calibrated: bool
    # False when the frozen policy cannot match a face to an existing identity (threshold above 1).
    automatic_matching: bool


class ReprocessReview(BaseModel):
    """A human decision that reprocessing could not carry over (identity model 60.1): the identity
    it was about, who that is if named, and why (`NO_CORRESPONDENCE`, `AMBIGUOUS`,
    `SPACE_CHANGED`, `MISSING_VECTOR`)."""

    id: str
    identity_id: str
    person: str | None
    reason: str
    processing_run_id: str
    created_at: datetime


class ReprocessReviews(BaseModel):
    items: list[ReprocessReview]


class ProcessingRunDetail(BaseModel):
    id: str
    source_id: str
    state: str
    parent_run_id: str | None  # retry lineage
    supersedes_run_id: str | None  # reprocessing: the generation this run replaces once accepted
    requested_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    failed_at: datetime | None
    failure_code: str | None
    policy: PolicyProvenance
    job: JobBrief | None


def processing_settings(backend: Annotated[Backend, Depends(get_backend)]) -> ProcessingSettings:
    if backend.processing is None:
        raise ApiError(503, "PROCESSING_UNAVAILABLE", "Processing is not configured.")
    return backend.processing


def run_not_found(run_id: uuid.UUID) -> ApiError:
    return ApiError(
        404, "RUN_NOT_FOUND", "The requested processing run could not be found.",
        details={"run_id": str(run_id)},
    )  # fmt: skip


# --- shaping --------------------------------------------------------------------------------


def job_brief(job: Job) -> JobBrief:
    progress = (
        None
        if job.progress_completed is None
        else Progress(completed=job.progress_completed, total=job.progress_total)
    )
    return JobBrief(
        id=str(job.id),
        state=job.state,
        priority=job.priority,
        attempt_number=job.attempt_number,
        progress=progress,
    )


def _policy(frozen: dict[str, Any]) -> PolicyProvenance:
    mode = frozen["calibration"]["mode"]
    return PolicyProvenance(
        calibration_mode=mode,
        decision_policy_version=frozen["decision_policy"].get("version"),
        calibrated=mode != UNCALIBRATED,
        automatic_matching=frozen["decision_policy"]["match_threshold"] <= MAX_SIMILARITY,
    )


def _details(session: Session, runs: list[ProcessingRun]) -> list[ProcessingRunDetail]:
    """Each run with its source-processing job (a run has exactly one; a retry is a new run)."""
    jobs: dict[uuid.UUID, Job] = {}
    for job in session.scalars(
        select(Job).where(
            Job.processing_run_id.in_([run.id for run in runs]), Job.type.in_(SOURCE_JOB_TYPES)
        )
    ):
        assert job.processing_run_id is not None  # selected by it
        jobs[job.processing_run_id] = job
    snapshots = {
        s.id: s.canonical_json
        for s in session.scalars(
            select(ProcessingConfigurationSnapshot).where(
                ProcessingConfigurationSnapshot.id.in_(
                    [run.configuration_snapshot_id for run in runs]
                )
            )
        )
    }
    return [
        ProcessingRunDetail(
            id=str(run.id),
            source_id=str(run.source_id),
            state=run.state,
            parent_run_id=None if run.parent_run_id is None else str(run.parent_run_id),
            supersedes_run_id=None if run.supersedes_run_id is None else str(run.supersedes_run_id),
            requested_at=run.requested_at,
            started_at=run.started_at,
            completed_at=run.completed_at,
            failed_at=run.failed_at,
            failure_code=run.failure_code,
            policy=_policy(snapshots[run.configuration_snapshot_id]),
            job=None if run.id not in jobs else job_brief(jobs[run.id]),
        )
        for run in runs
    ]


def gone_runs() -> Select[tuple[uuid.UUID]]:
    """The ids of runs whose Source is being or was deleted: no route serves them."""
    return select(ProcessingRun.id).where(ProcessingRun.source_id.in_(gone_sources()))


def visible_run(session: Session, run_id: uuid.UUID) -> ProcessingRun:
    """The run, or `404 RUN_NOT_FOUND` if it is unknown or its Source is being or was deleted."""
    run = session.get(ProcessingRun, run_id, populate_existing=True)
    if run is None or session.scalar(
        select(gone_runs().where(ProcessingRun.id == run_id).exists())
    ):
        raise run_not_found(run_id)
    return run


def _run_detail(session: Session, run_id: uuid.UUID) -> ProcessingRunDetail:
    return _details(session, [visible_run(session, run_id)])[0]


def _require_source(session: Session, source_id: uuid.UUID) -> None:
    require_visible_source(session, source_id)


def _still_there(library: Library, check: Callable[[Session], object]) -> None:
    """A command was refused: if what it was about was deleted in the meantime (after the check
    that let it start), the honest answer is the same `404` as before, not the refusal."""
    library.unit_of_work.read(check)


# --- routes ---------------------------------------------------------------------------------


def _schedule(
    library: Library, backend: Backend, source_id: uuid.UUID, *, reprocess: bool
) -> ProcessingRunDetail:
    """Shared by `process` and `reprocess`: check the source, resolve the host's request, commit
    the run and its job, announce it, and show it."""
    library.unit_of_work.read(lambda session: _require_source(session, source_id))
    recheck_if_missing(library, backend, source_id)  # a missing original is verified on use (#179)
    settings = processing_settings(backend)  # (after the Source: a gone one is 404, not 503)
    try:
        request = library.unit_of_work.read(settings.request_for)
    except ProcessingUnavailableError:
        raise ApiError(
            503, "PROCESSING_UNAVAILABLE", "No processing configuration is available."
        ) from None
    use_case = ProcessSourceUseCase(
        library.unit_of_work,
        new_id=backend.settings.new_id,
        clock=backend.settings.clock,
        wake_scheduler=backend.wake_scheduler,
    )
    command = use_case.reprocess if reprocess else use_case.process
    try:
        scheduled: ScheduledProcessing = command(
            source_id,
            processing_request=request,
            priority=JobPriority.INTERACTIVE,
            created_by_user_action=None,
        )
    except ProcessSourceError as error:
        _still_there(library, lambda session: _require_source(session, source_id))
        details = {"reason": str(error)}
        if isinstance(error, SourceAlreadyProcessedError):
            raise ApiError(
                409, "SOURCE_ALREADY_PROCESSED",
                "The source already has a result; reprocess it instead.", details=details,
            ) from None  # fmt: skip
        if isinstance(error, SourceBusyError):
            raise ApiError(
                409, "SOURCE_BUSY", "The source is being processed; cancel that first.",
                details=details,
            ) from None  # fmt: skip
        if reprocess:
            raise ApiError(
                409, "SOURCE_STATE_CONFLICT", "The source cannot be reprocessed now.",
                details=details,
            ) from None  # fmt: skip
        raise ApiError(
            409, "SOURCE_NOT_PROCESSABLE", "The source cannot be processed now.", details=details
        ) from None
    backend.announce_run(scheduled.processing_run_id, "processing_run.created")
    return library.unit_of_work.read(
        lambda session: _run_detail(session, scheduled.processing_run_id)
    )


@router.post("/sources/{source_id}/process", status_code=202)
def process_source(
    source_id: uuid.UUID,
    library: Library,
    backend: Annotated[Backend, Depends(get_backend)],
) -> ProcessingRunDetail:
    return _schedule(library, backend, source_id, reprocess=False)


@router.get("/sources/{source_id}/reprocess-reviews")
def reprocess_reviews(source_id: uuid.UUID, library: Library) -> ReprocessReviews:
    """The source's open review items: `REPROCESS_REVIEW_REQUIRED` evidence (persistence 10)
    whose identity is still `ACTIVE` and has had no correction since, newest first."""

    def read(session: Session) -> ReprocessReviews:
        _require_source(session, source_id)
        later = aliased(Evidence)
        resolved = exists().where(
            later.kind == EvidenceKind.USER_CORRECTION,
            later.subject_identity_id == Evidence.subject_identity_id,
            later.created_at > Evidence.created_at,
        )
        rows = session.execute(
            select(Evidence, Identity)
            .join(Identity, Identity.id == Evidence.subject_identity_id)
            .where(
                Evidence.source_id == source_id,
                Evidence.kind == EvidenceKind.REPROCESS_REVIEW_REQUIRED,
                Identity.state == IdentityState.ACTIVE,
                ~resolved,
            )
            .order_by(Evidence.created_at.desc(), Evidence.id.desc())
        ).tuples().all()  # fmt: skip
        names = person_references(session, [identity.id for _evidence, identity in rows])
        return ReprocessReviews(
            items=[
                ReprocessReview(
                    id=str(evidence.id),
                    identity_id=str(identity.id),
                    person=None if identity.id not in names else names[identity.id].display_name,
                    reason=str(evidence.payload_json["reason"]),
                    processing_run_id=str(evidence.processing_run_id),
                    created_at=evidence.created_at,
                )
                for evidence, identity in rows
            ]
        )

    return library.unit_of_work.read(read)


@router.post("/sources/{source_id}/reprocess", status_code=202)
def reprocess_source(
    source_id: uuid.UUID,
    library: Library,
    backend: Annotated[Backend, Depends(get_backend)],
) -> ProcessingRunDetail:
    """Reprocess a source that has a result (API 5.4). The current result stays current until the
    new run is accepted; then the source emits `source.updated`."""
    return _schedule(library, backend, source_id, reprocess=True)


def _listing(
    library: Library,
    page: PageQuery,
    *,
    source_id: uuid.UUID | None,
    state: ProcessingRunState | None,
    of_a_visible_source: bool = False,
) -> Page[ProcessingRunDetail]:
    context = f"runs:{source_id}:{state}"
    after = created_cursor(page.cursor, context)

    def read(session: Session) -> Page[ProcessingRunDetail]:
        if of_a_visible_source and source_id is not None:
            _require_source(session, source_id)  # (same snapshot as the runs below)
        query = select(ProcessingRun).where(ProcessingRun.source_id.not_in(gone_sources()))
        if source_id is not None:
            query = query.where(ProcessingRun.source_id == source_id)
        if state is not None:
            query = query.where(ProcessingRun.state == state)
        if after is not None:
            query = query.where(older_than(ProcessingRun.created_at, ProcessingRun.id, after))
        runs = list(
            session.scalars(
                query.order_by(ProcessingRun.created_at.desc(), ProcessingRun.id.desc())
                .limit(page.limit + 1)
                .execution_options(populate_existing=True)
            )
        )
        details = {d.id: d for d in _details(session, runs)}
        return paginate(
            runs,
            page.limit,
            context=context,
            key=lambda run: created_key(run.created_at, run.id),
            item=lambda run: details[str(run.id)],
        )

    return library.unit_of_work.read(read)


@router.get("/processing-runs")
def list_runs(
    library: Library,
    page: PageQuery,
    source_id: Annotated[uuid.UUID | None, Query()] = None,
    state: Annotated[ProcessingRunState | None, Query()] = None,
) -> Page[ProcessingRunDetail]:
    return _listing(library, page, source_id=source_id, state=state)


@router.get("/sources/{source_id}/processing-runs")
def list_source_runs(
    source_id: uuid.UUID, library: Library, page: PageQuery
) -> Page[ProcessingRunDetail]:
    return _listing(library, page, source_id=source_id, state=None, of_a_visible_source=True)


@router.get("/processing-runs/{run_id}")
def get_run(run_id: uuid.UUID, library: Library) -> ProcessingRunDetail:
    return library.unit_of_work.read(lambda session: _run_detail(session, run_id))


def cancel_command(library: Library, backend: Backend, run_id: uuid.UUID) -> ProcessingRunDetail:
    """Shared by the run and job cancel routes: write the request, then show the run."""
    library.unit_of_work.read(lambda session: visible_run(session, run_id))
    try:
        result = CancelProcessingUseCase(library.unit_of_work, clock=backend.settings.clock).cancel(
            run_id
        )
    except RunNotFoundError:
        raise run_not_found(run_id) from None
    except CancelError as error:
        _still_there(library, lambda session: visible_run(session, run_id))
        raise ApiError(
            409, "RUN_NOT_CANCELLABLE", "The processing run cannot be cancelled now.",
            details={"reason": str(error)},
        ) from None  # fmt: skip
    if result.outcome != CancelOutcome.ALREADY:  # a repeat changed nothing: nothing to announce
        backend.announce_run(result.run_id)
    return library.unit_of_work.read(lambda session: _run_detail(session, result.run_id))


@router.post("/processing-runs/{run_id}/cancel", status_code=202)
def cancel_run(
    run_id: uuid.UUID, library: Library, backend: Annotated[Backend, Depends(get_backend)]
) -> ProcessingRunDetail:
    return cancel_command(library, backend, run_id)


@router.post("/processing-runs/{run_id}/retry", status_code=202)
def retry_run(
    run_id: uuid.UUID, library: Library, backend: Annotated[Backend, Depends(get_backend)]
) -> ProcessingRunDetail:
    def find_job(session: Session) -> tuple[uuid.UUID, uuid.UUID | None]:
        run = visible_run(session, run_id)
        return run.source_id, session.scalar(
            select(Job.id).where(Job.processing_run_id == run_id, Job.type.in_(SOURCE_JOB_TYPES))
        )

    source_id, job_id = library.unit_of_work.read(find_job)
    recheck_if_missing(library, backend, source_id)  # a missing original is verified on use (#179)
    try:
        if job_id is None:
            raise ProcessSourceError(f"run {run_id} has no processing job")
        scheduled = RetryProcessingUseCase(
            library.unit_of_work,
            new_id=backend.settings.new_id,
            clock=backend.settings.clock,
            wake_scheduler=backend.wake_scheduler,
        ).retry(job_id)
    except ProcessSourceError as error:
        _still_there(library, lambda session: visible_run(session, run_id))
        raise ApiError(
            409, "RUN_NOT_RETRYABLE", "The processing run cannot be retried.",
            details={"reason": str(error)},
        ) from None  # fmt: skip
    backend.announce_run(scheduled.processing_run_id, "processing_run.created")
    return library.unit_of_work.read(
        lambda session: _run_detail(session, scheduled.processing_run_id)
    )
