"""The FINAL-to-authoritative boundary (M3 step 11, TST-042)."""

import uuid
from collections.abc import Callable

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from backend.app.identities.models import (
    Evidence,
    EvidenceCandidate,
    EvidenceRepresentation,
)
from backend.app.jobs.models import Job
from backend.app.memory.models import (
    IndexOperation,
    Observation,
    Occurrence,
    OccurrenceObservation,
    Representation,
)
from backend.app.processing.accept_run import (
    AcceptanceError,
    AcceptProcessingRunUseCase,
    _Decision,
)
from backend.app.processing.models import (
    ProcessingCheckpoint,
    ProcessingRun,
)
from backend.app.recognition.reasoner import Reason, RecognitionOutcome
from backend.app.sources.models import Source
from backend.infrastructure.db.unit_of_work import TransactionRetry, UnitOfWork
from tests.factories.models import ModelFactory
from tests.fixtures.deterministic import FrozenClock, SeededUUIDs
from tests.fixtures.final_checkpoint import candidate, finalizing


def use_case(
    engine: Engine, clock: FrozenClock, new_id: SeededUUIDs, wake: Callable[[], None] | None = None
) -> AcceptProcessingRunUseCase:
    return AcceptProcessingRunUseCase(
        UnitOfWork(engine, retry=TransactionRetry(1, lambda _: 0), sleep=lambda _: None),
        new_id=new_id,
        clock=clock,
        wake_index=wake,
    )


@pytest.mark.parametrize("outcome", ["CREATE_NEW", "MATCH_EXISTING", "ABSTAIN"])
def test_acceptance_activates_private_output_atomically(
    sqlite_engine: Engine,
    db_session: Session,
    clock: FrozenClock,
    new_id: SeededUUIDs,
    outcome: str,
) -> None:
    run, observation, representation, identity, job = finalizing(db_session, clock, new_id, outcome)
    wakes: list[str] = []

    result = use_case(sqlite_engine, clock, new_id, lambda: wakes.append("wake")).accept(run.id)

    assert result.already_accepted is False
    assert wakes == ["wake"]
    db_session.expire_all()
    persisted_run = db_session.get(ProcessingRun, run.id)
    persisted_job = db_session.get(Job, job.id)
    assert persisted_run is not None
    assert persisted_run.state == "COMPLETED"
    assert persisted_job is not None
    assert persisted_job.state == "COMPLETED"
    if observation is None:
        assert db_session.scalar(select(func.count()).select_from(Occurrence)) == 0
        return
    assert representation is not None
    persisted_observation = db_session.get(Observation, observation.id)
    persisted_representation = db_session.get(Representation, representation.id)
    assert persisted_observation is not None
    assert persisted_observation.state == "ACTIVE"
    assert persisted_representation is not None
    assert persisted_representation.state == "ACTIVE"
    assert persisted_representation.ann_key == 1
    assert db_session.scalar(select(func.count()).select_from(IndexOperation)) == 1
    evidence = db_session.scalars(select(Evidence)).one()
    if outcome == "ABSTAIN":
        assert persisted_representation.identity_id is None
        assert evidence.kind == "RECOGNITION_ABSTAINED"
        assert db_session.scalar(select(func.count()).select_from(Occurrence)) == 0
    else:
        assert identity is not None
        assert persisted_representation.identity_id == identity.id
        assert db_session.scalar(select(func.count()).select_from(Occurrence)) == 1
        assert evidence.kind == (
            "IDENTITY_CREATED" if outcome == "CREATE_NEW" else "IDENTITY_MATCHED"
        )


def test_repeated_acceptance_validates_and_does_not_duplicate_rows(
    sqlite_engine: Engine, db_session: Session, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    run, _observation, _representation, _identity, _job = finalizing(
        db_session, clock, new_id, "ABSTAIN"
    )
    accept = use_case(sqlite_engine, clock, new_id)

    assert accept.accept(run.id).already_accepted is False
    assert accept.accept(run.id).already_accepted is True

    db_session.expire_all()
    assert db_session.scalar(select(func.count()).select_from(Evidence)) == 1
    assert db_session.scalar(select(func.count()).select_from(IndexOperation)) == 1


def test_acceptance_handles_each_private_face_in_a_final_checkpoint(
    sqlite_engine: Engine, db_session: Session, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    run, observation, representation, _identity, _job = finalizing(
        db_session, clock, new_id, "ABSTAIN"
    )
    assert observation is not None
    assert representation is not None
    build = ModelFactory(db_session, clock, new_id)
    second_observation = build.observation(
        run, execution_segment_id=observation.execution_segment_id, sequence_in_run=1
    )
    second_observation.quality_json = {"schema_version": 1, "detection_score": 0.9}
    second_representation = build.representation(
        second_observation, representation_space_id=representation.representation_space_id
    )
    checkpoint = db_session.get(ProcessingCheckpoint, run.current_checkpoint_id)
    assert checkpoint is not None
    first_decision = checkpoint.payload_json["decisions"][0]
    checkpoint.payload_json = {
        **checkpoint.payload_json,
        "observations": [str(observation.id), str(second_observation.id)],
        "decisions": [
            first_decision,
            {
                **first_decision,
                "observation_id": str(second_observation.id),
                "representation_id": str(second_representation.id),
            },
        ],
    }
    db_session.commit()

    use_case(sqlite_engine, clock, new_id).accept(run.id)

    assert db_session.scalar(select(func.count()).select_from(IndexOperation)) == 2


def test_repeated_acceptance_remains_idempotent_after_a_source_lifecycle_change(
    sqlite_engine: Engine, db_session: Session, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    run, _observation, _representation, _identity, _job = finalizing(
        db_session, clock, new_id, "ABSTAIN"
    )
    accept = use_case(sqlite_engine, clock, new_id)
    assert accept.accept(run.id).already_accepted is False
    source = db_session.get(Source, run.source_id)
    assert source is not None
    source.state = "RECYCLED"
    db_session.commit()

    assert accept.accept(run.id).already_accepted is True
    assert db_session.scalar(select(func.count()).select_from(Evidence)) == 1


def test_bad_final_output_rolls_back_without_waking_or_exposing_anything(
    sqlite_engine: Engine, db_session: Session, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    run, _observation, representation, _identity, _job = finalizing(
        db_session, clock, new_id, "ABSTAIN"
    )
    assert representation is not None
    final = db_session.get(ProcessingCheckpoint, run.current_checkpoint_id)
    assert final is not None
    final.payload_json = {
        **final.payload_json,
        "decisions": [
            {**final.payload_json["decisions"][0], "representation_id": str(uuid.uuid4())}
        ],
    }
    db_session.commit()
    wakes: list[str] = []

    with pytest.raises(AcceptanceError, match="private representations"):
        use_case(sqlite_engine, clock, new_id, lambda: wakes.append("wake")).accept(run.id)

    assert wakes == []
    db_session.expire_all()
    assert db_session.get(ProcessingRun, run.id).state == "FINALIZING"  # type: ignore[union-attr]
    assert db_session.get(Representation, representation.id).state == "PENDING"  # type: ignore[union-attr]
    assert db_session.scalar(select(func.count()).select_from(Evidence)) == 0


def test_an_abstention_that_secretly_names_an_identity_is_refused_atomically(
    sqlite_engine: Engine, db_session: Session, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    run, _observation, representation, _identity, _job = finalizing(
        db_session, clock, new_id, "ABSTAIN"
    )
    assert representation is not None
    representation.identity_id = ModelFactory(db_session, clock, new_id).identity().id
    db_session.commit()

    with pytest.raises(AcceptanceError, match="ABSTAIN must not name an identity"):
        use_case(sqlite_engine, clock, new_id).accept(run.id)

    db_session.expire_all()
    persisted = db_session.get(Representation, representation.id)
    assert persisted is not None
    assert persisted.state == "PENDING"
    assert db_session.scalar(select(func.count()).select_from(Evidence)) == 0


def test_a_post_commit_wake_error_cannot_undo_the_authoritative_acceptance(
    sqlite_engine: Engine, db_session: Session, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    run, _observation, representation, _identity, _job = finalizing(
        db_session, clock, new_id, "ABSTAIN"
    )
    assert representation is not None

    with pytest.raises(RuntimeError, match="wake failed"):
        use_case(
            sqlite_engine, clock, new_id, lambda: (_ for _ in ()).throw(RuntimeError("wake failed"))
        ).accept(run.id)

    db_session.expire_all()
    assert db_session.get(ProcessingRun, run.id).state == "COMPLETED"  # type: ignore[union-attr]
    assert db_session.get(Representation, representation.id).state == "ACTIVE"  # type: ignore[union-attr]
    assert db_session.scalar(select(func.count()).select_from(IndexOperation)) == 1


def test_abstention_candidates_are_historical_evidence(
    sqlite_engine: Engine, db_session: Session, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    run, _observation, representation, _identity, _job = finalizing(
        db_session, clock, new_id, "ABSTAIN"
    )
    assert representation is not None
    build = ModelFactory(db_session, clock, new_id)
    historical = build.representation(
        build.observation(),
        representation_space_id=representation.representation_space_id,
        state="ACTIVE",
        ann_key=2,
        activated_at=clock(),
    )
    final = db_session.get(ProcessingCheckpoint, run.current_checkpoint_id)
    assert final is not None
    final.payload_json = {
        **final.payload_json,
        "decisions": [
            {
                **final.payload_json["decisions"][0],
                "evidence": {
                    **final.payload_json["decisions"][0]["evidence"],
                    "candidates": [
                        {
                            "rank": 1,
                            "identity_id": None,
                            "similarity": 0.4,
                            "members": [
                                {
                                    "representation_id": str(historical.id),
                                    "pool": "GLOBAL",
                                    "similarity": 0.4,
                                }
                            ],
                        }
                    ],
                    "retrieval": {
                        **final.payload_json["decisions"][0]["evidence"]["retrieval"],
                        "returned": 1,
                    },
                },
            }
        ],
    }
    db_session.commit()

    use_case(sqlite_engine, clock, new_id).accept(run.id)

    candidate = db_session.scalars(select(EvidenceCandidate)).one()
    evidence = db_session.get(Evidence, candidate.evidence_id)
    assert evidence is not None
    assert evidence.kind == "RECOGNITION_ABSTAINED"
    assert candidate.decision == "CONSIDERED"
    candidate.details_json = {"tampered": True}
    db_session.commit()

    with pytest.raises(AcceptanceError, match="inconsistent candidate evidence"):
        use_case(sqlite_engine, clock, new_id).accept(run.id)


def test_matched_identity_evidence_keeps_its_candidate_snapshot(
    sqlite_engine: Engine, db_session: Session, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    run, _observation, representation, _identity, _job = finalizing(
        db_session, clock, new_id, "MATCH_EXISTING"
    )
    final = db_session.get(ProcessingCheckpoint, run.current_checkpoint_id)
    assert final is not None
    assert representation is not None
    db_session.commit()

    use_case(sqlite_engine, clock, new_id).accept(run.id)

    assert db_session.scalars(select(EvidenceCandidate)).one().evidence_id is not None


def test_final_decision_must_follow_its_valid_candidate_snapshot(
    sqlite_engine: Engine, db_session: Session, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    run, _observation, representation, _identity, _job = finalizing(
        db_session, clock, new_id, "MATCH_EXISTING"
    )
    assert representation is not None
    final = db_session.get(ProcessingCheckpoint, run.current_checkpoint_id)
    assert final is not None
    decision = final.payload_json["decisions"][0]
    evidence = decision["evidence"]
    representation.identity_id = None
    final.payload_json = {
        **final.payload_json,
        "decisions": [
            {
                **decision,
                "outcome": "ABSTAIN",
                "reason": Reason.UNCERTAIN_SIMILARITY.value,
                "identity_id": None,
                "evidence": {
                    **evidence,
                    "outcome": "ABSTAIN",
                    "reason": Reason.UNCERTAIN_SIMILARITY.value,
                    "identity_id": None,
                },
            }
        ],
    }
    db_session.commit()

    with pytest.raises(AcceptanceError, match="does not follow its evidence"):
        use_case(sqlite_engine, clock, new_id).accept(run.id)


def test_final_policy_must_match_the_frozen_run_configuration(
    sqlite_engine: Engine, db_session: Session, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    run, _observation, representation, _identity, _job = finalizing(
        db_session, clock, new_id, "MATCH_EXISTING"
    )
    assert representation is not None
    final = db_session.get(ProcessingCheckpoint, run.current_checkpoint_id)
    assert final is not None
    decision = final.payload_json["decisions"][0]
    evidence = decision["evidence"]
    representation.identity_id = None
    altered_policy = {**evidence["policy"], "match_threshold": 0.95}
    final.payload_json = {
        **final.payload_json,
        "decisions": [
            {
                **decision,
                "outcome": "ABSTAIN",
                "reason": Reason.UNCERTAIN_SIMILARITY.value,
                "identity_id": None,
                "evidence": {
                    **evidence,
                    "outcome": "ABSTAIN",
                    "reason": Reason.UNCERTAIN_SIMILARITY.value,
                    "identity_id": None,
                    "policy": altered_policy,
                },
            }
        ],
    }
    db_session.commit()

    with pytest.raises(AcceptanceError, match="policy does not match the frozen"):
        use_case(sqlite_engine, clock, new_id).accept(run.id)


def test_final_quality_must_match_its_private_observation(
    sqlite_engine: Engine, db_session: Session, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    run, _observation, representation, _identity, _job = finalizing(
        db_session, clock, new_id, "MATCH_EXISTING"
    )
    assert representation is not None
    final = db_session.get(ProcessingCheckpoint, run.current_checkpoint_id)
    assert final is not None
    decision = final.payload_json["decisions"][0]
    evidence = decision["evidence"]
    representation.identity_id = None
    final.payload_json = {
        **final.payload_json,
        "decisions": [
            {
                **decision,
                "outcome": "ABSTAIN",
                "reason": Reason.LOW_QUALITY.value,
                "identity_id": None,
                "evidence": {
                    **evidence,
                    "outcome": "ABSTAIN",
                    "reason": Reason.LOW_QUALITY.value,
                    "identity_id": None,
                    "quality": {"detection_score": 0.1},
                },
            }
        ],
    }
    db_session.commit()

    with pytest.raises(AcceptanceError, match="quality does not match its private observation"):
        use_case(sqlite_engine, clock, new_id).accept(run.id)


@pytest.mark.parametrize(
    ("snapshot_schema_version", "snapshot_root_schema_version", "outcome", "state"),
    [
        (2, 1, "ABSTAIN", "FINALIZING"),
        (1, 2, "NO_FACE", "FINALIZING"),
        (2, 1, "NO_FACE", "COMPLETED"),
    ],
)
def test_final_rejects_an_unsupported_configuration_snapshot(
    sqlite_engine: Engine,
    db_session: Session,
    clock: FrozenClock,
    new_id: SeededUUIDs,
    snapshot_schema_version: int,
    snapshot_root_schema_version: int,
    outcome: str,
    state: str,
) -> None:
    run, _observation, _representation, _identity, _job = finalizing(
        db_session,
        clock,
        new_id,
        outcome,
        snapshot_schema_version=snapshot_schema_version,
        snapshot_root_schema_version=snapshot_root_schema_version,
    )
    run.state = state
    db_session.commit()

    with pytest.raises(AcceptanceError, match="unsupported configuration snapshot"):
        use_case(sqlite_engine, clock, new_id).accept(run.id)


def test_run_local_candidate_identity_must_be_active_or_owned_by_its_run(
    sqlite_engine: Engine, db_session: Session, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    run, observation, representation, _identity, _job = finalizing(
        db_session, clock, new_id, "ABSTAIN"
    )
    assert observation is not None
    assert representation is not None
    build = ModelFactory(db_session, clock, new_id)
    stale_identity = build.identity(state="PENDING")
    local_observation = build.observation(
        run, execution_segment_id=observation.execution_segment_id, sequence_in_run=1
    )
    local = build.representation(
        local_observation,
        representation_space_id=representation.representation_space_id,
        identity_id=stale_identity.id,
    )
    final = db_session.get(ProcessingCheckpoint, run.current_checkpoint_id)
    assert final is not None
    decision = final.payload_json["decisions"][0]
    evidence = decision["evidence"]
    final.payload_json = {
        **final.payload_json,
        "decisions": [
            {
                **decision,
                "evidence": {
                    **evidence,
                    "candidates": [
                        {
                            "rank": 1,
                            "identity_id": str(stale_identity.id),
                            "similarity": 0.4,
                            "members": [
                                {
                                    "representation_id": str(local.id),
                                    "pool": "RUN_LOCAL",
                                    "similarity": 0.4,
                                }
                            ],
                        }
                    ],
                    "retrieval": {**evidence["retrieval"], "returned": 1},
                },
            },
        ],
    }
    db_session.commit()

    _checkpoint, decisions = use_case(sqlite_engine, clock, new_id)._final(db_session, run)
    with pytest.raises(AcceptanceError, match="candidate member is not authoritative"):
        use_case(sqlite_engine, clock, new_id)._validate_reasoned_decision(
            db_session, run, decisions[0], representation
        )


def test_final_candidate_snapshot_must_stay_best_first(
    sqlite_engine: Engine, db_session: Session, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    run, _observation, representation, _identity, _job = finalizing(
        db_session, clock, new_id, "MATCH_EXISTING"
    )
    assert representation is not None
    build = ModelFactory(db_session, clock, new_id)
    later_identity = build.identity()
    later = build.representation(
        build.observation(),
        representation_space_id=representation.representation_space_id,
        state="ACTIVE",
        identity_id=later_identity.id,
        ann_key=3,
        activated_at=clock(),
    )
    final = db_session.get(ProcessingCheckpoint, run.current_checkpoint_id)
    assert final is not None
    decision = final.payload_json["decisions"][0]
    evidence = decision["evidence"]
    final.payload_json = {
        **final.payload_json,
        "decisions": [
            {
                **decision,
                "evidence": {
                    **evidence,
                    "candidates": [
                        *evidence["candidates"],
                        candidate(later.id, rank=2, identity_id=later_identity.id, similarity=0.95),
                    ],
                    "retrieval": {**evidence["retrieval"], "returned": 2},
                    "margin": 0.9 - 0.95,
                },
            }
        ],
    }
    db_session.commit()

    with pytest.raises(AcceptanceError, match="candidates are not best-first"):
        use_case(sqlite_engine, clock, new_id).accept(run.id)


def test_final_candidate_member_must_not_name_private_output(
    sqlite_engine: Engine, db_session: Session, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    run, _observation, representation, _identity, _job = finalizing(
        db_session, clock, new_id, "MATCH_EXISTING"
    )
    assert representation is not None
    final = db_session.get(ProcessingCheckpoint, run.current_checkpoint_id)
    assert final is not None
    decision = final.payload_json["decisions"][0]
    evidence = decision["evidence"]
    original = evidence["candidates"][0]
    final.payload_json = {
        **final.payload_json,
        "decisions": [
            {
                **decision,
                "evidence": {
                    **evidence,
                    "candidates": [
                        {
                            **original,
                            "members": [
                                {
                                    **original["members"][0],
                                    "representation_id": str(representation.id),
                                }
                            ],
                        }
                    ],
                },
            }
        ],
    }
    db_session.commit()

    with pytest.raises(AcceptanceError, match="candidate member is not authoritative"):
        use_case(sqlite_engine, clock, new_id).accept(run.id)


def test_global_candidate_member_must_name_an_active_identity(
    sqlite_engine: Engine, db_session: Session, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    run, _observation, representation, _identity, _job = finalizing(
        db_session, clock, new_id, "ABSTAIN"
    )
    assert representation is not None
    build = ModelFactory(db_session, clock, new_id)
    inactive_identity = build.identity(state="PENDING")
    inactive = build.representation(
        build.observation(),
        representation_space_id=representation.representation_space_id,
        state="ACTIVE",
        identity_id=inactive_identity.id,
        ann_key=2,
        activated_at=clock(),
    )
    final = db_session.get(ProcessingCheckpoint, run.current_checkpoint_id)
    assert final is not None
    decision = final.payload_json["decisions"][0]
    evidence = decision["evidence"]
    final.payload_json = {
        **final.payload_json,
        "decisions": [
            {
                **decision,
                "evidence": {
                    **evidence,
                    "candidates": [
                        candidate(inactive.id, identity_id=inactive_identity.id, similarity=0.4)
                    ],
                    "retrieval": {**evidence["retrieval"], "returned": 1},
                },
            }
        ],
    }
    db_session.commit()

    with pytest.raises(AcceptanceError, match="candidate member is not authoritative"):
        use_case(sqlite_engine, clock, new_id).accept(run.id)


def test_final_candidate_members_must_stay_best_first(
    sqlite_engine: Engine, db_session: Session, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    run, _observation, representation, identity, _job = finalizing(
        db_session, clock, new_id, "MATCH_EXISTING"
    )
    assert representation is not None
    assert identity is not None
    build = ModelFactory(db_session, clock, new_id)
    lesser = build.representation(
        build.observation(),
        representation_space_id=representation.representation_space_id,
        state="ACTIVE",
        identity_id=identity.id,
        ann_key=3,
        activated_at=clock(),
    )
    final = db_session.get(ProcessingCheckpoint, run.current_checkpoint_id)
    assert final is not None
    decision = final.payload_json["decisions"][0]
    evidence = decision["evidence"]
    original = evidence["candidates"][0]
    final.payload_json = {
        **final.payload_json,
        "decisions": [
            {
                **decision,
                "evidence": {
                    **evidence,
                    "candidates": [
                        {
                            **original,
                            "members": [
                                {
                                    "representation_id": str(lesser.id),
                                    "pool": "GLOBAL",
                                    "similarity": 0.8,
                                },
                                *original["members"],
                            ],
                        }
                    ],
                    "retrieval": {**evidence["retrieval"], "returned": 2},
                },
            }
        ],
    }
    db_session.commit()

    with pytest.raises(AcceptanceError, match="candidate members are not best-first"):
        use_case(sqlite_engine, clock, new_id).accept(run.id)


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"unexpected": True}, "unknown or missing field"),
        ({"schema_version": 2, "observations": [], "decisions": []}, "unsupported"),
        ({"schema_version": 1, "observations": "wrong", "decisions": []}, "must be lists"),
        (
            {"schema_version": 1, "observations": [str(uuid.uuid4())] * 2, "decisions": []},
            "repeats an observation",
        ),
        (
            {"schema_version": 1, "observations": [str(uuid.uuid4())], "decisions": []},
            "do not cover",
        ),
    ],
)
def test_final_checkpoint_schema_fails_closed(
    sqlite_engine: Engine,
    db_session: Session,
    clock: FrozenClock,
    new_id: SeededUUIDs,
    payload: dict[str, object],
    message: str,
) -> None:
    run, _observation, _representation, _identity, _job = finalizing(
        db_session, clock, new_id, "NO_FACE"
    )
    checkpoint = db_session.get(ProcessingCheckpoint, run.current_checkpoint_id)
    assert checkpoint is not None
    checkpoint.payload_json = payload
    db_session.flush()

    with pytest.raises(AcceptanceError, match=message):
        use_case(sqlite_engine, clock, new_id)._final(db_session, run)


def test_final_checkpoint_requires_the_current_supported_final(
    sqlite_engine: Engine, db_session: Session, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    run, _observation, _representation, _identity, _job = finalizing(
        db_session, clock, new_id, "NO_FACE"
    )
    run.current_checkpoint_id = None
    db_session.flush()

    with pytest.raises(AcceptanceError, match="no current supported FINAL"):
        use_case(sqlite_engine, clock, new_id)._final(db_session, run)


def test_final_checkpoint_refuses_a_repeated_representation(
    sqlite_engine: Engine, db_session: Session, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    run, _observation, _representation, _identity, _job = finalizing(
        db_session, clock, new_id, "ABSTAIN"
    )
    checkpoint = db_session.get(ProcessingCheckpoint, run.current_checkpoint_id)
    assert checkpoint is not None
    checkpoint.payload_json = {
        **checkpoint.payload_json,
        "decisions": checkpoint.payload_json["decisions"] * 2,
    }
    db_session.flush()

    with pytest.raises(AcceptanceError, match="repeats a representation"):
        use_case(sqlite_engine, clock, new_id)._final(db_session, run)


@pytest.mark.parametrize(
    ("value", "message"),
    [
        (None, "not a string"),
        ("not-a-uuid", "invalid"),
        ({}, "unknown or missing field"),
        (
            {
                "observation_id": str(uuid.uuid4()),
                "representation_id": str(uuid.uuid4()),
                "outcome": "NOT_REAL",
                "reason": "TEST",
                "identity_id": None,
                "evidence": {},
            },
            "invalid outcome",
        ),
        (
            {
                "observation_id": str(uuid.uuid4()),
                "representation_id": str(uuid.uuid4()),
                "outcome": "ABSTAIN",
                "reason": "NOT_REAL",
                "identity_id": None,
                "evidence": {},
            },
            "invalid reason",
        ),
        (
            {
                "observation_id": str(uuid.uuid4()),
                "representation_id": str(uuid.uuid4()),
                "outcome": "ABSTAIN",
                "reason": "MATCHED",
                "identity_id": None,
                "evidence": {},
            },
            "does not support",
        ),
        (
            {
                "observation_id": str(uuid.uuid4()),
                "representation_id": str(uuid.uuid4()),
                "outcome": "ABSTAIN",
                "reason": "UNCERTAIN_SIMILARITY",
                "identity_id": None,
                "evidence": [],
            },
            "not an object",
        ),
    ],
)
def test_final_scalar_decoders_fail_closed(
    sqlite_engine: Engine,
    clock: FrozenClock,
    new_id: SeededUUIDs,
    value: object,
    message: str,
) -> None:
    accept = use_case(sqlite_engine, clock, new_id)
    if value is None or isinstance(value, str):
        with pytest.raises(AcceptanceError, match=message):
            accept._uuid(value, "test")
    else:
        with pytest.raises(AcceptanceError, match=message):
            accept._decision(value)


@pytest.mark.parametrize(
    ("evidence", "message"),
    [
        ({"candidates": {}}, "not a list"),
        ({"candidates": [{}]}, "malformed"),
        ({"candidates": [{"rank": 0, "members": [{}]}]}, "malformed"),
        ({"candidates": [{"rank": 0, "members": ["not-an-object"]}]}, "malformed"),
    ],
)
def test_candidate_decoder_fails_closed(
    sqlite_engine: Engine,
    clock: FrozenClock,
    new_id: SeededUUIDs,
    evidence: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(AcceptanceError, match=message):
        use_case(sqlite_engine, clock, new_id)._candidates(evidence)


@pytest.mark.parametrize(
    "candidates",
    [
        [
            {
                "rank": 1,
                "identity_id": None,
                "similarity": 0.4,
                "members": [],
            }
        ],
        [
            {
                "rank": 1,
                "identity_id": None,
                "similarity": 0.4,
                "members": [
                    {"representation_id": str(uuid.uuid4()), "pool": "OTHER", "similarity": 0.4}
                ],
            }
        ],
        [
            {
                "rank": 1,
                "identity_id": None,
                "similarity": 0.4,
                "members": [
                    {"representation_id": str(uuid.uuid4()), "pool": "GLOBAL", "similarity": 0.3}
                ],
            }
        ],
        [
            candidate(uuid.UUID(int=1)),
            candidate(uuid.UUID(int=1), rank=2),
        ],
        [
            candidate(uuid.UUID(int=1), identity_id=uuid.UUID(int=3)),
            candidate(uuid.UUID(int=2), rank=2, identity_id=uuid.UUID(int=3)),
        ],
    ],
)
def test_candidate_decoder_rejects_invalid_bounded_snapshot(
    sqlite_engine: Engine,
    clock: FrozenClock,
    new_id: SeededUUIDs,
    candidates: list[dict[str, object]],
) -> None:
    with pytest.raises(AcceptanceError):
        use_case(sqlite_engine, clock, new_id)._candidates({"candidates": candidates})


def test_candidate_decoder_keeps_the_first_member_of_a_group(
    sqlite_engine: Engine, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    first, second = uuid.uuid4(), uuid.uuid4()
    decoded = use_case(sqlite_engine, clock, new_id)._candidates(
        {
            "candidates": [
                candidate(
                    first,
                    similarity=0.6,
                    members=[
                        {"representation_id": str(first), "pool": "GLOBAL", "similarity": 0.6},
                        {"representation_id": str(second), "pool": "RUN_LOCAL", "similarity": 0.5},
                    ],
                )
            ]
        }
    )

    assert decoded[0].representation_id == first


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda evidence: evidence | {"outcome": "CREATE_NEW"}, "contradicts"),
        (
            lambda evidence: {key: value for key, value in evidence.items() if key != "policy"},
            "schema",
        ),
        (lambda evidence: evidence | {"schema_version": 2}, "schema"),
        (lambda evidence: evidence | {"unknown": True}, "schema"),
        (lambda evidence: evidence | {"assessment_version": ""}, "metadata"),
        (
            lambda evidence: evidence | {"quality": {"detection_score": 2.0}},
            "semantic fields",
        ),
        (
            lambda evidence: evidence | {"policy": {**evidence["policy"], "margin": 0.0}},
            "incoherent policy",
        ),
        (
            lambda evidence: evidence | {"retrieval": {**evidence["retrieval"], "requested_k": 1}},
            "inconsistent retrieval",
        ),
        (lambda evidence: evidence | {"margin": 0.1}, "impossible margin"),
        (
            lambda evidence: (
                evidence
                | {
                    "candidates": [
                        candidate(uuid.UUID(int=1), similarity=0.6),
                        candidate(uuid.UUID(int=2), rank=2, similarity=0.4),
                    ],
                    "retrieval": {**evidence["retrieval"], "returned": 2},
                    "margin": 0.1,
                }
            ),
            "inconsistent margin",
        ),
    ],
)
def test_final_evidence_fails_closed_when_its_contract_is_not_canonical(
    sqlite_engine: Engine,
    db_session: Session,
    clock: FrozenClock,
    new_id: SeededUUIDs,
    change: Callable[[dict[str, object]], dict[str, object]],
    message: str,
) -> None:
    run, _observation, representation, _identity, _job = finalizing(
        db_session, clock, new_id, "ABSTAIN"
    )
    assert representation is not None
    checkpoint = db_session.get(ProcessingCheckpoint, run.current_checkpoint_id)
    assert checkpoint is not None
    decision = checkpoint.payload_json["decisions"][0]
    checkpoint.payload_json = {
        **checkpoint.payload_json,
        "decisions": [{**decision, "evidence": change(decision["evidence"])}],
    }
    db_session.commit()

    with pytest.raises(AcceptanceError, match=message):
        use_case(sqlite_engine, clock, new_id).accept(run.id)

    db_session.expire_all()
    assert db_session.get(Representation, representation.id).state == "PENDING"  # type: ignore[union-attr]


def test_final_evidence_accepts_a_bounded_snapshot_with_a_correct_margin(
    sqlite_engine: Engine, db_session: Session, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    run, _observation, _representation, _identity, _job = finalizing(
        db_session, clock, new_id, "ABSTAIN"
    )
    checkpoint = db_session.get(ProcessingCheckpoint, run.current_checkpoint_id)
    assert checkpoint is not None
    decision = checkpoint.payload_json["decisions"][0]
    evidence = {
        **decision["evidence"],
        "reason": Reason.UNCERTAIN_SIMILARITY.value,
        "candidates": [
            candidate(uuid.UUID(int=1), similarity=0.6),
            candidate(uuid.UUID(int=2), rank=2, similarity=0.4),
        ],
        "retrieval": {**decision["evidence"]["retrieval"], "returned": 2},
        "margin": 0.2,
    }

    assert (
        use_case(sqlite_engine, clock, new_id)._evidence(
            evidence, RecognitionOutcome.ABSTAIN, Reason.UNCERTAIN_SIMILARITY, None
        )
        == evidence
    )


def test_missing_run_and_wrong_lifecycle_states_are_refused(
    sqlite_engine: Engine, db_session: Session, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    accept = use_case(sqlite_engine, clock, new_id)
    with pytest.raises(AcceptanceError, match="does not exist"):
        accept.accept(uuid.uuid4())
    run, _observation, _representation, _identity, job = finalizing(
        db_session, clock, new_id, "NO_FACE"
    )
    run.state = "RUNNING"
    db_session.commit()
    with pytest.raises(AcceptanceError, match="not FINALIZING"):
        accept.accept(run.id)
    run.state = "FINALIZING"
    job.state = "QUEUED"
    db_session.commit()
    with pytest.raises(AcceptanceError, match="job is QUEUED"):
        accept.accept(run.id)


def test_first_acceptance_requires_an_active_source_and_available_original(
    sqlite_engine: Engine, db_session: Session, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    run, _observation, _representation, _identity, _job = finalizing(
        db_session, clock, new_id, "NO_FACE"
    )
    source = db_session.get(Source, run.source_id)
    assert source is not None
    source.state = "RECYCLED"
    db_session.commit()

    with pytest.raises(AcceptanceError, match="source or original"):
        use_case(sqlite_engine, clock, new_id).accept(run.id)


def test_private_output_must_be_exactly_pending_and_owned_by_its_final_checkpoint(
    sqlite_engine: Engine, db_session: Session, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    run, observation, _representation, _identity, _job = finalizing(
        db_session, clock, new_id, "ABSTAIN"
    )
    assert observation is not None
    ModelFactory(db_session, clock, new_id).observation(
        run, execution_segment_id=observation.execution_segment_id, sequence_in_run=1
    )
    db_session.flush()
    _checkpoint, decisions = use_case(sqlite_engine, clock, new_id)._final(db_session, run)

    with pytest.raises(AcceptanceError, match="exactly the private observations"):
        use_case(sqlite_engine, clock, new_id)._validate_private_output(db_session, run, decisions)


def test_identity_decision_validation_rejects_unknown_and_wrong_lifecycle(
    sqlite_engine: Engine, db_session: Session, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    run, observation, representation, _identity, _job = finalizing(
        db_session, clock, new_id, "ABSTAIN"
    )
    assert observation is not None
    assert representation is not None
    accept = use_case(sqlite_engine, clock, new_id)
    unknown = _Decision(
        observation.id,
        representation.id,
        RecognitionOutcome.MATCH_EXISTING,
        Reason.MATCHED,
        uuid.uuid4(),
        {},
    )
    representation.identity_id = unknown.identity_id
    with pytest.raises(AcceptanceError, match="does not exist"):
        accept._validate_decision_identity(db_session, run, unknown, representation)
    representation.identity_id = None
    with pytest.raises(AcceptanceError, match="does not agree"):
        accept._validate_decision_identity(db_session, run, unknown, representation)
    representation.identity_id = None
    pending = ModelFactory(db_session, clock, new_id).identity(state="PENDING")
    decision = _Decision(
        observation.id,
        representation.id,
        RecognitionOutcome.MATCH_EXISTING,
        Reason.MATCHED,
        pending.id,
        {},
    )
    representation.identity_id = pending.id
    with pytest.raises(AcceptanceError, match="must name an ACTIVE"):
        accept._validate_decision_identity(db_session, run, decision, representation)


def test_create_decision_must_name_an_identity_owned_by_its_run(
    sqlite_engine: Engine, db_session: Session, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    run, observation, representation, _identity, _job = finalizing(
        db_session, clock, new_id, "ABSTAIN"
    )
    assert observation is not None
    assert representation is not None
    identity = ModelFactory(db_session, clock, new_id).identity(state="PENDING")
    representation.identity_id = identity.id
    decision = _Decision(
        observation.id,
        representation.id,
        RecognitionOutcome.CREATE_NEW,
        Reason.NO_CANDIDATE,
        identity.id,
        {},
    )

    with pytest.raises(AcceptanceError, match="this run's pending identity"):
        use_case(sqlite_engine, clock, new_id)._validate_decision_identity(
            db_session, run, decision, representation
        )


def test_context_requires_exactly_one_processing_job(
    sqlite_engine: Engine, db_session: Session, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    run, _observation, _representation, _identity, _job = finalizing(
        db_session, clock, new_id, "NO_FACE"
    )
    ModelFactory(db_session, clock, new_id).job(
        processing_run_id=run.id, type="PROCESS_SOURCE", state="RUNNING"
    )
    db_session.flush()

    with pytest.raises(AcceptanceError, match="source or job"):
        use_case(sqlite_engine, clock, new_id)._context(db_session, run)


def test_private_representation_must_be_pending_and_match_its_observation(
    sqlite_engine: Engine, db_session: Session, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    run, _observation, representation, _identity, _job = finalizing(
        db_session, clock, new_id, "ABSTAIN"
    )
    assert representation is not None
    representation.state = "SUPERSEDED"
    _checkpoint, decisions = use_case(sqlite_engine, clock, new_id)._final(db_session, run)

    with pytest.raises(AcceptanceError, match="not the private output"):
        use_case(sqlite_engine, clock, new_id)._validate_private_output(db_session, run, decisions)


@pytest.mark.parametrize("failure", ["observation", "source", "run", "job"])
def test_acceptance_rolls_back_when_a_compare_and_set_loses(
    sqlite_engine: Engine,
    db_session: Session,
    clock: FrozenClock,
    new_id: SeededUUIDs,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    run, _observation, representation, _identity, _job = finalizing(
        db_session, clock, new_id, "ABSTAIN"
    )
    assert representation is not None
    if failure == "observation":
        monkeypatch.setattr(
            "backend.app.processing.accept_run.ObservationRepository.transition",
            lambda *_args, **_kwargs: False,
        )
        message = "observation changed"
    elif failure == "source":
        monkeypatch.setattr(
            "backend.app.processing.accept_run.SourceRepository.set_current_run",
            lambda *_args, **_kwargs: False,
        )
        message = "source changed"
    elif failure == "run":
        monkeypatch.setattr(
            "backend.app.processing.accept_run.optimistic_locked_update",
            lambda *_args, **_kwargs: 0,
        )
        message = "run changed"
    else:
        monkeypatch.setattr(
            "backend.app.processing.accept_run.JobRepository.transition",
            lambda *_args, **_kwargs: False,
        )
        message = "job changed"

    with pytest.raises(AcceptanceError, match=message):
        use_case(sqlite_engine, clock, new_id).accept(run.id)

    db_session.expire_all()
    assert db_session.get(ProcessingRun, run.id).state == "FINALIZING"  # type: ignore[union-attr]
    assert db_session.get(Representation, representation.id).state == "PENDING"  # type: ignore[union-attr]


@pytest.mark.parametrize("outcome", ["ABSTAIN", "MATCH_EXISTING"])
def test_completed_runs_revalidate_their_identity_assignment(
    sqlite_engine: Engine,
    db_session: Session,
    clock: FrozenClock,
    new_id: SeededUUIDs,
    outcome: str,
) -> None:
    run, _observation, representation, _identity, _job = finalizing(
        db_session, clock, new_id, outcome
    )
    assert representation is not None
    accept = use_case(sqlite_engine, clock, new_id)
    accept.accept(run.id)
    assert accept.accept(run.id).already_accepted is True
    representation = db_session.get(Representation, representation.id)
    assert representation is not None
    representation.identity_id = ModelFactory(db_session, clock, new_id).identity().id
    db_session.commit()

    expected = "acquired an identity" if outcome == "ABSTAIN" else "changed identity"
    with pytest.raises(AcceptanceError, match=expected):
        accept.accept(run.id)


def test_completed_run_requires_active_output_and_accepted_owners(
    sqlite_engine: Engine, db_session: Session, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    run, _observation, representation, _identity, _job = finalizing(
        db_session, clock, new_id, "ABSTAIN"
    )
    assert representation is not None
    accept = use_case(sqlite_engine, clock, new_id)
    accept.accept(run.id)
    source = db_session.get(Source, run.source_id)
    assert source is not None
    source.current_processing_run_id = None
    db_session.commit()

    with pytest.raises(AcceptanceError, match="missing its accepted owners"):
        accept.accept(run.id)

    source.current_processing_run_id = run.id
    db_session.flush()
    representation = db_session.get(Representation, representation.id, populate_existing=True)
    assert representation is not None
    representation.state = "PENDING"
    representation.ann_key = None
    db_session.commit()
    with pytest.raises(AcceptanceError, match="inconsistent accepted output"):
        accept.accept(run.id)


def test_completed_run_requires_its_original_decision_evidence(
    sqlite_engine: Engine, db_session: Session, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    run, _observation, _representation, _identity, _job = finalizing(
        db_session, clock, new_id, "ABSTAIN"
    )
    accept = use_case(sqlite_engine, clock, new_id)
    accept.accept(run.id)
    db_session.delete(db_session.scalars(select(Evidence)).one())
    db_session.commit()

    with pytest.raises(AcceptanceError, match="missing its decision evidence"):
        accept.accept(run.id)


@pytest.mark.parametrize("corruption", ["schema", "link"])
def test_completed_run_revalidates_evidence_contract(
    sqlite_engine: Engine,
    db_session: Session,
    clock: FrozenClock,
    new_id: SeededUUIDs,
    corruption: str,
) -> None:
    run, _observation, _representation, _identity, _job = finalizing(
        db_session, clock, new_id, "ABSTAIN"
    )
    accept = use_case(sqlite_engine, clock, new_id)
    accept.accept(run.id)
    if corruption == "schema":
        db_session.scalars(select(Evidence)).one().payload_schema_version = 2
        expected = "incompatible"
    else:
        db_session.scalars(select(EvidenceRepresentation)).one().role = "CANDIDATE"
        expected = "links"
    db_session.commit()

    with pytest.raises(AcceptanceError, match=expected):
        accept.accept(run.id)


@pytest.mark.parametrize("outcome", ["CREATE_NEW", "MATCH_EXISTING"])
def test_completed_identity_decision_requires_its_active_image_occurrence(
    sqlite_engine: Engine,
    db_session: Session,
    clock: FrozenClock,
    new_id: SeededUUIDs,
    outcome: str,
) -> None:
    run, _observation, _representation, _identity, _job = finalizing(
        db_session, clock, new_id, outcome
    )
    accept = use_case(sqlite_engine, clock, new_id)
    accept.accept(run.id)
    db_session.delete(db_session.scalars(select(Occurrence)).one())
    db_session.commit()

    with pytest.raises(AcceptanceError, match="missing its accepted occurrence"):
        accept.accept(run.id)


def test_completed_abstention_rejects_an_illicit_occurrence_membership(
    sqlite_engine: Engine, db_session: Session, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    run, observation, _representation, _identity, _job = finalizing(
        db_session, clock, new_id, "ABSTAIN"
    )
    assert observation is not None
    accept = use_case(sqlite_engine, clock, new_id)
    accept.accept(run.id)
    occurrence = ModelFactory(db_session, clock, new_id).occurrence(observation, state="ACTIVE")
    db_session.add(
        OccurrenceObservation(
            occurrence_id=occurrence.id,
            observation_id=observation.id,
            ordinal=0,
        )
    )
    db_session.commit()

    with pytest.raises(AcceptanceError, match="acquired an occurrence"):
        accept.accept(run.id)


def test_completed_run_requires_its_durable_add_operation(
    sqlite_engine: Engine, db_session: Session, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    run, _observation, _representation, _identity, _job = finalizing(
        db_session, clock, new_id, "ABSTAIN"
    )
    accept = use_case(sqlite_engine, clock, new_id)
    accept.accept(run.id)
    db_session.delete(db_session.scalars(select(IndexOperation)).one())
    db_session.commit()

    with pytest.raises(AcceptanceError, match="missing its ADD operation"):
        accept.accept(run.id)
