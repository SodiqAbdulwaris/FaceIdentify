"""A video's tracks become occurrences over time under the track rule (M6 step 6; D7; TST-061,
TST-070).

The real pipeline: an image enrols the red "person" first (the empty library creates an identity),
then a clip of painted squares is processed and accepted. The red track's kept faces all match
that identity, so the track becomes one TRACK occurrence spanning its time; the green track's faces
would each start a new identity, which a video never does, so they all abstain as TRACK_UNSETTLED.
"""

import uuid
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select

from backend.app.identities.models import Evidence, EvidenceKind, Identity
from backend.app.memory.models import (
    Occurrence,
    OccurrenceKind,
    OccurrenceObservation,
    Representation,
    RepresentationState,
)
from backend.app.processing.accept_run import AcceptanceError
from backend.app.processing.models import ProcessingCheckpoint, ProcessingRun
from tests.fixtures.pipeline import Pipeline
from tests.fixtures.video_pipeline import (
    import_video,
    painted_clip,
    video_executor,
    video_perception,
)


def enrol_red(pipeline: Pipeline) -> uuid.UUID:
    """An image whose one face is the red vector: the first face makes the identity."""
    run_id = pipeline.execute(pipeline.import_image())
    pipeline.accept(run_id, apply_index=True)
    with pipeline.lib.session_factory() as session:
        (identity,) = session.scalars(select(Identity)).all()
        return identity.id


def process_video(pipeline: Pipeline, tmp_path: Path) -> uuid.UUID:
    source_id = import_video(pipeline, painted_clip(tmp_path / "squares.mp4"))
    video_perception(pipeline)
    pipeline.enqueue(source_id)
    started = pipeline.scheduler().claim_source_job("worker")
    assert started is not None
    return video_executor(pipeline).execute(started).processing_run_id


@pytest.fixture
def red(pipeline: Pipeline) -> uuid.UUID:
    return enrol_red(pipeline)


def test_a_settled_track_is_one_occurrence_over_its_time(
    pipeline: Pipeline, red: uuid.UUID, tmp_path: Path
) -> None:
    run_id = process_video(pipeline, tmp_path)

    pipeline.accept(run_id, apply_index=True)

    with pipeline.lib.session_factory() as session:
        (occurrence,) = session.scalars(
            select(Occurrence).where(Occurrence.processing_run_id == run_id)
        ).all()
        assert (occurrence.identity_id, occurrence.kind) == (red, OccurrenceKind.TRACK)
        assert (occurrence.start_timestamp_ms, occurrence.end_timestamp_ms) == (0, 2520)
        assert (occurrence.start_frame, occurrence.end_frame) == (0, 63)
        members = session.scalars(
            select(OccurrenceObservation.observation_id).where(
                OccurrenceObservation.occurrence_id == occurrence.id
            )
        ).all()
        assert len(members) >= 2  # several kept faces support the one appearance
        reds = session.scalars(
            select(Representation).where(
                Representation.processing_run_id == run_id, Representation.identity_id == red
            )
        ).all()
        assert {r.observation_id for r in reds} == set(members)
        assert session.scalars(select(Identity)).all()[0].id == red  # no identity was created
        assert len(session.scalars(select(Identity)).all()) == 1


def test_an_unsettled_track_abstains_with_each_face_s_own_proposal(
    pipeline: Pipeline, red: uuid.UUID, tmp_path: Path
) -> None:
    run_id = process_video(pipeline, tmp_path)

    pipeline.accept(run_id, apply_index=True)

    with pipeline.lib.session_factory() as session:
        abstained = session.scalars(
            select(Evidence).where(
                Evidence.processing_run_id == run_id,
                Evidence.kind == EvidenceKind.RECOGNITION_ABSTAINED,
            )
        ).all()
        assert abstained  # the green track's faces
        for row in abstained:
            assert row.payload_json["reason"] == "TRACK_UNSETTLED"
            assert row.payload_json["proposal"]["outcome"] == "CREATE_NEW"
            representation = session.get(
                Representation, uuid.UUID(row.payload_json["representation_id"])
            )
            assert representation is not None
            assert representation.identity_id is None
            assert representation.state == RepresentationState.ACTIVE  # findable, for review


def test_accepting_again_validates_the_track_occurrence(
    pipeline: Pipeline, red: uuid.UUID, tmp_path: Path
) -> None:
    run_id = process_video(pipeline, tmp_path)
    pipeline.accept(run_id, apply_index=True)

    pipeline.accept(run_id, apply_index=True)  # idempotent: the stored result is validated

    with pipeline.lib.session_factory() as session:
        occurrence = session.scalars(
            select(Occurrence).where(Occurrence.processing_run_id == run_id)
        ).one()
        session.delete(
            session.scalars(
                select(OccurrenceObservation).where(
                    OccurrenceObservation.occurrence_id == occurrence.id
                )
            ).first()
        )
        session.commit()
    with pytest.raises(AcceptanceError, match="missing its accepted occurrence"):
        pipeline.accept(run_id, apply_index=False)


def final_of(pipeline: Pipeline, run_id: uuid.UUID) -> dict[str, Any]:
    with pipeline.lib.session_factory() as session:
        run = session.get(ProcessingRun, run_id)
        assert run is not None
        checkpoint = session.get(ProcessingCheckpoint, run.current_checkpoint_id)
        assert checkpoint is not None
        return dict(checkpoint.payload_json)


def rewrite_final(pipeline: Pipeline, run_id: uuid.UUID, payload: dict[str, Any]) -> None:
    with pipeline.lib.session_factory() as session:
        run = session.get(ProcessingRun, run_id)
        assert run is not None
        checkpoint = session.get(ProcessingCheckpoint, run.current_checkpoint_id)
        assert checkpoint is not None
        checkpoint.payload_json = payload
        session.commit()


def unsettle_red(payload: dict[str, Any]) -> None:
    """Claim the red track was unsettled although its faces all matched."""
    red_track = payload["tracks"][0]["observations"]
    for decision in payload["decisions"]:
        if decision["observation_id"] in red_track:
            proposal = {k: decision[k] for k in ("outcome", "reason", "identity_id")}
            decision.update(outcome="ABSTAIN", reason="TRACK_UNSETTLED", identity_id=None)
            decision["evidence"].update(
                outcome="ABSTAIN", reason="TRACK_UNSETTLED", identity_id=None, proposal=proposal
            )


@pytest.mark.parametrize(
    ("tamper", "message"),
    [
        (lambda p: p.pop("tracks"), "tracks do not fit the source"),
        (lambda p: p.update(tracks={}), "tracks must be a list"),
        (lambda p: p["tracks"][0].pop("start_ms"), "unknown or missing field"),
        (lambda p: p["tracks"][0].update(start_ms=10**9), "invalid span"),
        (lambda p: p["tracks"][0].update(observations=[]), "invalid span"),
        (lambda p: p["tracks"].pop(), "hold each observation once"),
        (
            lambda p: p["decisions"][-1]["evidence"]["proposal"].update(reason="TRACK_UNSETTLED"),
            "proposal reason does not fit",
        ),
        (
            lambda p: p["decisions"][-1]["evidence"]["proposal"].update(outcome="MAYBE"),
            "proposal is not a decision",
        ),
        (
            lambda p: p["decisions"][-1]["evidence"].update(proposal=[]),
            "proposal has an unknown or missing field",
        ),
        (
            lambda p: p["decisions"][-1]["evidence"]["proposal"].update(
                outcome="MATCH_EXISTING", reason="MATCHED", identity_id=str(uuid.uuid4())
            ),
            "does not follow its evidence",
        ),
    ],
)
def test_a_final_that_breaks_the_track_rule_is_refused(
    pipeline: Pipeline, red: uuid.UUID, tmp_path: Path, tamper: Any, message: str
) -> None:
    run_id = process_video(pipeline, tmp_path)
    payload = final_of(pipeline, run_id)
    assert payload["decisions"][-1]["reason"] == "TRACK_UNSETTLED"  # (the green track's last face)
    tamper(payload)
    rewrite_final(pipeline, run_id, payload)

    with pytest.raises(AcceptanceError, match=message):
        pipeline.accept(run_id, apply_index=False)


def test_an_image_face_cannot_be_left_unsettled(pipeline: Pipeline, red: uuid.UUID) -> None:
    run_id = pipeline.execute(pipeline.import_image())
    payload = final_of(pipeline, run_id)
    decision = payload["decisions"][0]
    proposal = {k: decision[k] for k in ("outcome", "reason", "identity_id")}
    decision.update(outcome="ABSTAIN", reason="TRACK_UNSETTLED", identity_id=None)
    decision["evidence"].update(
        outcome="ABSTAIN", reason="TRACK_UNSETTLED", identity_id=None, proposal=proposal
    )
    rewrite_final(pipeline, run_id, payload)
    with pipeline.lib.session_factory() as session:
        for representation in session.scalars(
            select(Representation).where(Representation.processing_run_id == run_id)
        ):
            representation.identity_id = None
        session.commit()

    with pytest.raises(AcceptanceError, match="only a video track"):
        pipeline.accept(run_id, apply_index=False)


def test_a_track_whose_faces_all_match_cannot_be_left_unsettled(
    pipeline: Pipeline, red: uuid.UUID, tmp_path: Path
) -> None:
    run_id = process_video(pipeline, tmp_path)
    payload = final_of(pipeline, run_id)
    unsettle_red(payload)
    rewrite_final(pipeline, run_id, payload)
    with pipeline.lib.session_factory() as session:  # (as an abstention would leave them)
        for representation in session.scalars(
            select(Representation).where(Representation.processing_run_id == run_id)
        ):
            representation.identity_id = None
        session.commit()

    with pytest.raises(AcceptanceError, match="does not follow the track rule"):
        pipeline.accept(run_id, apply_index=False)
