"""JobRepository contract against real SQLite (M2: TST-022; PERSISTENCE_IMPLEMENTATION.md §12, §26).

What a repository must guarantee, proved with separate sessions and threads rather than assumed:
it joins the caller's transaction and never commits, claiming picks by priority then age and can
never hand one job to two workers, and every other change is decided by the database.
"""

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, sessionmaker

from backend.app.jobs.models import Job
from backend.app.jobs.repository import ClaimedJob, JobRepository
from backend.infrastructure.db.engine import create_session_factory
from tests.factories.models import ModelFactory
from tests.fixtures.concurrency import rendezvous_before_write

LEASE = timedelta(minutes=5)


@pytest.fixture
def factory(sqlite_engine: Engine) -> sessionmaker[Session]:
    return create_session_factory(sqlite_engine)


def state_of(factory: sessionmaker[Session], job_id: uuid.UUID) -> str:
    with factory() as session:
        return session.execute(select(Job.state).where(Job.id == job_id)).scalar_one()


def new_job(build: ModelFactory, **overrides: object) -> Job:
    fields: dict[str, object] = dict(
        id=build.new_id(), type="PROCESS_SOURCE", state="QUEUED", priority="NORMAL",
        payload_schema_version=1, progress_mode="DETERMINATE",
        created_at=build.clock(), updated_at=build.clock(),
    )  # fmt: skip
    return Job(**(fields | overrides))


# --- the caller owns the transaction ----------------------------------------------------------


def test_add_flushes_but_does_not_commit(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    with factory() as session:
        job = JobRepository(session).add(new_job(build))
        with factory() as other:  # not visible to another connection until the caller commits
            assert other.get(Job, job.id) is None
        session.rollback()
    with factory() as session:
        assert session.get(Job, job.id) is None


def test_add_checks_constraints_at_once(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    with factory() as session, pytest.raises(IntegrityError):
        JobRepository(session).add(new_job(build, type="NOT_A_TYPE"))


def test_a_claim_that_is_never_committed_leaves_the_job_queued(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    job = build.job()
    build.session.commit()
    with factory() as session:
        claimed = JobRepository(session).claim_next(
            owner="worker-1", now=build.clock(), lease_for=LEASE
        )
        assert claimed is not None
        session.rollback()

    assert state_of(factory, job.id) == "QUEUED"


def test_claim_with_an_empty_type_filter_claims_nothing(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    job = build.job()
    build.session.commit()

    with factory() as session:
        assert (
            JobRepository(session).claim_next(
                owner="worker-1", now=build.clock(), lease_for=LEASE, types=()
            )
            is None
        )
        session.commit()

    assert state_of(factory, job.id) == "QUEUED"


def test_get_returns_the_row_as_the_database_has_it_now(
    sqlite_engine: Engine, factory: sessionmaker[Session], build: ModelFactory
) -> None:
    job = build.job()
    build.session.commit()
    with Session(sqlite_engine, expire_on_commit=False) as session:  # keeps what it has loaded
        repository = JobRepository(session)
        cached = repository.get(job.id)  # held, so the session's identity map keeps it
        assert cached is not None
        assert cached.state == "QUEUED"
        session.commit()
        with factory() as other:
            JobRepository(other).transition(job.id, {"QUEUED"}, "CANCELLED", now=build.clock())
            other.commit()

        refreshed = repository.get(job.id)

        assert refreshed is not None
        assert refreshed.state == "CANCELLED"
        assert repository.get(build.new_id()) is None


# --- claiming ---------------------------------------------------------------------------------


def test_claim_picks_by_priority_then_age(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    older = build.clock()
    newer = older + timedelta(seconds=1)
    low = build.job(priority="LOW", created_at=older)
    normal_new = build.job(priority="NORMAL", created_at=newer)
    normal_old = build.job(priority="NORMAL", created_at=older)
    interactive = build.job(priority="INTERACTIVE", created_at=newer)
    build.session.commit()
    expected = [interactive.id, normal_old.id, normal_new.id, low.id]

    with factory() as session:
        repository = JobRepository(session)
        order = []
        for _ in expected:
            claimed = repository.claim_next(owner="w", now=build.clock(), lease_for=LEASE)
            assert claimed is not None
            order.append(claimed.id)
        session.commit()

    assert order == expected


def test_claim_follows_the_integer_rank_not_the_alphabetical_order_of_the_string(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    """Alphabetically it would be HIGH, INTERACTIVE, LOW, MAINTENANCE, NORMAL."""
    created = build.clock()
    jobs = {
        name: build.job(priority=name, created_at=created)
        for name in ("NORMAL", "MAINTENANCE", "HIGH", "LOW", "INTERACTIVE")
    }
    build.session.commit()

    with factory() as session:
        repository = JobRepository(session)
        order = []
        for _ in jobs:
            claimed = repository.claim_next(owner="w", now=build.clock(), lease_for=LEASE)
            assert claimed is not None
            order.append(claimed.id)
        session.commit()

    assert order == [
        jobs[name].id for name in ("INTERACTIVE", "HIGH", "NORMAL", "LOW", "MAINTENANCE")
    ]


def test_claim_breaks_a_tie_on_id(factory: sessionmaker[Session], build: ModelFactory) -> None:
    ids = sorted(build.new_id() for _ in range(3))
    # Inserted in the reverse of id order, so insertion order cannot be what decides.
    jobs = [build.job(id=job_id, created_at=build.clock()) for job_id in reversed(ids)]
    build.session.commit()

    with factory() as session:
        repository = JobRepository(session)
        order = []
        for _ in jobs:
            claimed = repository.claim_next(owner="w", now=build.clock(), lease_for=LEASE)
            assert claimed is not None
            order.append(claimed.id)

    assert order == sorted(job.id for job in jobs)


def test_claim_records_the_lease_and_returns_what_a_worker_needs(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    now = build.clock()
    job = build.job(payload_json={"source": "x"}, attempt_number=2)
    build.session.commit()

    with factory() as session:
        claimed = JobRepository(session).claim_next(owner="worker-1", now=now, lease_for=LEASE)
        session.commit()

    assert claimed == ClaimedJob(
        id=job.id, type="PROCESS_SOURCE", processing_run_id=None, payload_schema_version=1,
        payload_json={"source": "x"}, attempt_number=2, lease_owner="worker-1",
        lease_expires_at=now + LEASE,
    )  # fmt: skip
    with factory() as session:
        row = session.get(Job, job.id)
        assert row is not None
        assert (row.state, row.lease_owner, row.heartbeat_at, row.started_at) == (
            "RUNNING", "worker-1", now, now,
        )  # fmt: skip
        assert row.lease_expires_at == now + LEASE


def test_a_caller_that_already_read_is_exposed_to_a_stale_snapshot(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    """The guarantee has a limit, stated in the module: the repository joins the caller's
    transaction. One that read first, then loses a race to another writer, gets SQLite's
    `SQLITE_BUSY_SNAPSHOT` at once. Closing that is the unit of work's job (CONTEXT Q20)."""
    build.job()
    build.session.commit()
    with factory() as session:
        session.execute(select(Job.id)).all()  # a read: the transaction now holds a snapshot
        with factory() as other:
            claimed = JobRepository(other).claim_next(owner="a", now=build.clock(), lease_for=LEASE)
            assert claimed is not None
            other.commit()

        with pytest.raises(OperationalError):
            JobRepository(session).claim_next(owner="b", now=build.clock(), lease_for=LEASE)


def test_claim_takes_only_queued_jobs(factory: sessionmaker[Session], build: ModelFactory) -> None:
    for state in (
        "RUNNING", "PAUSING", "PAUSED", "CANCELLING", "CANCELLED", "COMPLETED", "FAILED",
        "INTERRUPTED",
    ):  # fmt: skip
        build.job(state=state)
    build.session.commit()

    with factory() as session:
        claimed = JobRepository(session).claim_next(owner="w", now=build.clock(), lease_for=LEASE)
        assert claimed is None


def test_a_stale_cached_job_cannot_be_claimed_twice(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    job = build.job()
    build.session.commit()
    with factory() as session:
        cached = session.get(Job, job.id)  # this session believes the job is QUEUED
        assert cached is not None
        assert cached.state == "QUEUED"
        session.commit()
        with factory() as other:
            first = JobRepository(other).claim_next(owner="a", now=build.clock(), lease_for=LEASE)
            assert first is not None
            other.commit()

        second = JobRepository(session).claim_next(owner="b", now=build.clock(), lease_for=LEASE)

        assert second is None


def test_concurrent_workers_never_share_a_job(
    sqlite_engine: Engine, factory: sessionmaker[Session], build: ModelFactory
) -> None:
    total = 24
    ids = {build.job().id for _ in range(total)}
    build.session.commit()
    now = build.clock()

    def worker(name: str) -> list[uuid.UUID]:
        mine: list[uuid.UUID] = []
        while True:
            with factory() as session:
                claimed = JobRepository(session).claim_next(owner=name, now=now, lease_for=LEASE)
                session.commit()
            if claimed is None:
                return mine
            mine.append(claimed.id)

    # Every worker is held at its first claim until all four have arrived, so a claim that reads
    # before it writes has all of them read the same job first.
    with (
        rendezvous_before_write(sqlite_engine, "UPDATE jobs", parties=4),
        ThreadPoolExecutor(max_workers=4) as pool,
    ):
        results = list(pool.map(worker, [f"w{n}" for n in range(4)]))

    claimed_ids = [job_id for mine in results for job_id in mine]
    assert len(claimed_ids) == total  # none twice
    assert set(claimed_ids) == ids  # none lost


# --- transitions ------------------------------------------------------------------------------


def test_transition_requires_one_of_the_named_states(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    job = build.job(state="RUNNING", lease_owner="w", lease_expires_at=build.clock())
    build.session.commit()

    with factory() as session:
        repository = JobRepository(session)
        wrong = repository.transition(job.id, {"QUEUED", "PAUSED"}, "CANCELLED", now=build.clock())
        right = repository.transition(job.id, {"RUNNING"}, "PAUSING", now=build.clock())
        session.commit()

    assert (wrong, right) == (False, True)
    assert state_of(factory, job.id) == "PAUSING"


def test_a_job_becomes_running_only_by_being_claimed(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    job = build.job()
    build.session.commit()

    with factory() as session, pytest.raises(ValueError, match="claim_next"):
        JobRepository(session).transition(job.id, {"QUEUED"}, "RUNNING", now=build.clock())

    assert state_of(factory, job.id) == "QUEUED"


@pytest.mark.parametrize(
    ("to_state", "keeps_lease", "ends"),
    [
        ("PAUSING", True, False),
        ("CANCELLING", True, False),
        ("PAUSED", False, False),
        ("INTERRUPTED", False, False),
        ("COMPLETED", False, True),
        ("FAILED", False, True),
        ("CANCELLED", False, True),
    ],
)
def test_each_target_state_keeps_or_clears_the_lease_and_ends_the_job_or_not(
    factory: sessionmaker[Session], build: ModelFactory, to_state: str, keeps_lease: bool,
    ends: bool,
) -> None:  # fmt: skip
    now = build.clock()
    job = build.job(state="RUNNING", lease_owner="w", lease_expires_at=now, heartbeat_at=now)
    build.session.commit()

    with factory() as session:
        assert JobRepository(session).transition(job.id, {"RUNNING"}, to_state, now=now)
        session.commit()

    with factory() as session:
        row = session.get(Job, job.id)
        assert row is not None
        held = (row.lease_owner, row.lease_expires_at, row.heartbeat_at)
        assert held == (("w", now, now) if keeps_lease else (None, None, None))
        assert row.ended_at == (now if ends else None)


def test_a_failure_is_recorded_with_its_code_and_detail(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    job = build.job(state="RUNNING")
    build.session.commit()

    with factory() as session:
        JobRepository(session).transition(
            job.id, {"RUNNING"}, "FAILED", now=build.clock(), failure_code="BOOM",
            failure_detail="it broke",
        )  # fmt: skip
        session.commit()

    with factory() as session:
        row = session.get(Job, job.id)
        assert row is not None
        assert (row.failure_code, row.failure_detail) == ("BOOM", "it broke")


def test_progress_is_recorded_until_the_job_is_over_and_the_schema_guards_it(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    running = build.job(state="RUNNING")
    done = build.job(state="COMPLETED")
    build.session.commit()

    with factory() as session:
        repository = JobRepository(session)
        assert repository.set_progress(running.id, completed=3, total=10, now=build.clock())
        assert not repository.set_progress(done.id, completed=1, total=2, now=build.clock())
        assert not repository.set_progress(build.new_id(), completed=1, total=2, now=build.clock())
        session.commit()
        with pytest.raises(IntegrityError):
            repository.set_progress(running.id, completed=11, total=10, now=build.clock())
        session.rollback()

    with factory() as session:
        row = session.get(Job, running.id)
        assert row is not None
        assert (row.progress_completed, row.progress_total) == (3, 10)


def test_transient_lists_every_job_that_is_not_over_oldest_first(
    factory: sessionmaker[Session], build: ModelFactory
) -> None:
    t0 = build.clock()
    queued = build.job(state="QUEUED", created_at=t0 + timedelta(seconds=2))
    interrupted = build.job(state="INTERRUPTED", created_at=t0)
    paused = build.job(state="PAUSED", created_at=t0 + timedelta(seconds=1))
    for state in ("COMPLETED", "FAILED", "CANCELLED"):
        build.job(state=state)
    build.session.commit()

    with factory() as session:
        listed = JobRepository(session).transient()

    assert [job.id for job in listed] == [interrupted.id, paused.id, queued.id]
