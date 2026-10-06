"""The one authoritative boundary for a processed source (persistence §30).

Perception leaves only private PENDING rows and a FINAL checkpoint.  This use case validates that
handoff and atomically makes the result visible; the derived ANN work is merely queued here and is
woken only after the transaction commits.
"""

import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from math import isclose, isfinite
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.identities.models import (
    Evidence,
    EvidenceCandidate,
    EvidenceKind,
    EvidenceRepresentationRole,
    Identity,
    IdentityState,
)
from backend.app.identities.repository import EvidenceLink, EvidenceRepository, OccurrenceRepository
from backend.app.identities.use_cases import activate_identity, assign_representation_to_identity
from backend.app.jobs.models import Job, JobState, JobType
from backend.app.jobs.repository import JobRepository
from backend.app.memory.index_operation_repository import IndexOperationRepository, NewOperation
from backend.app.memory.models import (
    IndexOperation,
    IndexOperationKind,
    Observation,
    ObservationState,
    Occurrence,
    OccurrenceKind,
    OccurrenceObservation,
    OccurrenceState,
    Representation,
    RepresentationState,
)
from backend.app.memory.repository import ObservationRepository, RepresentationRepository
from backend.app.processing.models import (
    CheckpointKind,
    CheckpointState,
    ProcessingCheckpoint,
    ProcessingConfigurationSnapshot,
    ProcessingRun,
    ProcessingRunState,
)
from backend.app.processing.repository import CheckpointRepository
from backend.app.processing.run_repository import ProcessingRunRepository
from backend.app.recognition.assessment import (
    ASSESSMENT_VERSION,
    INTERPRETATION,
    CandidateGroup,
    GroupMember,
    ObservationQuality,
    RecognitionAssessment,
)
from backend.app.recognition.reasoner import (
    EVIDENCE_SCHEMA_VERSION,
    DecisionPolicy,
    IdentityReasoner,
    Reason,
    RecognitionOutcome,
)
from backend.app.recognition.retrieval import Pool
from backend.app.sources.models import Artifact, ArtifactState, Source, SourceKind, SourceState
from backend.app.sources.repository import SourceRepository
from backend.infrastructure.db.optimistic import optimistic_locked_update
from backend.infrastructure.db.unit_of_work import UnitOfWork

FINAL_SCHEMA_VERSION = 1
_EVIDENCE_KEYS = {
    "schema_version",
    "outcome",
    "reason",
    "identity_id",
    "assessment_version",
    "interpretation",
    "representation_space_id",
    "quality",
    "retrieval",
    "candidates",
    "margin",
    "policy",
}
_CANDIDATE_KEYS = {"rank", "identity_id", "similarity", "members"}
_CANDIDATE_MEMBER_KEYS = {"representation_id", "pool", "similarity"}
_REASONS_BY_OUTCOME = {
    RecognitionOutcome.MATCH_EXISTING: {Reason.MATCHED},
    RecognitionOutcome.CREATE_NEW: {Reason.NO_CANDIDATE, Reason.NOT_SIMILAR},
    RecognitionOutcome.ABSTAIN: {
        Reason.LOW_QUALITY,
        Reason.RETRIEVAL_INCOMPLETE,
        Reason.AMBIGUOUS_CANDIDATES,
        Reason.UNRESOLVED_NEIGHBOUR,
        Reason.UNCERTAIN_SIMILARITY,
    },
}


class AcceptanceError(RuntimeError):
    """A FINAL checkpoint is absent, stale, malformed, or contradicts private output."""


@dataclass(frozen=True, slots=True)
class AcceptedProcessingRun:
    processing_run_id: uuid.UUID
    already_accepted: bool


@dataclass(frozen=True, slots=True)
class _Decision:
    observation_id: uuid.UUID
    representation_id: uuid.UUID
    outcome: RecognitionOutcome
    reason: Reason
    identity_id: uuid.UUID | None
    evidence: dict[str, Any]


class AcceptProcessingRunUseCase:
    """Accept one FINALIZING run, or validate its previously accepted result idempotently."""

    def __init__(
        self,
        uow: UnitOfWork,
        *,
        new_id: Callable[[], uuid.UUID],
        clock: Callable[[], datetime],
        wake_index: Callable[[], None] | None = None,
    ) -> None:
        self._uow = uow
        self._new_id = new_id
        self._clock = clock
        self._wake_index = wake_index

    def accept(self, processing_run_id: uuid.UUID) -> AcceptedProcessingRun:
        result = self._uow.write(lambda session: self._accept(session, processing_run_id))
        # This is intentionally after `write` returns: a crash or error here leaves SQLite
        # authoritative and the durable ADD operations are replayable by the coordinator.
        if self._wake_index is not None:
            self._wake_index()
        return result

    def _accept(self, session: Session, run_id: uuid.UUID) -> AcceptedProcessingRun:
        run = ProcessingRunRepository(session).lock(run_id)
        if run is None:
            raise AcceptanceError("processing run does not exist")
        checkpoint, decisions = self._final(session, run)
        self._configuration_snapshot(session, run)
        source, job = self._context(session, run)
        if run.state == ProcessingRunState.COMPLETED:
            self._validate_completed(session, run, source, job, decisions)
            return AcceptedProcessingRun(run.id, already_accepted=True)
        if run.state != ProcessingRunState.FINALIZING:
            raise AcceptanceError(f"processing run is {run.state}, not FINALIZING")
        if job.state != JobState.RUNNING:
            raise AcceptanceError(f"processing job is {job.state}, not RUNNING")
        self._require_source_is_acceptable(session, source)
        self._validate_private_output(session, run, decisions)
        now = self._clock()
        for decision in decisions:
            self._accept_decision(session, run, source, decision, now)
        for observation_id in self._observation_ids(decisions, checkpoint):
            if not ObservationRepository(session).transition(
                observation_id,
                from_states=(ObservationState.PENDING,),
                to_state=ObservationState.ACTIVE,
            ):
                raise AcceptanceError("an observation changed while accepting")
        if not SourceRepository(session).set_current_run(
            source.id, run.id, expected_revision=source.revision, now=now
        ):
            raise AcceptanceError("source changed while accepting")
        changed = optimistic_locked_update(
            session,
            ProcessingRun,
            run.id,
            expected_revision=run.revision,
            values={
                "state": ProcessingRunState.COMPLETED,
                "completed_at": now,
                "updated_at": now,
            },
            extra_where=(ProcessingRun.state == ProcessingRunState.FINALIZING,),
        )
        if changed != 1:
            raise AcceptanceError("processing run changed while accepting")
        if not JobRepository(session).transition(
            job.id, (JobState.RUNNING,), JobState.COMPLETED, now=now
        ):
            raise AcceptanceError("processing job changed while accepting")
        return AcceptedProcessingRun(run.id, already_accepted=False)

    def _final(
        self, session: Session, run: ProcessingRun
    ) -> tuple[ProcessingCheckpoint, tuple[_Decision, ...]]:
        checkpoint = CheckpointRepository(session).final_valid(run.id)
        if (
            checkpoint is None
            or checkpoint.id != run.current_checkpoint_id
            or checkpoint.kind != CheckpointKind.FINAL
            or checkpoint.state != CheckpointState.VALID
            or checkpoint.payload_schema_version != FINAL_SCHEMA_VERSION
        ):
            raise AcceptanceError("processing run has no current supported FINAL checkpoint")
        payload = checkpoint.payload_json
        if set(payload) != {"schema_version", "observations", "decisions"}:
            raise AcceptanceError("FINAL checkpoint has an unknown or missing field")
        if payload["schema_version"] != FINAL_SCHEMA_VERSION:
            raise AcceptanceError("FINAL checkpoint has an unsupported payload schema")
        observations = payload["observations"]
        entries = payload["decisions"]
        if not isinstance(observations, list) or not isinstance(entries, list):
            raise AcceptanceError("FINAL checkpoint observations and decisions must be lists")
        decisions = tuple(self._decision(entry) for entry in entries)
        observation_ids = tuple(self._uuid(value, "observations") for value in observations)
        if len(set(observation_ids)) != len(observation_ids):
            raise AcceptanceError("FINAL checkpoint repeats an observation")
        if {decision.observation_id for decision in decisions} != set(observation_ids):
            raise AcceptanceError("FINAL checkpoint decisions do not cover its observations")
        if len({decision.representation_id for decision in decisions}) != len(decisions):
            raise AcceptanceError("FINAL checkpoint repeats a representation")
        return checkpoint, decisions

    def _context(self, session: Session, run: ProcessingRun) -> tuple[Source, Job]:
        source = SourceRepository(session).get(run.source_id)
        jobs = list(
            session.scalars(
                select(Job).where(
                    Job.processing_run_id == run.id, Job.type == JobType.PROCESS_SOURCE
                )
            )
        )
        if source is None or len(jobs) != 1:
            raise AcceptanceError("processing source or job is no longer valid")
        return source, jobs[0]

    @staticmethod
    def _require_source_is_acceptable(session: Session, source: Source) -> None:
        artifact = session.get(Artifact, source.original_artifact_id)
        if (
            source.kind != SourceKind.IMAGE
            or source.state != SourceState.ACTIVE
            or artifact is None
            or artifact.state != ArtifactState.AVAILABLE
        ):
            raise AcceptanceError("processing source or original is no longer valid")

    def _validate_private_output(
        self, session: Session, run: ProcessingRun, decisions: Sequence[_Decision]
    ) -> None:
        observation_ids = set(self._observation_ids(decisions, None))
        pending_observations = set(
            session.scalars(
                select(Observation.id).where(
                    Observation.processing_run_id == run.id,
                    Observation.source_id == run.source_id,
                    Observation.state == ObservationState.PENDING,
                )
            )
        )
        if pending_observations != observation_ids:
            raise AcceptanceError("FINAL checkpoint does not name exactly the private observations")
        representations = list(
            session.scalars(
                select(Representation).where(Representation.processing_run_id == run.id)
            )
        )
        expected = {decision.representation_id for decision in decisions}
        if {representation.id for representation in representations} != expected:
            raise AcceptanceError(
                "FINAL checkpoint does not name exactly the private representations"
            )
        by_id = {representation.id: representation for representation in representations}
        for decision in decisions:
            representation = by_id[decision.representation_id]
            if (
                representation.state != RepresentationState.PENDING
                or representation.observation_id != decision.observation_id
                or representation.vector is None
                or decision.evidence["representation_space_id"]
                != str(representation.representation_space_id)
            ):
                raise AcceptanceError(
                    "a representation is not the private output described by FINAL"
                )
            self._validate_decision_identity(session, run, decision, representation)
            self._validate_reasoned_decision(session, run, decision, representation)

    def _validate_reasoned_decision(
        self,
        session: Session,
        run: ProcessingRun,
        decision: _Decision,
        representation: Representation,
    ) -> None:
        evidence = decision.evidence
        policy_data = evidence["policy"]
        assert isinstance(policy_data, dict)
        policy = DecisionPolicy(
            policy_data["version"],
            policy_data["min_detection_score"],
            policy_data["match_threshold"],
            policy_data["margin"],
            policy_data["new_identity_ceiling"],
        )
        snapshot = self._configuration_snapshot(session, run)
        snapshot_policy = snapshot.canonical_json.get("decision_policy")
        if snapshot_policy != {"schema_version": 1, **policy_data}:
            raise AcceptanceError(
                "FINAL checkpoint policy does not match the frozen run configuration"
            )
        observation = session.get(Observation, decision.observation_id)
        observation_quality = None if observation is None else observation.quality_json
        if (
            not isinstance(observation_quality, dict)
            or observation_quality.get("schema_version") != 1
            or observation_quality.get("detection_score") != evidence["quality"]["detection_score"]
        ):
            raise AcceptanceError("FINAL checkpoint quality does not match its private observation")
        groups: list[CandidateGroup] = []
        for candidate in evidence["candidates"]:
            assert isinstance(candidate, dict)
            identity_id = (
                None
                if candidate["identity_id"] is None
                else self._uuid(candidate["identity_id"], "candidate identity")
            )
            members: list[GroupMember] = []
            for member in candidate["members"]:
                assert isinstance(member, dict)
                member_id = self._uuid(member["representation_id"], "candidate")
                persisted = session.get(Representation, member_id)
                pool = Pool(member["pool"])
                candidate_identity = (
                    None if identity_id is None else session.get(Identity, identity_id)
                )
                if (
                    persisted is None
                    or persisted.id == representation.id
                    or persisted.representation_space_id != representation.representation_space_id
                    or persisted.identity_id != identity_id
                    or pool is Pool.GLOBAL
                    and persisted.state != RepresentationState.ACTIVE
                    or pool is Pool.GLOBAL
                    and identity_id is not None
                    and (
                        candidate_identity is None
                        or candidate_identity.state != IdentityState.ACTIVE
                    )
                    or pool is Pool.RUN_LOCAL
                    and (
                        persisted.state != RepresentationState.PENDING
                        or persisted.processing_run_id != run.id
                    )
                    or pool is Pool.RUN_LOCAL
                    and identity_id is not None
                    and (
                        candidate_identity is None
                        or (
                            candidate_identity.state != IdentityState.ACTIVE
                            and (
                                candidate_identity.state != IdentityState.PENDING
                                or candidate_identity.created_by_processing_run_id != run.id
                            )
                        )
                    )
                ):
                    raise AcceptanceError("FINAL checkpoint candidate member is not authoritative")
                members.append(GroupMember(member_id, pool, member["similarity"]))
            group = CandidateGroup(identity_id, tuple(members))
            if tuple(
                sorted(
                    members,
                    key=lambda item: (-item.similarity, item.pool, str(item.representation_id)),
                )
            ) != tuple(members):
                raise AcceptanceError("FINAL checkpoint candidate members are not best-first")
            groups.append(group)
        if tuple(
            sorted(
                groups,
                key=lambda item: (-item.best_similarity, str(item.members[0].representation_id)),
            )
        ) != tuple(groups):
            raise AcceptanceError("FINAL checkpoint candidates are not best-first")
        assessment = RecognitionAssessment(
            evidence["assessment_version"],
            evidence["interpretation"],
            self._uuid(evidence["representation_space_id"], "evidence representation space"),
            ObservationQuality(observation_quality["detection_score"]),
            evidence["retrieval"]["requested_k"],
            evidence["retrieval"]["returned"],
            evidence["retrieval"]["dropped"],
            evidence["retrieval"]["converged"],
            tuple(groups),
        )
        expected = IdentityReasoner(policy).decide(assessment)
        if (
            expected.outcome != decision.outcome
            or expected.reason != decision.reason
            or decision.outcome is RecognitionOutcome.MATCH_EXISTING
            and expected.identity_id != decision.identity_id
        ):
            raise AcceptanceError("FINAL checkpoint decision does not follow its evidence")

    @staticmethod
    def _configuration_snapshot(
        session: Session, run: ProcessingRun
    ) -> ProcessingConfigurationSnapshot:
        snapshot = session.get(ProcessingConfigurationSnapshot, run.configuration_snapshot_id)
        if (
            snapshot is None
            or snapshot.schema_version != 1
            or not isinstance(snapshot.canonical_json, dict)
            or snapshot.canonical_json.get("schema_version") != 1
        ):
            raise AcceptanceError("processing run has an unsupported configuration snapshot")
        return snapshot

    def _validate_decision_identity(
        self,
        session: Session,
        run: ProcessingRun,
        decision: _Decision,
        representation: Representation,
    ) -> None:
        if decision.outcome is RecognitionOutcome.ABSTAIN:
            if decision.identity_id is not None or representation.identity_id is not None:
                raise AcceptanceError("ABSTAIN must not name an identity")
            return
        if decision.identity_id is None or representation.identity_id != decision.identity_id:
            raise AcceptanceError("identity decision does not agree with its representation")
        identity = session.get(Identity, decision.identity_id)
        if identity is None:
            raise AcceptanceError("decision identity does not exist")
        if decision.outcome is RecognitionOutcome.CREATE_NEW:
            if (
                identity.state != IdentityState.PENDING
                or identity.created_by_processing_run_id != run.id
            ):
                raise AcceptanceError("CREATE_NEW must name this run's pending identity")
            return
        if identity.state != IdentityState.ACTIVE:
            raise AcceptanceError("MATCH_EXISTING must name an ACTIVE identity")

    def _accept_decision(
        self,
        session: Session,
        run: ProcessingRun,
        source: Source,
        decision: _Decision,
        now: datetime,
    ) -> None:
        candidates = self._candidates(decision.evidence)
        payload: dict[str, object] = {**decision.evidence}
        if decision.outcome is RecognitionOutcome.CREATE_NEW:
            assert decision.identity_id is not None
            identity = session.get(Identity, decision.identity_id)
            assert identity is not None
            activate_identity(
                session, identity.id, expected_revision=identity.revision, clock=self._clock
            )
            assign_representation_to_identity(
                session,
                decision.representation_id,
                identity.id,
                new_id=self._new_id,
                clock=self._clock,
                evidence_kind=EvidenceKind.IDENTITY_CREATED,
                source_id=source.id,
                payload=payload,
                candidates=candidates,
            )
            self._occurrence(session, run, source, identity.id, decision.observation_id, now)
            return
        if decision.outcome is RecognitionOutcome.MATCH_EXISTING:
            assert decision.identity_id is not None
            assign_representation_to_identity(
                session,
                decision.representation_id,
                decision.identity_id,
                new_id=self._new_id,
                clock=self._clock,
                evidence_kind=EvidenceKind.IDENTITY_MATCHED,
                source_id=source.id,
                payload=payload,
                candidates=candidates,
            )
            self._occurrence(
                session, run, source, decision.identity_id, decision.observation_id, now
            )
            return
        representation = session.get(Representation, decision.representation_id)
        assert representation is not None
        representation.state = RepresentationState.ACTIVE
        representation.ann_key = RepresentationRepository(session).allocate_ann_key(
            representation.representation_space_id
        )
        representation.activated_at = now
        EvidenceRepository(session).append(
            Evidence(
                id=self._new_id(),
                kind=EvidenceKind.RECOGNITION_ABSTAINED,
                processing_run_id=run.id,
                source_id=source.id,
                payload_schema_version=FINAL_SCHEMA_VERSION,
                payload_json={
                    "representation_id": str(representation.id),
                    "ann_key": representation.ann_key,
                    **payload,
                },
                created_at=now,
            ),
            representations=(EvidenceLink(representation.id, EvidenceRepresentationRole.SUBJECT),),
            candidates=candidates,
        )
        IndexOperationRepository(session).append_batch(
            (NewOperation(representation.id, representation.representation_space_id, "ADD"),),
            now=now,
            new_id=self._new_id,
        )

    def _occurrence(
        self,
        session: Session,
        run: ProcessingRun,
        source: Source,
        identity_id: uuid.UUID,
        observation_id: uuid.UUID,
        now: datetime,
    ) -> None:
        OccurrenceRepository(session).add(
            Occurrence(
                id=self._new_id(),
                source_id=source.id,
                identity_id=identity_id,
                processing_run_id=run.id,
                representative_observation_id=observation_id,
                kind=OccurrenceKind.IMAGE,
                state=OccurrenceState.ACTIVE,
                created_at=now,
                activated_at=now,
            ),
            (observation_id,),
        )

    def _validate_completed(
        self,
        session: Session,
        run: ProcessingRun,
        source: Source,
        job: Job,
        decisions: Sequence[_Decision],
    ) -> None:
        if source.current_processing_run_id != run.id or job.state != JobState.COMPLETED:
            raise AcceptanceError("completed processing run is missing its accepted owners")
        for decision in decisions:
            representation = session.get(Representation, decision.representation_id)
            observation = session.get(Observation, decision.observation_id)
            if (
                representation is None
                or observation is None
                or representation.state != RepresentationState.ACTIVE
                or observation.state != ObservationState.ACTIVE
                or representation.ann_key is None
            ):
                raise AcceptanceError("completed processing run has inconsistent accepted output")
            if decision.outcome is RecognitionOutcome.ABSTAIN:
                if representation.identity_id is not None:
                    raise AcceptanceError("accepted ABSTAIN acquired an identity")
            elif representation.identity_id != decision.identity_id:
                raise AcceptanceError("accepted representation changed identity")
            self._validate_accepted_artifacts(session, run, source, decision, representation)

    @staticmethod
    def _uuid(value: object, field: str) -> uuid.UUID:
        if not isinstance(value, str):
            raise AcceptanceError(f"FINAL checkpoint {field} id is not a string")
        try:
            return uuid.UUID(value)
        except ValueError as error:
            raise AcceptanceError(f"FINAL checkpoint {field} id is invalid") from error

    def _decision(self, value: object) -> _Decision:
        if not isinstance(value, Mapping) or set(value) != {
            "observation_id",
            "representation_id",
            "outcome",
            "reason",
            "identity_id",
            "evidence",
        }:
            raise AcceptanceError("FINAL checkpoint decision has an unknown or missing field")
        try:
            outcome = RecognitionOutcome(value["outcome"])
        except (TypeError, ValueError) as error:
            raise AcceptanceError("FINAL checkpoint decision has an invalid outcome") from error
        try:
            reason = Reason(value["reason"])
        except (TypeError, ValueError) as error:
            raise AcceptanceError("FINAL checkpoint decision has an invalid reason") from error
        if reason not in _REASONS_BY_OUTCOME[outcome]:
            raise AcceptanceError("FINAL checkpoint decision reason does not support its outcome")
        identity_id = (
            None if value["identity_id"] is None else self._uuid(value["identity_id"], "identity")
        )
        evidence = self._evidence(value["evidence"], outcome, reason, identity_id)
        return _Decision(
            self._uuid(value["observation_id"], "observation"),
            self._uuid(value["representation_id"], "representation"),
            outcome,
            reason,
            identity_id,
            evidence,
        )

    def _evidence(
        self,
        value: object,
        outcome: RecognitionOutcome,
        reason: Reason,
        identity_id: uuid.UUID | None,
    ) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise AcceptanceError("FINAL checkpoint decision evidence is not an object")
        if set(value) != _EVIDENCE_KEYS or value.get("schema_version") != EVIDENCE_SCHEMA_VERSION:
            raise AcceptanceError("FINAL checkpoint decision has an unsupported evidence schema")
        if (
            value["outcome"] != outcome.value
            or value["reason"] != reason.value
            or value["identity_id"] != (None if identity_id is None else str(identity_id))
        ):
            raise AcceptanceError("FINAL checkpoint decision evidence contradicts its decision")
        if (
            value["assessment_version"] != ASSESSMENT_VERSION
            or value["interpretation"] != INTERPRETATION
        ):
            raise AcceptanceError(
                "FINAL checkpoint decision evidence has invalid assessment metadata"
            )
        self._uuid(value["representation_space_id"], "evidence representation space")
        quality = value["quality"]
        retrieval = value["retrieval"]
        policy = value["policy"]
        if (
            not isinstance(quality, dict)
            or set(quality) != {"detection_score"}
            or not self._number(quality["detection_score"])
            or not 0.0 <= quality["detection_score"] <= 1.0
            or not isinstance(retrieval, dict)
            or set(retrieval) != {"requested_k", "returned", "dropped", "converged"}
            or not all(
                isinstance(retrieval[field], int) and retrieval[field] >= 0
                for field in ("requested_k", "returned", "dropped")
            )
            or not isinstance(retrieval["converged"], bool)
            or value["margin"] is not None
            and not self._number(value["margin"])
            or not isinstance(policy, dict)
            or set(policy)
            != {
                "version",
                "min_detection_score",
                "match_threshold",
                "margin",
                "new_identity_ceiling",
            }
            or not isinstance(policy["version"], str)
            or not all(
                self._number(policy[field])
                for field in (
                    "min_detection_score",
                    "match_threshold",
                    "margin",
                    "new_identity_ceiling",
                )
            )
        ):
            raise AcceptanceError("FINAL checkpoint decision evidence has invalid semantic fields")
        try:
            DecisionPolicy(
                policy["version"],
                policy["min_detection_score"],
                policy["match_threshold"],
                policy["margin"],
                policy["new_identity_ceiling"],
            )
        except ValueError as error:
            raise AcceptanceError(
                "FINAL checkpoint decision evidence has incoherent policy"
            ) from error
        candidates = self._candidates(value)
        if (
            retrieval["requested_k"] < 2
            or retrieval["returned"] > retrieval["requested_k"]
            or len(candidates) > retrieval["returned"]
            or sum(len(candidate["members"]) for candidate in value["candidates"])
            != retrieval["returned"]
        ):
            raise AcceptanceError("FINAL checkpoint decision evidence has inconsistent retrieval")
        margin = value["margin"]
        if len(candidates) < 2:
            if margin is not None:
                raise AcceptanceError("FINAL checkpoint decision evidence has an impossible margin")
        elif not isclose(
            margin,
            value["candidates"][0]["similarity"] - value["candidates"][1]["similarity"],
            abs_tol=1e-12,
        ):
            raise AcceptanceError("FINAL checkpoint decision evidence has an inconsistent margin")
        return value

    @staticmethod
    def _number(value: object) -> bool:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value)

    def _observation_ids(
        self, decisions: Sequence[_Decision], checkpoint: ProcessingCheckpoint | None
    ) -> tuple[uuid.UUID, ...]:
        if checkpoint is None:
            return tuple(decision.observation_id for decision in decisions)
        return tuple(
            self._uuid(value, "observation") for value in checkpoint.payload_json["observations"]
        )

    def _candidates(self, evidence: Mapping[str, Any]) -> list[EvidenceCandidate]:
        raw = evidence.get("candidates", [])
        if not isinstance(raw, list):
            raise AcceptanceError("decision candidate evidence is not a list")
        candidates: list[EvidenceCandidate] = []
        member_ids: set[uuid.UUID] = set()
        identity_ids: set[uuid.UUID] = set()
        for expected_rank, item in enumerate(raw, start=1):
            if (
                not isinstance(item, Mapping)
                or set(item) != _CANDIDATE_KEYS
                or not isinstance(item.get("rank"), int)
                or isinstance(item["rank"], bool)
                or item["rank"] != expected_rank
                or not self._number(item.get("similarity"))
                or not -1.0 <= item["similarity"] <= 1.0
            ):
                raise AcceptanceError("decision candidate evidence is malformed")
            members = item.get("members")
            if not isinstance(members, list) or not members:
                raise AcceptanceError("decision candidate evidence is malformed")
            similarities: list[float] = []
            first_representation_id: uuid.UUID | None = None
            for member in members:
                if (
                    not isinstance(member, Mapping)
                    or set(member) != _CANDIDATE_MEMBER_KEYS
                    or member.get("pool") not in {"GLOBAL", "RUN_LOCAL"}
                    or not self._number(member.get("similarity"))
                    or not -1.0 <= member["similarity"] <= 1.0
                ):
                    raise AcceptanceError("decision candidate member is malformed")
                member_id = self._uuid(member.get("representation_id"), "candidate")
                if member_id in member_ids:
                    raise AcceptanceError("decision candidate evidence repeats a representation")
                member_ids.add(member_id)
                if first_representation_id is None:
                    first_representation_id = member_id
                similarities.append(member["similarity"])
            if item["similarity"] != max(similarities):
                raise AcceptanceError("decision candidate evidence has an inconsistent similarity")
            identity = item.get("identity_id")
            identity_id = None if identity is None else self._uuid(identity, "candidate identity")
            if identity_id is not None:
                if identity_id in identity_ids:
                    raise AcceptanceError("decision candidate evidence repeats an identity")
                identity_ids.add(identity_id)
            candidates.append(
                EvidenceCandidate(
                    evidence_id=uuid.UUID(int=0),
                    rank=item["rank"],
                    representation_id=first_representation_id,
                    identity_id=identity_id,
                    raw_similarity=float(item["similarity"]),
                    calibrated_confidence=None,
                    decision="CONSIDERED",
                    details_json=dict(item),
                )
            )
        return candidates

    def _validate_accepted_artifacts(
        self,
        session: Session,
        run: ProcessingRun,
        source: Source,
        decision: _Decision,
        representation: Representation,
    ) -> None:
        kind = {
            RecognitionOutcome.CREATE_NEW: EvidenceKind.IDENTITY_CREATED,
            RecognitionOutcome.MATCH_EXISTING: EvidenceKind.IDENTITY_MATCHED,
            RecognitionOutcome.ABSTAIN: EvidenceKind.RECOGNITION_ABSTAINED,
        }[decision.outcome]
        evidence = list(
            session.scalars(
                select(Evidence).where(
                    Evidence.processing_run_id == run.id,
                    Evidence.source_id == source.id,
                    Evidence.kind == kind,
                )
            )
        )
        matching = [
            row
            for row in evidence
            if row.payload_json
            == {
                "representation_id": str(representation.id),
                "ann_key": representation.ann_key,
                **decision.evidence,
            }
            and row.subject_identity_id == decision.identity_id
        ]
        if len(matching) != 1:
            raise AcceptanceError("completed processing run is missing its decision evidence")
        evidence_row = matching[0]
        if evidence_row.payload_schema_version != EVIDENCE_SCHEMA_VERSION:
            raise AcceptanceError("completed processing run has incompatible decision evidence")
        if EvidenceRepository(session).links(evidence_row.id) != [
            EvidenceLink(representation.id, EvidenceRepresentationRole.SUBJECT)
        ]:
            raise AcceptanceError(
                "completed processing run has inconsistent decision evidence links"
            )
        expected_candidates = self._candidates(decision.evidence)
        candidates = EvidenceRepository(session).candidates(evidence_row.id)
        if len(candidates) != len(expected_candidates) or any(
            actual.rank != expected.rank
            or actual.representation_id != expected.representation_id
            or actual.identity_id != expected.identity_id
            or actual.raw_similarity != expected.raw_similarity
            or actual.calibrated_confidence != expected.calibrated_confidence
            or actual.decision != expected.decision
            or actual.details_json != expected.details_json
            for actual, expected in zip(candidates, expected_candidates, strict=True)
        ):
            raise AcceptanceError("completed processing run has inconsistent candidate evidence")
        occurrences = list(
            session.scalars(
                select(Occurrence)
                .join(OccurrenceObservation)
                .where(
                    Occurrence.processing_run_id == run.id,
                    Occurrence.source_id == source.id,
                    OccurrenceObservation.observation_id == decision.observation_id,
                )
            )
        )
        if decision.outcome is RecognitionOutcome.ABSTAIN:
            if occurrences:
                raise AcceptanceError("accepted ABSTAIN acquired an occurrence")
        elif (
            len(occurrences) != 1
            or occurrences[0].identity_id != decision.identity_id
            or occurrences[0].state != OccurrenceState.ACTIVE
            or occurrences[0].kind != OccurrenceKind.IMAGE
            or OccurrenceRepository(session).observation_ids(occurrences[0].id)
            != [decision.observation_id]
        ):
            raise AcceptanceError("completed processing run is missing its accepted occurrence")
        operations = list(
            session.scalars(
                select(IndexOperation).where(
                    IndexOperation.representation_id == representation.id,
                    IndexOperation.representation_space_id
                    == representation.representation_space_id,
                    IndexOperation.operation == IndexOperationKind.ADD,
                )
            )
        )
        if len(operations) != 1:
            raise AcceptanceError("completed processing run is missing its ADD operation")
