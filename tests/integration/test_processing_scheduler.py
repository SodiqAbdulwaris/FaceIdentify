"""M3's short claim/start transaction for source-processing jobs."""

from datetime import timedelta

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from backend.app.jobs.models import JobState
from backend.app.processing.models import ExecutionSegment, ProcessingRun, ProcessingRunState
from backend.app.processing.scheduler import ProcessingScheduler
from backend.infrastructure.db.unit_of_work import TransactionRetry, UnitOfWork
from tests.factories.models import ModelFactory

LEASE = timedelta(seconds=30)


def scheduler(engine: Engine, build: ModelFactory) -> ProcessingScheduler:
    return ProcessingScheduler(
        UnitOfWork(engine, retry=TransactionRetry(1, lambda _: 0), sleep=lambda _: None),
        new_id=build.new_id,
        clock=build.clock,
        lease_for=LEASE,
    )


def test_claim_source_job_starts_run_and_one_lifecycle_segment(
    sqlite_engine: Engine, build: ModelFactory
) -> None:
    run = build.run(state=ProcessingRunState.PENDING)
    job = build.job(processing_run_id=run.id)
    build.session.commit()

    started = scheduler(sqlite_engine, build).claim_source_job("scheduler-1")

    assert started is not None
    assert started.job.id == job.id
    with Session(sqlite_engine) as session:
        persisted_job = session.get(type(job), job.id)
        persisted_run = session.get(ProcessingRun, run.id)
        segment = session.get(ExecutionSegment, started.execution_segment_id)
        assert persisted_job is not None
        assert (persisted_job.state, persisted_job.lease_owner) == (JobState.RUNNING, "scheduler-1")
        assert persisted_run is not None
        assert persisted_run.state == ProcessingRunState.RUNNING
        assert segment is not None
        assert (segment.processing_run_id, segment.ordinal, segment.state) == (
            run.id,
            0,
            "RUNNING",
        )
        assert segment.runtime_variant_id is None


def test_claim_source_job_skips_other_job_types(sqlite_engine: Engine, build: ModelFactory) -> None:
    other = build.job(type="REBUILD_INDEX")
    build.session.commit()

    assert scheduler(sqlite_engine, build).claim_source_job("scheduler-1") is None
    with Session(sqlite_engine) as session:
        persisted = session.get(type(other), other.id)
        assert persisted is not None
        assert persisted.state == JobState.QUEUED


def test_job_without_a_processing_run_fails_without_a_segment(
    sqlite_engine: Engine, build: ModelFactory
) -> None:
    job = build.job(processing_run_id=None)
    build.session.commit()

    assert scheduler(sqlite_engine, build).claim_source_job("scheduler-1") is None
    with Session(sqlite_engine) as session:
        persisted = session.get(type(job), job.id)
        assert persisted is not None
        assert persisted.state == JobState.FAILED
        assert session.query(ExecutionSegment).count() == 0


@pytest.mark.parametrize("run_state", ["RUNNING", "COMPLETED"])
def test_stale_job_fails_without_a_segment(
    sqlite_engine: Engine, build: ModelFactory, run_state: str
) -> None:
    run = build.run(state=run_state)
    job = build.job(processing_run_id=run.id)
    build.session.commit()

    assert scheduler(sqlite_engine, build).claim_source_job("scheduler-1") is None
    with Session(sqlite_engine) as session:
        persisted = session.get(type(job), job.id)
        assert persisted is not None
        assert persisted.state == JobState.FAILED
        assert session.query(ExecutionSegment).count() == 0


def test_blank_scheduler_owner_is_refused(sqlite_engine: Engine, build: ModelFactory) -> None:
    with pytest.raises(ValueError, match="must not be blank"):
        scheduler(sqlite_engine, build).claim_source_job("")
