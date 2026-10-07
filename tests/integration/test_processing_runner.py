"""One queued job, end to end, through the runner a scheduler loop repeats (M4 W2.2; TST-060).

Perception is planted (no weights); everything else is the real library: the scheduler, the
executor, acceptance, the index coordinator. Each test names the outcome the runner reports and the
durable state it leaves.
"""

from typing import Any

import pytest
from sqlalchemy import select

from backend.app.identities.models import Evidence, Identity
from backend.app.jobs.models import Job
from backend.app.memory.models import IndexOperation, Observation, Occurrence, Representation
from backend.app.processing.accept_run import AcceptanceError, AcceptProcessingRunUseCase
from backend.app.processing.models import ProcessingRun
from backend.app.processing.runner import (
    REFUSED_FINAL_CODE,
    UNEXPECTED_CODE,
    RunOutcomeKind,
)
from backend.app.runtime.perception_client import PerceptionError
from backend.ml.contracts.protocol import MLErrorCode
from tests.fixtures.pipeline import Pipeline


def only[T](pipeline: Pipeline, model: type[T]) -> T:
    with pipeline.lib.session_factory() as session:
        return session.scalars(select(model)).one()


def states(pipeline: Pipeline, model: Any) -> list[str]:
    with pipeline.lib.session_factory() as session:
        return sorted(session.scalars(select(model.state)))


def test_with_nothing_queued_the_runner_is_idle(pipeline: Pipeline) -> None:
    outcome = pipeline.runner().run_once()

    assert outcome.kind is RunOutcomeKind.IDLE
    assert outcome.processing_run_id is None


def test_the_run_is_announced_once_its_job_is_claimed_and_a_failed_announcement_is_harmless(
    pipeline: Pipeline,
) -> None:
    seen: list[tuple[Any, str]] = []

    def started(run_id: Any) -> None:
        seen.append((run_id, only(pipeline, ProcessingRun).state))
        raise RuntimeError("the notification failed")

    pipeline.enqueue(pipeline.import_image())
    runner = pipeline.runner()
    runner._on_started = started

    outcome = runner.run_once()

    assert outcome.kind is RunOutcomeKind.ACCEPTED  # the failed notification changed nothing
    assert seen == [(outcome.processing_run_id, "RUNNING")]  # told after the claim, before the work


def test_a_queued_job_is_executed_accepted_and_indexed(pipeline: Pipeline) -> None:
    pipeline.enqueue(pipeline.import_image())

    outcome = pipeline.runner(wake_index=pipeline.apply_index).run_once()

    assert outcome.kind is RunOutcomeKind.ACCEPTED
    assert outcome.error is None and outcome.wake_error is None  # noqa: PT018
    assert states(pipeline, ProcessingRun) == ["COMPLETED"]
    assert states(pipeline, Job) == ["COMPLETED"]
    assert states(pipeline, Observation) == ["ACTIVE"]
    assert pipeline.count(Identity) == pipeline.count(Occurrence) == 1
    assert states(pipeline, IndexOperation) == ["APPLIED"]  # the wake ran after the commit


def test_a_failure_the_executor_settles_is_reported_and_leaves_private_output(
    pipeline: Pipeline,
) -> None:
    def fail() -> None:
        raise PerceptionError(MLErrorCode.INFERENCE_FAILED, "the embedder failed")

    pipeline.perception.on_represent = fail
    pipeline.enqueue(pipeline.import_image())

    outcome = pipeline.runner().run_once()

    assert outcome.kind is RunOutcomeKind.FAILED
    assert outcome.error == "PerceptionError"
    assert "embedder" not in str(outcome)  # a class name only, never the message
    assert states(pipeline, ProcessingRun) == ["FAILED"]
    assert states(pipeline, Job) == ["FAILED"]
    assert states(pipeline, Observation) == ["PENDING"]  # the detection stays private
    assert pipeline.count(Identity) == pipeline.count(Evidence) == 0


def test_a_cancellation_requested_during_work_ends_cancelled(pipeline: Pipeline) -> None:
    def request_cancel() -> None:
        with pipeline.lib.session_factory() as session:
            job = session.scalars(select(Job)).one()
            job.state = "CANCELLING"
            session.commit()

    pipeline.perception.on_represent = request_cancel
    pipeline.enqueue(pipeline.import_image())

    outcome = pipeline.runner().run_once()

    assert outcome.kind is RunOutcomeKind.CANCELLED
    assert states(pipeline, ProcessingRun) == ["CANCELLED"]
    assert states(pipeline, Job) == ["CANCELLED"]
    assert pipeline.count(Identity) == 0


def test_a_refused_final_makes_the_run_not_resumable_and_the_job_failed(
    pipeline: Pipeline, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*_args: object, **_kwargs: object) -> None:
        raise AcceptanceError("the FINAL checkpoint is not acceptable")

    monkeypatch.setattr(AcceptProcessingRunUseCase, "_accept", refuse)
    pipeline.enqueue(pipeline.import_image())

    outcome = pipeline.runner().run_once()

    assert outcome.kind is RunOutcomeKind.NOT_ACCEPTABLE
    assert outcome.error == "AcceptanceError"
    run = only(pipeline, ProcessingRun)
    job = only(pipeline, Job)
    assert (run.state, run.failure_code) == ("NOT_RESUMABLE", "FINAL_NOT_ACCEPTABLE")
    assert (job.state, job.failure_code) == ("FAILED", REFUSED_FINAL_CODE)
    assert job.lease_owner is None  # leaving a leased state released the lease
    assert states(pipeline, Observation) == ["PENDING"]
    assert states(pipeline, Representation) == ["PENDING"]  # the output is never exposed
    assert states(pipeline, Identity) == ["PENDING"]  # the new identity stays private
    assert pipeline.count(Occurrence) == pipeline.count(Evidence) == 0


def test_a_wake_error_after_the_commit_is_reported_and_the_run_stays_accepted(
    pipeline: Pipeline,
) -> None:
    def broken_wake() -> None:
        raise RuntimeError("index unavailable")

    pipeline.enqueue(pipeline.import_image())

    outcome = pipeline.runner(wake_index=broken_wake).run_once()

    assert outcome.kind is RunOutcomeKind.ACCEPTED
    assert outcome.wake_error == "RuntimeError"
    assert states(pipeline, ProcessingRun) == ["COMPLETED"]
    assert states(pipeline, IndexOperation) == ["PENDING"]  # durable, replayed by the coordinator
    pipeline.apply_index()
    assert states(pipeline, IndexOperation) == ["APPLIED"]


def test_an_error_before_the_acceptance_commits_propagates_and_the_run_stays_finalizing(
    pipeline: Pipeline, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("the database went away")

    monkeypatch.setattr(AcceptProcessingRunUseCase, "_accept", broken)
    pipeline.enqueue(pipeline.import_image())

    with pytest.raises(RuntimeError, match="the database went away"):
        pipeline.runner().run_once()

    assert states(pipeline, ProcessingRun) == ["FINALIZING"]  # recovery finishes it on restart
    assert states(pipeline, Job) == ["RUNNING"]
    assert states(pipeline, Observation) == ["PENDING"]


def test_a_defect_is_not_masked_when_settling_the_claim_fails_too(
    pipeline: Pipeline, monkeypatch: pytest.MonkeyPatch
) -> None:
    def defect() -> None:
        raise ValueError("a bug")

    pipeline.perception.on_represent = defect
    pipeline.enqueue(pipeline.import_image())
    runner = pipeline.runner()

    def unavailable(*_args: object) -> None:
        raise OSError("the database is gone")

    monkeypatch.setattr(runner._executor, "fail_claimed", unavailable)

    with pytest.raises(RuntimeError, match="unexpected ValueError") as raised:
        runner.run_once()

    assert isinstance(raised.value.__cause__, ValueError)  # the defect, not the settling error


def test_an_unexpected_defect_fails_the_claimed_work_and_is_raised(pipeline: Pipeline) -> None:
    def defect() -> None:
        raise ValueError("a bug")

    pipeline.perception.on_represent = defect
    pipeline.enqueue(pipeline.import_image())

    with pytest.raises(RuntimeError, match="unexpected ValueError") as raised:
        pipeline.runner().run_once()

    assert isinstance(raised.value.__cause__, ValueError)
    job = only(pipeline, Job)
    assert (job.state, job.failure_code) == ("FAILED", UNEXPECTED_CODE)
    assert states(pipeline, ProcessingRun) == ["FAILED"]
