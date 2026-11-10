"""Reprocessing images: versioned runs with atomic supersession (M6 step 1, issue 180; persistence
12.1, identity model 60.1, API 5.4). Issue 180's acceptance tests 1, 2 and 4 to 7 (test 3, the
process kills, is `tests/recovery/test_reprocess_process_kill.py`), on the image halves of TST-061,
TST-064 and TST-067.

Only perception is planted; SQLite, USearch, the scheduler, the executor, acceptance, the eraser and
the managed files are real.
"""

import shutil
import uuid
from typing import Any

import pytest
from sqlalchemy import Engine, select, update
from sqlalchemy.orm import Session

from backend.app.identities.corrections import confirm_occurrence
from backend.app.identities.forget import ForgetIdentityUseCase
from backend.app.identities.models import Evidence, Identity
from backend.app.identities.use_cases import resolve_ann_candidates
from backend.app.jobs.models import Job
from backend.app.memory.models import IndexOperation, Observation, Occurrence, Representation
from backend.app.people.use_cases import name_identity
from backend.app.processing.accept_run import AcceptanceError, AcceptProcessingRunUseCase
from backend.app.processing.cancel import CancelProcessingUseCase
from backend.app.processing.models import ProcessingRun
from backend.app.processing.process_source import (
    ProcessSourceError,
    SourceAlreadyProcessedError,
    SourceBusyError,
    SourceNotProcessedError,
)
from backend.app.processing.retry import RetryProcessingUseCase
from backend.app.runtime.perception_client import PerceptionError
from backend.app.sources.models import Source
from backend.infrastructure.db.unit_of_work import TransactionRetry, UnitOfWork
from backend.ml.contracts.protocol import MLErrorCode
from tests.factories.models import ModelFactory
from tests.fixtures.deterministic import FrozenClock, SeededUUIDs
from tests.fixtures.final_checkpoint import finalizing
from tests.fixtures.pipeline import Pipeline, prepare_catalog, unit
from tests.fixtures.story import A, B, C, files_containing, process

LEFT = (0.19, 0.2, 0.79, 0.8)  # each overlaps the planted face's box with IoU >= 0.7
RIGHT = (0.21, 0.2, 0.81, 0.8)


def rows(lib: Pipeline, model: Any, **where: Any) -> list[Any]:
    with lib.lib.session_factory() as session:
        query = select(model)
        for column, value in where.items():
            query = query.where(getattr(model, column) == value)
        found = list(session.scalars(query))
        session.expunge_all()
        return found


def current_run(lib: Pipeline, source_id: uuid.UUID) -> uuid.UUID | None:
    (source,) = rows(lib, Source, id=source_id)
    run_id: uuid.UUID | None = source.current_processing_run_id
    return run_id


def identity_of(lib: Pipeline, run_id: uuid.UUID) -> uuid.UUID:
    (representation,) = rows(lib, Representation, processing_run_id=run_id)
    assert representation.identity_id is not None
    identity_id: uuid.UUID = representation.identity_id
    return identity_id


def write(lib: Pipeline, change: Any) -> Any:
    return lib.lib.unit_of_work.write(change)


def name(lib: Pipeline, identity_id: uuid.UUID) -> None:
    write(lib, lambda s: name_identity(s, identity_id, "Ada", new_id=lib.new_id, clock=lib.clock))


def accepted(lib: Pipeline, run_id: uuid.UUID) -> Any:
    return AcceptProcessingRunUseCase(
        lib.lib.unit_of_work,
        new_id=lib.new_id,
        clock=lib.clock,
        wake_index=lib.apply_index,
        erase=lib.lib.eraser.erase,
    ).accept(run_id)


def kinds(lib: Pipeline, kind: str) -> list[Evidence]:
    return rows(lib, Evidence, kind=kind)


def active_occurrences(lib: Pipeline, source_id: uuid.UUID) -> list[Occurrence]:
    return rows(lib, Occurrence, source_id=source_id, state="ACTIVE")


def indexed(lib: Pipeline, representation: Representation) -> bool:
    assert representation.ann_key is not None
    index = lib.lib.coordinator.open_for_recognition(lib.space_id)
    return bool(index.contains(representation.ann_key))


def broken(_pixels: Any) -> Any:
    raise PerceptionError(MLErrorCode.COMPONENT_LOAD_FAILED, "the worker failed")


# --- 1. the current generation stays until one transaction replaces it (TST-061) ------------


def test_the_current_generation_stays_until_one_transaction_replaces_it(pipeline: Pipeline) -> None:
    lib = pipeline
    source_id, v1 = process(lib, A)
    (old,) = rows(lib, Representation, processing_run_id=v1)

    v2 = lib.reexecute(source_id)

    assert current_run(lib, source_id) == v1  # V2 is FINALIZING: V1 is still what everyone sees
    assert [o.state for o in rows(lib, Observation, processing_run_id=v1)] == ["ACTIVE"]
    assert [r.state for r in rows(lib, Representation, processing_run_id=v2)] == ["PENDING"]
    assert [o.processing_run_id for o in active_occurrences(lib, source_id)] == [v1]
    (run,) = rows(lib, ProcessingRun, id=v2)
    assert (run.state, run.supersedes_run_id) == ("FINALIZING", v1)
    (job,) = rows(lib, Job, processing_run_id=v2)
    assert job.type == "REPROCESS_SOURCE"

    lib.accept(v2, apply_index=True)

    assert current_run(lib, source_id) == v2
    (observation,) = rows(lib, Observation, processing_run_id=v1)
    assert (observation.state, observation.superseded_by_run_id) == ("SUPERSEDED", v2)
    assert observation.superseded_at == lib.clock()
    (superseded,) = rows(lib, Representation, processing_run_id=v1)
    assert (superseded.state, superseded.superseded_at) == ("SUPERSEDED", lib.clock())
    assert superseded.ann_key == old.ann_key  # kept as history, never reused
    (occurrence,) = rows(lib, Occurrence, processing_run_id=v1)
    assert (occurrence.state, occurrence.superseded_at) == ("SUPERSEDED", lib.clock())
    (new,) = rows(lib, Representation, processing_run_id=v2)
    assert new.state == "ACTIVE"
    assert [o.processing_run_id for o in active_occurrences(lib, source_id)] == [v2]
    (run,) = rows(lib, ProcessingRun, id=v2)
    assert (run.state, run.completed_at) == ("COMPLETED", lib.clock())
    assert [j.state for j in rows(lib, Job, processing_run_id=v2)] == ["COMPLETED"]
    (removal,) = rows(lib, IndexOperation, representation_id=old.id, operation="REMOVE")
    assert removal.state == "APPLIED"
    assert indexed(lib, new)
    assert not indexed(lib, superseded)


def test_recognition_never_takes_the_replaced_generation_as_evidence(pipeline: Pipeline) -> None:
    """V1's face is left out of V2's candidates (persistence 12.1 item 3): otherwise the same face
    would match itself."""
    lib = pipeline
    source_id, _v1 = process(lib, A)

    v2 = lib.reexecute(source_id)
    lib.accept(v2, apply_index=True)

    (created,) = rows(lib, Evidence, processing_run_id=v2)
    assert created.kind == "IDENTITY_CREATED"
    assert created.payload_json["candidates"] == []


# --- 2. failure, cancellation and refusal before activation leave V1 (TST-064) --------------


def v1_snapshot(lib: Pipeline, source_id: uuid.UUID) -> tuple[Any, ...]:
    def states(model: Any) -> list[tuple[str, str]]:
        return sorted(
            (str(row.id), row.state)
            for row in rows(lib, model)
            if row.state in ("ACTIVE", "SUPERSEDED")
        )

    return (
        current_run(lib, source_id),
        states(Observation),
        states(Representation),
        states(Occurrence),
        sorted(str(i.id) for i in rows(lib, Identity, state="ACTIVE")),
    )


@pytest.mark.parametrize("how", ["cancelled", "failed", "refused"])
def test_a_reprocess_that_never_activates_leaves_the_current_generation(
    pipeline: Pipeline, how: str
) -> None:
    lib = pipeline
    source_id, v1 = process(lib, A)
    before = v1_snapshot(lib, source_id)

    if how == "cancelled":
        lib.enqueue_reprocess(source_id)
        (run,) = [r for r in rows(lib, ProcessingRun) if r.supersedes_run_id == v1]
        CancelProcessingUseCase(lib.lib.unit_of_work, clock=lib.clock).cancel(run.id)
        state = "CANCELLED"
    elif how == "failed":
        lib.perception.detect = broken  # type: ignore[method-assign, assignment]
        with pytest.raises(PerceptionError):
            lib.reexecute(source_id)
        state = "FAILED"
    else:  # the generation it would replace is no longer current at activation
        v2 = lib.reexecute(source_id)
        write(lib, lambda s: s.execute(update(Source).values(current_processing_run_id=None)))
        with pytest.raises(AcceptanceError, match="no longer current"):
            lib.accept(v2, apply_index=True)
        write(lib, lambda s: s.execute(update(Source).values(current_processing_run_id=v1)))
        state = "FINALIZING"

    assert v1_snapshot(lib, source_id) == before
    (run,) = [r for r in rows(lib, ProcessingRun) if r.supersedes_run_id == v1]
    assert run.state == state
    assert [r.state for r in rows(lib, Representation, processing_run_id=run.id)] in (
        [],
        ["PENDING"],
    )


def test_a_retried_reprocess_keeps_what_it_replaces_and_activates(pipeline: Pipeline) -> None:
    lib = pipeline
    source_id, v1 = process(lib, A)
    real_detect = lib.perception.detect
    lib.perception.detect = broken  # type: ignore[method-assign, assignment]
    with pytest.raises(PerceptionError):
        lib.reexecute(source_id)
    lib.perception.detect = real_detect  # type: ignore[method-assign]
    (failed,) = [r for r in rows(lib, ProcessingRun) if r.supersedes_run_id == v1]
    (old_job,) = rows(lib, Job, processing_run_id=failed.id)

    scheduled = RetryProcessingUseCase(
        lib.lib.unit_of_work, new_id=lib.new_id, clock=lib.clock, wake_scheduler=lambda: None
    ).retry(old_job.id)
    retried = lib.run_next()
    lib.accept(retried, apply_index=True)

    assert retried == scheduled.processing_run_id
    (run,) = rows(lib, ProcessingRun, id=retried)
    assert (run.supersedes_run_id, run.parent_run_id) == (v1, failed.id)
    assert [j.type for j in rows(lib, Job, processing_run_id=retried)] == ["REPROCESS_SOURCE"]
    assert current_run(lib, source_id) == retried


# --- 4. no view double-counts or shows superseded evidence (TST-061) -----------------------


def test_a_stale_index_entry_for_the_old_generation_is_never_a_candidate(
    pipeline: Pipeline,
) -> None:
    lib = pipeline
    source_id, v1 = process(lib, A)
    (old,) = rows(lib, Representation, processing_run_id=v1)
    v2 = lib.reexecute(source_id)

    lib.accept(v2, apply_index=False)  # committed; the index has not caught up

    assert indexed(lib, old)  # the index still holds V1's vector
    assert old.ann_key is not None
    with lib.lib.session_factory() as session:
        assert resolve_ann_candidates(session, lib.space_id, [old.ann_key]) == []
    assert len(active_occurrences(lib, source_id)) == 1


def test_an_old_index_file_cannot_bring_the_old_generation_back(opened: Any) -> None:
    with opened() as lib:
        source_id, v1 = process(lib, A)
        directory = lib.lib.coordinator.index_directory(lib.space_id)
        saved = directory.parent / "saved-index"
        shutil.copytree(directory, saved)
        v2 = lib.reexecute(source_id)
        lib.accept(v2, apply_index=True)
    shutil.rmtree(directory)
    shutil.copytree(saved, directory)  # the library reopens with the index from before

    with opened() as lib:
        (old,) = rows(lib, Representation, processing_run_id=v1)
        (new,) = rows(lib, Representation, processing_run_id=v2)
        assert indexed(lib, new)
        assert not indexed(lib, old)
        assert current_run(lib, source_id) == v2
        assert len(active_occurrences(lib, source_id)) == 1


# --- 5. human decisions survive only through a trustworthy correspondence (TST-061) ---------


@pytest.mark.parametrize("decision", ["named", "confirmed"])
def test_a_human_decision_is_carried_to_the_corresponding_face(
    pipeline: Pipeline, decision: str
) -> None:
    lib = pipeline
    source_id, v1 = process(lib, A)
    person = identity_of(lib, v1)
    if decision == "named":
        name(lib, person)
    else:
        (occurrence,) = active_occurrences(lib, source_id)
        write(
            lib,
            lambda s: confirm_occurrence(
                s, occurrence.id, expected_identity_id=person, new_id=lib.new_id, clock=lib.clock
            ),
        )

    v2 = lib.reexecute(source_id)
    lib.accept(v2, apply_index=True)

    assert identity_of(lib, v2) == person
    (carried,) = kinds(lib, "REPROCESS_DECISION_CARRIED_OVER")
    (old,) = rows(lib, Representation, processing_run_id=v1)
    (new,) = rows(lib, Representation, processing_run_id=v2)
    payload = carried.payload_json
    assert payload["previous_representation_id"] == str(old.id)
    assert payload["representation_id"] == str(new.id)
    assert payload["iou"] == pytest.approx(1.0)
    assert payload["cosine"] == pytest.approx(1.0)
    assert carried.subject_identity_id == person
    assert [o.identity_id for o in active_occurrences(lib, source_id)] == [person]
    assert [i.id for i in rows(lib, Identity, state="ACTIVE")] == [person]  # no duplicate
    assert len(rows(lib, Identity, state="DELETED")) == 1  # V2's own pending one
    assert kinds(lib, "REPROCESS_REVIEW_REQUIRED") == []
    assert [e.kind for e in rows(lib, Evidence, processing_run_id=v2)] == [
        "REPROCESS_DECISION_CARRIED_OVER"
    ]


def test_a_second_reprocessing_carries_the_decision_again(pipeline: Pipeline) -> None:
    lib = pipeline
    source_id, v1 = process(lib, A)
    person = identity_of(lib, v1)
    name(lib, person)
    for _ in range(2):
        lib.accept(lib.reexecute(source_id), apply_index=True)

    current = current_run(lib, source_id)
    assert current is not None
    assert identity_of(lib, current) == person
    assert len(kinds(lib, "REPROCESS_DECISION_CARRIED_OVER")) == 2


def test_an_automatic_decision_is_not_carried(pipeline: Pipeline) -> None:
    lib = pipeline
    source_id, v1 = process(lib, A)
    automatic = identity_of(lib, v1)

    v2 = lib.reexecute(source_id)
    lib.accept(v2, apply_index=True)

    assert identity_of(lib, v2) != automatic  # V2's own decision applies
    assert kinds(lib, "REPROCESS_DECISION_CARRIED_OVER") == []
    assert kinds(lib, "REPROCESS_REVIEW_REQUIRED") == []


def test_an_ambiguous_correspondence_needs_review_and_assigns_nothing(pipeline: Pipeline) -> None:
    lib = pipeline
    source_id, v1 = process(lib, A)
    person = identity_of(lib, v1)
    name(lib, person)
    lib.perception.faces = [(LEFT, A), (RIGHT, B)]

    v2 = lib.reexecute(source_id)
    lib.accept(v2, apply_index=True)

    (review,) = kinds(lib, "REPROCESS_REVIEW_REQUIRED")
    assert review.payload_json["reason"] == "AMBIGUOUS"
    assert len(review.payload_json["candidate_representation_ids"]) == 2
    assert review.subject_identity_id == person
    assert all(r.identity_id != person for r in rows(lib, Representation, processing_run_id=v2))
    assert kinds(lib, "REPROCESS_DECISION_CARRIED_OVER") == []
    (identity,) = rows(lib, Identity, id=person)
    assert identity.state == "ACTIVE"  # the identity and its name are untouched


def test_a_vanished_face_needs_review(pipeline: Pipeline) -> None:
    lib = pipeline
    source_id, v1 = process(lib, A)
    name(lib, identity_of(lib, v1))
    lib.perception.vector = C  # the same place, a different face

    v2 = lib.reexecute(source_id)
    lib.accept(v2, apply_index=True)

    (review,) = kinds(lib, "REPROCESS_REVIEW_REQUIRED")
    assert review.payload_json["reason"] == "NO_CORRESPONDENCE"
    assert review.payload_json["candidate_representation_ids"] == []


def test_a_new_representation_space_is_never_compared(pipeline: Pipeline) -> None:
    lib = pipeline
    source_id, v1 = process(lib, A)
    person = identity_of(lib, v1)
    name(lib, person)
    catalog = prepare_catalog(lib.lib, lib.clock, lib.new_id)
    other = Pipeline(lib.lib, lib.clock, lib.new_id, catalog)

    v2 = other.reexecute(source_id)
    other.accept(v2, apply_index=True)

    (review,) = kinds(lib, "REPROCESS_REVIEW_REQUIRED")
    assert review.payload_json["reason"] == "SPACE_CHANGED"
    assert identity_of(lib, v2) != person
    assert current_run(lib, source_id) == v2


# --- 6. forget and erasure survive reprocessing and a restart (TST-067) ---------------------


def forget(lib: Pipeline, identity_id: uuid.UUID) -> None:
    ForgetIdentityUseCase(
        lib.lib.unit_of_work, lib.lib.eraser, lib.lib.store, clock=lib.clock, new_id=lib.new_id
    ).forget(identity_id)


@pytest.mark.parametrize("how", ["forgotten", "erased"])
def test_a_forgotten_face_never_comes_back(opened: Any, how: str) -> None:
    with opened() as lib:
        source_id, v1 = process(lib, A)
        (old,) = rows(lib, Representation, processing_run_id=v1)
        if how == "forgotten":
            forget(lib, identity_of(lib, v1))
        else:
            lib.lib.eraser.erase([old.id])

        v2 = lib.reexecute(source_id)
        result = accepted(lib, v2)

        assert result.erasing != ()
        (observation,) = rows(lib, Observation, processing_run_id=v2)
        (new,) = rows(lib, Representation, processing_run_id=v2)
        assert observation.state == "REJECTED"
        assert (new.state, new.vector, new.ann_key, new.identity_id) == ("ERASED", None, None, None)
        assert active_occurrences(lib, source_id) == []
        assert rows(lib, Identity, state="PENDING") == []
        assert rows(lib, IndexOperation, representation_id=new.id) == []
        assert files_containing(lib, A) == []
        assert current_run(lib, source_id) == v2
        assert accepted(lib, v2).already_accepted  # a repeat revalidates the suppressed shape

    with opened() as lib:  # and a restart brings nothing back
        assert active_occurrences(lib, source_id) == []
        assert [r.state for r in rows(lib, Representation)] == ["ERASED", "ERASED"]
        assert files_containing(lib, A) == []


def test_forgetting_after_reprocessing_erases_every_generation(pipeline: Pipeline) -> None:
    lib = pipeline
    source_id, v1 = process(lib, A)
    person = identity_of(lib, v1)
    name(lib, person)
    lib.accept(lib.reexecute(source_id), apply_index=True)

    forget(lib, person)

    assert sorted(r.state for r in rows(lib, Representation)) == ["ERASED", "ERASED"]
    assert active_occurrences(lib, source_id) == []
    assert files_containing(lib, A) == []


# --- 7. repeated and concurrent requests keep one authoritative generation (TST-064) -------


def test_requests_that_would_make_a_second_generation_are_refused(pipeline: Pipeline) -> None:
    lib = pipeline
    unprocessed = lib.import_image()
    with pytest.raises(SourceNotProcessedError):
        lib.enqueue_reprocess(unprocessed)
    source_id, _v1 = process(lib, A)
    with pytest.raises(SourceAlreadyProcessedError):
        lib.enqueue(source_id)
    lib.enqueue_reprocess(source_id)
    with pytest.raises(SourceBusyError):
        lib.enqueue_reprocess(source_id)
    assert len(rows(lib, ProcessingRun)) == 2


def test_a_repeated_activation_changes_nothing(pipeline: Pipeline) -> None:
    lib = pipeline
    source_id, v1 = process(lib, A)
    name(lib, identity_of(lib, v1))
    v2 = lib.reexecute(source_id)
    lib.accept(v2, apply_index=True)

    def counts() -> tuple[int, ...]:
        return tuple(
            len(rows(lib, model))
            for model in (Observation, Representation, Occurrence, Evidence, IndexOperation)
        )

    before = counts()
    assert accepted(lib, v2).already_accepted
    assert counts() == before
    assert len(active_occurrences(lib, source_id)) == 1


def test_a_second_first_run_is_never_accepted_over_a_result(pipeline: Pipeline) -> None:
    lib = pipeline
    lib.perception.vector = A
    source_id = lib.import_image()
    first, second = lib.execute(source_id), lib.execute(source_id)  # both before any result

    lib.accept(first, apply_index=True)
    with pytest.raises(AcceptanceError, match="already has an accepted generation"):
        lib.accept(second, apply_index=True)

    assert current_run(lib, source_id) == first
    assert len(active_occurrences(lib, source_id)) == 1


# --- what activation refuses, and what is not a human decision ------------------------------


def test_an_abstained_face_carries_no_decision(pipeline: Pipeline) -> None:
    lib = pipeline
    process(lib, unit(0.6, 0.8, 0, 0))  # another image: A resembles it, but too little to match
    source_id, v1 = process(lib, A)
    (abstained,) = rows(lib, Representation, processing_run_id=v1)
    assert (abstained.state, abstained.identity_id) == ("ACTIVE", None)

    lib.accept(lib.reexecute(source_id), apply_index=True)

    assert kinds(lib, "REPROCESS_DECISION_CARRIED_OVER") == []
    assert kinds(lib, "REPROCESS_REVIEW_REQUIRED") == []


def test_a_carried_decision_whose_identity_was_retired_refuses_activation(
    pipeline: Pipeline,
) -> None:
    lib = pipeline
    source_id, v1 = process(lib, A)
    person = identity_of(lib, v1)
    name(lib, person)
    v2 = lib.reexecute(source_id)
    write(
        lib,
        lambda s: s.execute(update(Identity).where(Identity.id == person).values(state="DELETED")),
    )

    with pytest.raises(AcceptanceError, match="carried-over identity is no longer ACTIVE"):
        lib.accept(v2, apply_index=True)

    assert current_run(lib, source_id) == v1


@pytest.mark.parametrize("tamper", ["rejected", "carried"])
def test_a_completed_reprocess_run_whose_faces_were_changed_is_refused_on_repeat(
    pipeline: Pipeline, tamper: str
) -> None:
    lib = pipeline
    source_id, v1 = process(lib, A)
    if tamper == "carried":
        name(lib, identity_of(lib, v1))
    v2 = lib.reexecute(source_id)
    lib.accept(v2, apply_index=True)
    if tamper == "rejected":  # a face rejected without an erased face to explain it
        change = update(Observation).where(Observation.processing_run_id == v2)
        write(lib, lambda s: s.execute(change.values(state="REJECTED")))
        expected = "unexplained rejected face"
    else:  # a carried face lost its occurrence
        change = update(Occurrence).where(Occurrence.processing_run_id == v2)
        write(lib, lambda s: s.execute(change.values(state="DELETED")))
        expected = "inconsistent carried face"

    with pytest.raises(AcceptanceError, match=expected):
        accepted(lib, v2)


def test_a_reprocess_run_without_a_frozen_space_is_refused(
    sqlite_engine: Engine, db_session: Session, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    run, _observation, _representation, _identity, job = finalizing(
        db_session, clock, new_id, "NO_FACE"
    )
    build = ModelFactory(db_session, clock, new_id)
    previous = build.run(source_id=run.source_id, state="COMPLETED")
    source = db_session.get(Source, run.source_id)
    assert source is not None
    source.current_processing_run_id = previous.id
    run.supersedes_run_id = previous.id
    job.type = "REPROCESS_SOURCE"
    db_session.commit()

    with pytest.raises(AcceptanceError, match="names no representation space"):
        AcceptProcessingRunUseCase(
            UnitOfWork(sqlite_engine, retry=TransactionRetry(1, lambda _: 0), sleep=lambda _: None),
            new_id=new_id,
            clock=clock,
        ).accept(run.id)


# --- what a retry refuses ------------------------------------------------------------------


def retry(lib: Pipeline, run_id: uuid.UUID) -> Any:
    (job,) = rows(lib, Job, processing_run_id=run_id)
    return RetryProcessingUseCase(
        lib.lib.unit_of_work, new_id=lib.new_id, clock=lib.clock, wake_scheduler=lambda: None
    ).retry(job.id)


def test_a_failed_first_run_is_not_retried_once_the_source_has_a_result(
    pipeline: Pipeline,
) -> None:
    lib = pipeline
    lib.perception.vector = A
    source_id = lib.import_image()
    lib.enqueue(source_id)
    lib.enqueue(source_id)  # both before any result
    lib.accept(lib.run_next(), apply_index=True)
    lib.perception.detect = broken  # type: ignore[method-assign, assignment]
    with pytest.raises(PerceptionError):
        lib.run_next()
    (failed,) = rows(lib, ProcessingRun, state="FAILED")

    with pytest.raises(SourceAlreadyProcessedError):
        retry(lib, failed.id)


def test_a_failed_reprocess_is_not_retried_once_its_predecessor_was_replaced(
    pipeline: Pipeline,
) -> None:
    lib = pipeline
    source_id, v1 = process(lib, A)
    real_detect = lib.perception.detect
    lib.perception.detect = broken  # type: ignore[method-assign, assignment]
    with pytest.raises(PerceptionError):
        lib.reexecute(source_id)
    lib.perception.detect = real_detect  # type: ignore[method-assign]
    (failed,) = rows(lib, ProcessingRun, state="FAILED")
    lib.accept(lib.reexecute(source_id), apply_index=True)  # V1 is replaced by another run

    with pytest.raises(ProcessSourceError, match="no longer current"):
        retry(lib, failed.id)


def test_a_failed_reprocess_is_not_retried_while_another_runs(pipeline: Pipeline) -> None:
    lib = pipeline
    source_id, _v1 = process(lib, A)
    real_detect = lib.perception.detect
    lib.perception.detect = broken  # type: ignore[method-assign, assignment]
    with pytest.raises(PerceptionError):
        lib.reexecute(source_id)
    lib.perception.detect = real_detect  # type: ignore[method-assign]
    (failed,) = rows(lib, ProcessingRun, state="FAILED")
    lib.enqueue_reprocess(source_id)

    with pytest.raises(SourceBusyError):
        retry(lib, failed.id)
