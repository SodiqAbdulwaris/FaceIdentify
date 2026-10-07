"""Requesting the cancellation of a processing run (M4 W3.4; TST-060).

The use case writes the request; the executor observes it between work units and settles
`CANCELLED`, and recovery settles one a crash left behind. Perception is planted (no weights); the
library, scheduler, executor and acceptance are real.
"""

import uuid
from typing import Any

import pytest
from sqlalchemy import select

from backend.app.identities.models import Identity
from backend.app.jobs.models import Job
from backend.app.processing.cancel import (
    CancelError,
    CancelOutcome,
    CancelProcessingUseCase,
    RunNotFoundError,
)
from backend.app.processing.models import ProcessingRun
from backend.app.processing.runner import RunOutcomeKind
from backend.app.runtime.perception_client import PerceptionError
from backend.ml.contracts.protocol import MLErrorCode
from tests.fixtures.pipeline import Pipeline


def cancel(pipeline: Pipeline, run_id: uuid.UUID) -> Any:
    return CancelProcessingUseCase(pipeline.lib.unit_of_work, clock=pipeline.clock).cancel(run_id)


def only[T](pipeline: Pipeline, model: type[T]) -> T:
    with pipeline.lib.session_factory() as session:
        return session.scalars(select(model)).one()


def fail() -> None:
    raise PerceptionError(MLErrorCode.INFERENCE_FAILED, "the embedder failed")


def queued_run(pipeline: Pipeline) -> uuid.UUID:
    pipeline.enqueue(pipeline.import_image())
    return only(pipeline, ProcessingRun).id


def test_a_queued_run_is_cancelled_at_once_and_never_claimed(pipeline: Pipeline) -> None:
    run_id = queued_run(pipeline)

    result = cancel(pipeline, run_id)

    assert result.outcome is CancelOutcome.CANCELLED
    run, job = only(pipeline, ProcessingRun), only(pipeline, Job)
    assert (run.state, job.state) == ("CANCELLED", "CANCELLED")
    assert job.ended_at is not None
    assert (job.lease_owner, job.lease_expires_at) == (None, None)
    assert pipeline.runner().run_once().kind is RunOutcomeKind.IDLE
    assert pipeline.perception.calls == 0


def test_a_repeated_cancel_changes_nothing(pipeline: Pipeline) -> None:
    run_id = queued_run(pipeline)
    cancel(pipeline, run_id)
    revision = only(pipeline, ProcessingRun).revision

    again = cancel(pipeline, run_id)

    assert again.outcome is CancelOutcome.ALREADY
    assert only(pipeline, ProcessingRun).revision == revision


def test_a_running_run_is_asked_to_stop_and_settles_cancelled_with_private_output(
    pipeline: Pipeline,
) -> None:
    seen: list[CancelOutcome] = []

    def cancel_while_working() -> None:
        run = only(pipeline, ProcessingRun)
        assert (run.state, only(pipeline, Job).state) == ("RUNNING", "RUNNING")
        seen.append(cancel(pipeline, run.id).outcome)
        assert (only(pipeline, ProcessingRun).state, only(pipeline, Job).state) == (
            "CANCELLING",
            "CANCELLING",
        )
        assert only(pipeline, Job).lease_owner is not None  # the worker still holds it
        seen.append(cancel(pipeline, run.id).outcome)  # a repeat while stopping is harmless

    pipeline.perception.on_represent = cancel_while_working
    queued_run(pipeline)

    outcome = pipeline.runner().run_once()

    assert seen == [CancelOutcome.REQUESTED, CancelOutcome.ALREADY]
    assert outcome.kind is RunOutcomeKind.CANCELLED
    assert (only(pipeline, ProcessingRun).state, only(pipeline, Job).state) == (
        "CANCELLED",
        "CANCELLED",
    )
    assert pipeline.count(Identity) == 0


def test_a_run_that_is_being_made_authoritative_cannot_be_cancelled(pipeline: Pipeline) -> None:
    run_id = pipeline.execute(pipeline.import_image())  # FINAL written: FINALIZING

    with pytest.raises(CancelError, match="FINALIZING"):
        cancel(pipeline, run_id)

    assert only(pipeline, ProcessingRun).state == "FINALIZING"
    pipeline.accept(run_id, apply_index=False)  # and it is still accepted
    assert only(pipeline, ProcessingRun).state == "COMPLETED"


@pytest.mark.parametrize("fate", ["COMPLETED", "FAILED"])
def test_a_run_that_is_over_cannot_be_cancelled(pipeline: Pipeline, fate: str) -> None:
    run_id = queued_run(pipeline)
    if fate == "COMPLETED":
        assert pipeline.runner().run_once().kind is RunOutcomeKind.ACCEPTED
    else:
        pipeline.perception.on_represent = fail
        assert pipeline.runner().run_once().kind is RunOutcomeKind.FAILED

    with pytest.raises(CancelError, match=fate):
        cancel(pipeline, run_id)

    assert only(pipeline, ProcessingRun).state == fate


def test_a_pending_run_with_no_job_cannot_be_cancelled(pipeline: Pipeline) -> None:
    run_id = queued_run(pipeline)
    with pipeline.lib.session_factory() as session:
        session.delete(session.scalars(select(Job)).one())
        session.commit()

    with pytest.raises(CancelError, match="PENDING"):
        cancel(pipeline, run_id)


def test_an_unknown_run_is_not_found(pipeline: Pipeline) -> None:
    with pytest.raises(RunNotFoundError):
        cancel(pipeline, uuid.uuid4())
