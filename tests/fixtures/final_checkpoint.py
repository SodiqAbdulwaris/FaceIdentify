"""Builders for a FINALIZING run with a valid FINAL checkpoint (shared by acceptance and recovery
tests). `finalizing` writes the private output the FINAL describes; nothing here runs acceptance."""

import uuid

from sqlalchemy.orm import Session

from backend.app.identities.models import Identity
from backend.app.jobs.models import Job
from backend.app.memory.models import Observation, Representation
from backend.app.processing.models import ProcessingRun
from backend.app.recognition.assessment import ASSESSMENT_VERSION
from backend.app.recognition.reasoner import Reason
from tests.factories.models import ModelFactory
from tests.fixtures.deterministic import FrozenClock, SeededUUIDs


def finalizing(
    session: Session,
    clock: FrozenClock,
    new_id: SeededUUIDs,
    outcome: str,
    *,
    snapshot_schema_version: int = 1,
    snapshot_root_schema_version: int = 1,
) -> tuple[ProcessingRun, Observation | None, Representation | None, Identity | None, Job]:
    build = ModelFactory(session, clock, new_id)
    policy = {
        "version": "test-v1",
        "min_detection_score": 0.5,
        "match_threshold": 0.8,
        "margin": 0.1,
        "new_identity_ceiling": 0.2,
    }
    snapshot = build.snapshot(
        schema_version=snapshot_schema_version,
        canonical_json={
            "schema_version": snapshot_root_schema_version,
            "decision_policy": {"schema_version": 1, **policy},
        },
    )
    run = build.run(state="FINALIZING", configuration_snapshot_id=snapshot.id)
    job = build.job(processing_run_id=run.id, type="PROCESS_SOURCE", state="RUNNING")
    if outcome == "NO_FACE":
        final = build.checkpoint(run, 0, "FINAL", "VALID")
        final.payload_json = {"schema_version": 1, "observations": [], "decisions": []}
        run.current_checkpoint_id = final.id
        session.commit()
        return run, None, None, None, job
    observation = build.observation(run)
    observation.quality_json = {"schema_version": 1, "detection_score": 0.9}
    representation = build.representation(observation)
    identity = None
    identity_id: str | None = None
    if outcome == "CREATE_NEW":
        identity = build.identity(state="PENDING", created_by_processing_run_id=run.id)
        representation.identity_id = identity.id
        identity_id = str(identity.id)
    elif outcome == "MATCH_EXISTING":
        identity = build.identity()
        representation.identity_id = identity.id
        identity_id = str(identity.id)
    reason = {
        "CREATE_NEW": Reason.NO_CANDIDATE,
        "MATCH_EXISTING": Reason.MATCHED,
        "ABSTAIN": Reason.RETRIEVAL_INCOMPLETE,
    }[outcome]
    candidates: list[dict[str, object]] = []
    returned = 0
    dropped = 1 if outcome == "ABSTAIN" else 0
    if outcome == "MATCH_EXISTING":
        assert identity is not None
        candidate_observation = build.observation()
        candidate_representation = build.representation(
            candidate_observation,
            representation_space_id=representation.representation_space_id,
            state="ACTIVE",
            identity_id=identity.id,
            ann_key=2,
            activated_at=clock(),
        )
        candidates = [
            candidate(candidate_representation.id, identity_id=identity.id, similarity=0.9)
        ]
        returned = 1
    final = build.checkpoint(run, 0, "FINAL", "VALID")
    final.payload_json = {
        "schema_version": 1,
        "observations": [str(observation.id)],
        "decisions": [
            {
                "observation_id": str(observation.id),
                "representation_id": str(representation.id),
                "outcome": outcome,
                "reason": reason.value,
                "identity_id": identity_id,
                "evidence": {
                    "schema_version": 1,
                    "outcome": outcome,
                    "reason": reason.value,
                    "identity_id": identity_id,
                    "assessment_version": ASSESSMENT_VERSION,
                    "interpretation": "COSINE_UNCALIBRATED",
                    "representation_space_id": str(representation.representation_space_id),
                    "quality": {"detection_score": 0.9},
                    "retrieval": {
                        "requested_k": 2,
                        "returned": returned,
                        "dropped": dropped,
                        "converged": True,
                    },
                    "candidates": candidates,
                    "margin": None,
                    "policy": policy,
                },
            }
        ],
    }
    run.current_checkpoint_id = final.id
    session.commit()
    return run, observation, representation, identity, job


def candidate(
    representation_id: uuid.UUID,
    *,
    rank: int = 1,
    identity_id: uuid.UUID | None = None,
    similarity: float = 0.4,
    members: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "rank": rank,
        "identity_id": None if identity_id is None else str(identity_id),
        "similarity": similarity,
        "members": members
        or [
            {
                "representation_id": str(representation_id),
                "pool": "GLOBAL",
                "similarity": similarity,
            }
        ],
    }
