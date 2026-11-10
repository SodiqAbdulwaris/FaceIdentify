"""The one authoritative boundary for a processed source (persistence §30).

Perception leaves only private PENDING rows and a FINAL checkpoint.  This use case validates that
handoff and atomically makes the result visible; the derived ANN work is merely queued here and is
woken only after the transaction commits.

A reprocess run (one with `supersedes_run_id`) is activated by the same transaction (persistence
12.1 item 5): it also checks that the generation it replaces is still the Source's current one,
supersedes that generation, carries human decisions over through the face correspondence of
identity model 60.1, records what needs review, and keeps a forgotten or erased face suppressed
(`supersession.py`). Exactly one generation is authoritative before and after the commit.

A video run's FINAL also names its tracks (M6 step 6). Each kept face is validated against its own
evidence as an image's is; then the track rule (D7, `agreed_identity`) is checked on what that
evidence decides: a track whose faces all match the same identity keeps those matches, and any
other track's faces must all abstain as `TRACK_UNSETTLED`. A settled track becomes ONE `TRACK`
occurrence over the time it spans, its matched faces its members; an unsettled one has none.
"""

import uuid
from collections.abc import Callable, Collection, Mapping, Sequence
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
from backend.app.identities.repository import (
    EvidenceLink,
    EvidenceRepository,
    IdentityRepository,
    OccurrenceRepository,
)
from backend.app.identities.use_cases import (
    activate_identity,
    assign_representation_to_identity,
    touch_identity,
)
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
from backend.app.processing.correspondence import MIN_COSINE, MIN_IOU, Face, geometric_pairs
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
from backend.app.processing.supersession import (
    CARRIED_KEYS,
    PAYLOAD_SCHEMA_VERSION,
    RULE,
    CarriedDecision,
    SupersessionPlan,
    box_of,
    carried_evidence,
    carried_payload,
    erased_faces,
    plan_supersession,
    record_reviews,
    supersede_previous,
)
from backend.app.processing.video_chunks import agreed_identity
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
    RecognitionDecision,
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
        Reason.TRACK_UNSETTLED,
    },
}
_TRACK_KEYS = {"track", "observations", "start_ms", "end_ms", "start_frame", "end_frame"}


class AcceptanceError(RuntimeError):
    """A FINAL checkpoint is absent, stale, malformed, or contradicts private output."""


@dataclass(frozen=True, slots=True)
class AcceptedProcessingRun:
    processing_run_id: uuid.UUID
    already_accepted: bool
    # New representations suppressed as a forgotten or erased face again (reprocessing): `ERASING`,
    # handed to the eraser after the commit.
    erasing: tuple[uuid.UUID, ...] = ()


@dataclass(frozen=True, slots=True)
class _Decision:
    observation_id: uuid.UUID
    representation_id: uuid.UUID
    outcome: RecognitionOutcome
    reason: Reason
    identity_id: uuid.UUID | None
    evidence: dict[str, Any]


@dataclass(frozen=True, slots=True)
class _Track:
    observations: tuple[uuid.UUID, ...]
    start_ms: int
    end_ms: int
    start_frame: int
    end_frame: int


class AcceptProcessingRunUseCase:
    """Accept one FINALIZING run, or validate its previously accepted result idempotently."""

    def __init__(
        self,
        uow: UnitOfWork,
        *,
        new_id: Callable[[], uuid.UUID],
        clock: Callable[[], datetime],
        wake_index: Callable[[], None] | None = None,
        erase: Callable[[Sequence[uuid.UUID]], object] | None = None,
    ) -> None:
        self._uow = uow
        self._new_id = new_id
        self._clock = clock
        self._wake_index = wake_index
        self._erase = erase

    def accept(self, processing_run_id: uuid.UUID) -> AcceptedProcessingRun:
        result = self._uow.write(lambda session: self._accept(session, processing_run_id))
        # This is intentionally after `write` returns: a crash or error here leaves SQLite
        # authoritative and the durable ADD operations are replayable by the coordinator; an
        # `ERASING` representation left behind is finished by the eraser at the next start.
        if self._wake_index is not None:
            self._wake_index()
        if result.erasing and self._erase is not None:
            self._erase(result.erasing)
        return result

    def _accept(self, session: Session, run_id: uuid.UUID) -> AcceptedProcessingRun:
        run = ProcessingRunRepository(session).lock(run_id)
        if run is None:
            raise AcceptanceError("processing run does not exist")
        checkpoint, decisions, tracks = self._final(session, run)
        self._configuration_snapshot(session, run)
        source, job = self._context(session, run)
        if (source.kind == SourceKind.VIDEO) != (tracks is not None):
            raise AcceptanceError("FINAL checkpoint tracks do not fit the source")
        if run.state == ProcessingRunState.COMPLETED:
            self._validate_completed(session, run, source, job, decisions, tracks)
            return AcceptedProcessingRun(run.id, already_accepted=True)
        if run.state != ProcessingRunState.FINALIZING:
            raise AcceptanceError(f"processing run is {run.state}, not FINALIZING")
        if job.state != JobState.RUNNING:
            raise AcceptanceError(f"processing job is {job.state}, not RUNNING")
        self._require_source_is_acceptable(session, source)
        self._require_generation(session, run, source)
        self._validate_private_output(session, run, decisions, tracks)
        plan = self._plan(session, run, decisions)
        now = self._clock()
        if run.supersedes_run_id is not None:
            supersede_previous(session, run, now=now, new_id=self._new_id)
        suppressed_observations: set[uuid.UUID] = set()
        for decision in decisions:
            if decision.representation_id in plan.suppressed:
                self._suppress(session, decision)
                suppressed_observations.add(decision.observation_id)
            elif decision.representation_id in plan.carried:
                carried = plan.carried[decision.representation_id]
                self._carry(session, run, source, decision, carried, now, occurrence=tracks is None)
            else:
                self._accept_decision(
                    session, run, source, decision, now, occurrence=tracks is None
                )
        placed = {
            d.observation_id: plan.carried[d.representation_id].identity_id
            for d in decisions
            if d.representation_id in plan.carried
        } | _matched(decisions, exclude=plan.suppressed | set(plan.carried))
        for track, identity_id, members in _settled_tracks(tracks, placed):
            self._track_occurrence(session, run, source, identity_id, track, members, now)
        self._dispose_pending_identities(session, decisions, plan, now)
        record_reviews(session, run, plan.reviews, now=now, new_id=self._new_id)
        for observation_id in self._observation_ids(decisions, checkpoint):
            if observation_id in suppressed_observations:
                continue
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
        return AcceptedProcessingRun(
            run.id, already_accepted=False, erasing=tuple(sorted(plan.suppressed))
        )

    @staticmethod
    def _require_generation(session: Session, run: ProcessingRun, source: Source) -> None:
        """A first run may only become a Source's first generation; a reprocess run may only
        replace the generation it was started from, and only while that is still current (the
        compare-and-swap of persistence 12.1 item 5a). Anything else would leave two generations
        active, so it is refused."""
        if run.supersedes_run_id is None:
            if source.current_processing_run_id is not None:
                raise AcceptanceError("the source already has an accepted generation")
            return
        previous = session.get(ProcessingRun, run.supersedes_run_id)
        if (
            source.current_processing_run_id != run.supersedes_run_id
            or previous is None
            or previous.state != ProcessingRunState.COMPLETED
        ):
            raise AcceptanceError("the generation this run replaces is no longer current")

    def _plan(
        self, session: Session, run: ProcessingRun, decisions: Sequence[_Decision]
    ) -> SupersessionPlan:
        if run.supersedes_run_id is None:
            return SupersessionPlan()
        return plan_supersession(
            session,
            run,
            space_id=self._frozen_space(session, run),
            representation_ids=[decision.representation_id for decision in decisions],
        )

    def _frozen_space(self, session: Session, run: ProcessingRun) -> uuid.UUID:
        space = self._configuration_snapshot(session, run).canonical_json.get(
            "representation_space"
        )
        if not isinstance(space, dict):
            raise AcceptanceError("the frozen configuration names no representation space")
        return self._uuid(space.get("id"), "frozen representation space")

    @staticmethod
    def _suppress(session: Session, decision: _Decision) -> None:
        """A new face that is a forgotten or erased face again: never activated (persistence 12.1
        item 9a). Its observation is `REJECTED` and its representation `ERASING`, holding no key and
        no identity, so it has no index work and the eraser clears its vector."""
        representation = session.get(Representation, decision.representation_id)
        assert representation is not None  # validated as this run's private output
        representation.state = RepresentationState.ERASING
        representation.identity_id = None
        rejected = ObservationRepository(session).transition(
            decision.observation_id,
            from_states=(ObservationState.PENDING,),
            to_state=ObservationState.REJECTED,
        )
        assert rejected  # (validated PENDING in this same transaction)

    def _carry(
        self,
        session: Session,
        run: ProcessingRun,
        source: Source,
        decision: _Decision,
        carried: CarriedDecision,
        now: datetime,
        *,
        occurrence: bool = True,
    ) -> None:
        """The new face takes the previous face's human decision instead of its own recognition
        result (identity model 60.1): it joins that identity, with its own occurrence, index entry
        and `REPROCESS_DECISION_CARRIED_OVER` evidence."""
        identity = session.get(Identity, carried.identity_id)
        if identity is None or identity.state != IdentityState.ACTIVE:
            raise AcceptanceError("a carried-over identity is no longer ACTIVE")
        representation = session.get(Representation, decision.representation_id)
        assert representation is not None  # validated as this run's private output
        representation.state = RepresentationState.ACTIVE
        representation.identity_id = identity.id
        representation.ann_key = RepresentationRepository(session).allocate_ann_key(
            representation.representation_space_id
        )
        representation.activated_at = now
        touch_identity(session, identity, now)
        EvidenceRepository(session).append(
            Evidence(
                id=self._new_id(),
                kind=EvidenceKind.REPROCESS_DECISION_CARRIED_OVER,
                processing_run_id=run.id,
                source_id=source.id,
                subject_identity_id=identity.id,
                payload_schema_version=PAYLOAD_SCHEMA_VERSION,
                payload_json=carried_payload(run, representation.id, carried),
                created_at=now,
            ),
            representations=(
                EvidenceLink(representation.id, EvidenceRepresentationRole.SUBJECT),
                EvidenceLink(
                    carried.previous_representation_id, EvidenceRepresentationRole.SUPPORTING
                ),
            ),
        )
        IndexOperationRepository(session).append_batch(
            (NewOperation(representation.id, representation.representation_space_id, "ADD"),),
            now=now,
            new_id=self._new_id,
        )
        if occurrence:  # (a video face joins its track's occurrence instead)
            self._occurrence(session, run, source, identity.id, decision.observation_id, now)

    @staticmethod
    def _dispose_pending_identities(
        session: Session, decisions: Sequence[_Decision], plan: SupersessionPlan, now: datetime
    ) -> None:
        """A `PENDING` identity that a carried or suppressed face's `CREATE_NEW` made during
        execution is `DELETED`, unless a face accepted on its own decision still names it (identity
        model 60.1): no identity survives for a face that did not become one."""
        replaced = plan.suppressed | plan.carried.keys()
        used = {
            decision.identity_id
            for decision in decisions
            if decision.representation_id not in replaced
        }
        for decision in decisions:
            if (
                decision.representation_id not in replaced
                or decision.outcome is not RecognitionOutcome.CREATE_NEW
                or decision.identity_id in used
            ):
                continue
            assert decision.identity_id is not None  # (validated: CREATE_NEW names one)
            identity = session.get(Identity, decision.identity_id)
            assert identity is not None  # (validated)
            deleted = IdentityRepository(session).transition(
                identity.id,
                expected_revision=identity.revision,
                from_states=(IdentityState.PENDING,),
                to_state=IdentityState.DELETED,
                now=now,
            )
            assert deleted  # (validated PENDING, and read in this same transaction)

    def _final(
        self, session: Session, run: ProcessingRun
    ) -> tuple[ProcessingCheckpoint, tuple[_Decision, ...], tuple[_Track, ...] | None]:
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
        if set(payload) - {"tracks"} != {"schema_version", "observations", "decisions"}:
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
        tracks = None if "tracks" not in payload else self._tracks(payload["tracks"])
        if tracks is not None and sorted(o for t in tracks for o in t.observations) != sorted(
            observation_ids
        ):
            raise AcceptanceError("FINAL checkpoint tracks do not hold each observation once")
        return checkpoint, decisions, tracks

    def _tracks(self, value: object) -> tuple[_Track, ...]:
        if not isinstance(value, list):
            raise AcceptanceError("FINAL checkpoint tracks must be a list")
        tracks = []
        for entry in value:
            if not isinstance(entry, dict) or set(entry) != _TRACK_KEYS:
                raise AcceptanceError("FINAL checkpoint track has an unknown or missing field")
            times = [entry[k] for k in ("start_ms", "end_ms", "start_frame", "end_frame")]
            if (
                not all(type(t) is int and t >= 0 for t in times)
                or times[0] > times[1]
                or times[2] > times[3]
                or not isinstance(entry["observations"], list)
                or not entry["observations"]
            ):
                raise AcceptanceError("FINAL checkpoint track has an invalid span")
            observations = tuple(self._uuid(o, "track observation") for o in entry["observations"])
            tracks.append(_Track(observations, *times))
        return tuple(tracks)

    def _context(self, session: Session, run: ProcessingRun) -> tuple[Source, Job]:
        source = SourceRepository(session).get(run.source_id)
        job_type = (
            JobType.PROCESS_SOURCE if run.supersedes_run_id is None else JobType.REPROCESS_SOURCE
        )
        job = JobRepository(session).current_for_run(run.id)  # (a retried video run has two)
        if source is None or job is None or job.type != job_type:
            raise AcceptanceError("processing source or job is no longer valid")
        return source, job

    @staticmethod
    def _require_source_is_acceptable(session: Session, source: Source) -> None:
        artifact = session.get(Artifact, source.original_artifact_id)
        if (
            source.kind not in (SourceKind.IMAGE, SourceKind.VIDEO)
            or source.state != SourceState.ACTIVE
            or artifact is None
            or artifact.state != ArtifactState.AVAILABLE
        ):
            raise AcceptanceError("processing source or original is no longer valid")

    def _validate_private_output(
        self,
        session: Session,
        run: ProcessingRun,
        decisions: Sequence[_Decision],
        tracks: tuple[_Track, ...] | None,
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
        proposals: dict[uuid.UUID, RecognitionDecision] = {}
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
            proposals[decision.observation_id] = self._validate_reasoned_decision(
                session, run, decision, representation
            )
        _validate_track_rule(
            decisions,
            {o: (p.outcome, p.identity_id) for o, p in proposals.items()},
            tracks,
        )

    def _validate_reasoned_decision(
        self,
        session: Session,
        run: ProcessingRun,
        decision: _Decision,
        representation: Representation,
    ) -> RecognitionDecision:
        """What the face's own evidence decides; the decision must be it, or (a face of an
        unsettled video track) an abstention whose recorded proposal is it."""
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
        claimed = (
            (decision.outcome, decision.reason, decision.identity_id)
            if decision.reason is not Reason.TRACK_UNSETTLED
            else (
                RecognitionOutcome(evidence["proposal"]["outcome"]),
                Reason(evidence["proposal"]["reason"]),
                None
                if evidence["proposal"]["identity_id"] is None
                else self._uuid(evidence["proposal"]["identity_id"], "proposal identity"),
            )
        )
        if (
            expected.outcome != claimed[0]
            or expected.reason != claimed[1]
            or claimed[0] is RecognitionOutcome.MATCH_EXISTING
            and expected.identity_id != claimed[2]
        ):
            raise AcceptanceError("FINAL checkpoint decision does not follow its evidence")
        return expected

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
        *,
        occurrence: bool = True,
    ) -> None:
        """`occurrence` False: a video face; its occurrence is its track's (`_track_occurrence`)."""
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
            if occurrence:
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
        observation = session.get(Observation, observation_id)
        moment = None if observation is None else observation.timestamp_ms
        # (a video face on its own, as a carried-over human decision is: the moment it is seen)
        frame = None if observation is None else observation.frame_index
        OccurrenceRepository(session).add(
            Occurrence(
                id=self._new_id(),
                source_id=source.id,
                identity_id=identity_id,
                processing_run_id=run.id,
                representative_observation_id=observation_id,
                kind=OccurrenceKind.IMAGE if moment is None else OccurrenceKind.TRACK,
                state=OccurrenceState.ACTIVE,
                start_frame=frame,
                end_frame=frame,
                start_timestamp_ms=moment,
                end_timestamp_ms=moment,
                created_at=now,
                activated_at=now,
            ),
            (observation_id,),
        )

    def _track_occurrence(
        self,
        session: Session,
        run: ProcessingRun,
        source: Source,
        identity_id: uuid.UUID,
        track: _Track,
        members: tuple[uuid.UUID, ...],
        now: datetime,
    ) -> None:
        OccurrenceRepository(session).add(
            Occurrence(
                id=self._new_id(),
                source_id=source.id,
                identity_id=identity_id,
                processing_run_id=run.id,
                representative_observation_id=members[0],
                kind=OccurrenceKind.TRACK,
                state=OccurrenceState.ACTIVE,
                start_frame=track.start_frame,
                end_frame=track.end_frame,
                start_timestamp_ms=track.start_ms,
                end_timestamp_ms=track.end_ms,
                created_at=now,
                activated_at=now,
            ),
            members,
        )

    def _validate_completed(
        self,
        session: Session,
        run: ProcessingRun,
        source: Source,
        job: Job,
        decisions: Sequence[_Decision],
        tracks: tuple[_Track, ...] | None,
    ) -> None:
        if source.current_processing_run_id != run.id or job.state != JobState.COMPLETED:
            raise AcceptanceError("completed processing run is missing its accepted owners")
        carried = {} if run.supersedes_run_id is None else carried_evidence(session, run.id)
        if set(carried) - {str(decision.representation_id) for decision in decisions}:
            raise AcceptanceError("completed processing run has carry-over evidence for no face")
        suppressible = self._suppressible(session, run, decisions)
        # The track rule again, on what was recorded (each face's decision, or its recorded proposal
        # when it was left unsettled), so a changed FINAL cannot pass as the result accepted.
        _validate_track_rule(decisions, _recorded_proposals(decisions), tracks)
        carried_to = {
            uuid.UUID(named): rows[0].subject_identity_id
            for named, rows in carried.items()
            if rows and rows[0].subject_identity_id is not None
        }
        placed = {
            d.observation_id: carried_to[d.representation_id]
            for d in decisions
            if d.representation_id in carried_to
        } | _matched(decisions, exclude=set(carried_to))
        settled = {
            observation: (track, members)
            for track, _identity, members in _settled_tracks(tracks, placed)
            for observation in members
        }
        for decision in decisions:
            representation = session.get(Representation, decision.representation_id)
            observation = session.get(Observation, decision.observation_id)
            if str(decision.representation_id) in carried:
                self._validate_carried(
                    session,
                    run,
                    decision,
                    representation,
                    observation,
                    carried[str(decision.representation_id)],
                )
                continue
            if observation is not None and observation.state == ObservationState.REJECTED:
                self._validate_suppressed(session, decision, representation, suppressible)
                continue
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
            self._validate_accepted_artifacts(
                session, run, source, decision, representation, settled.get(decision.observation_id)
            )

    @staticmethod
    def _suppressible(
        session: Session, run: ProcessingRun, decisions: Sequence[_Decision]
    ) -> set[uuid.UUID]:
        """The run's representations whose face corresponds geometrically to an erased face of the
        generation it replaced: the only ones that may have been suppressed."""
        if run.supersedes_run_id is None:
            return set()
        observations = {
            observation.id: observation
            for observation in session.scalars(
                select(Observation).where(
                    Observation.id.in_([decision.observation_id for decision in decisions])
                )
            )
        }
        found = [d for d in decisions if d.observation_id in observations]  # (a missing one is
        # refused by the caller's loop)
        current = [
            Face(
                d.representation_id,
                box_of(observations[d.observation_id]),
                time_ms=observations[d.observation_id].timestamp_ms,
            )
            for d in found
        ]
        return set(geometric_pairs(erased_faces(session, run.supersedes_run_id), current))

    @staticmethod
    def _validate_suppressed(
        session: Session,
        decision: _Decision,
        representation: Representation | None,
        suppressible: set[uuid.UUID],
    ) -> None:
        """The accepted shape of a suppressed face (persistence 12.1 item 9a): observation
        `REJECTED`, representation `ERASING` or `ERASED` with no key and no identity, no occurrence,
        and a geometric correspondent among the replaced generation's erased faces."""
        occurrence = session.scalar(
            select(OccurrenceObservation.occurrence_id)
            .where(OccurrenceObservation.observation_id == decision.observation_id)
            .limit(1)
        )
        if (
            representation is None
            or decision.representation_id not in suppressible
            or representation.state not in (RepresentationState.ERASING, RepresentationState.ERASED)
            or representation.ann_key is not None
            or representation.identity_id is not None
            or occurrence is not None
        ):
            raise AcceptanceError("completed processing run has an unexplained rejected face")

    @staticmethod
    def _validate_carried(
        session: Session,
        run: ProcessingRun,
        decision: _Decision,
        representation: Representation | None,
        observation: Observation | None,
        rows: Sequence[Evidence],
    ) -> None:
        """A carried face: `ACTIVE` under the carried identity, with exactly one
        `REPROCESS_DECISION_CARRIED_OVER` row whose payload names this face, this run, the run it
        replaced, the identity, the measured overlap and similarity over the rule's thresholds
        and the rule, and whose links are exactly this face (`SUBJECT`) and the replaced
        generation's face (`SUPPORTING`); and its occurrence and its `ADD` operation."""
        if len(rows) != 1 or representation is None or representation.identity_id is None:
            raise AcceptanceError("completed processing run has an inconsistent carried face")
        evidence = rows[0]
        payload = evidence.payload_json
        links = EvidenceRepository(session).links(evidence.id)
        previous = (
            None if len(links) != 2 else session.get(Representation, links[1].representation_id)
        )
        identity_id = representation.identity_id
        occurrences = list(
            session.scalars(
                select(Occurrence)
                .join(OccurrenceObservation)
                .where(
                    Occurrence.processing_run_id == run.id,
                    OccurrenceObservation.observation_id == decision.observation_id,
                )
            )
        )
        operations = session.scalars(
            select(IndexOperation.id).where(
                IndexOperation.representation_id == decision.representation_id,
                IndexOperation.operation == IndexOperationKind.ADD,
            )
        ).all()
        if (
            representation is None
            or observation is None
            or representation.state != RepresentationState.ACTIVE
            or observation.state != ObservationState.ACTIVE
            or representation.ann_key is None
            or evidence.subject_identity_id != identity_id
            or set(payload) != CARRIED_KEYS
            or payload["representation_id"] != str(representation.id)
            or payload["run_id"] != str(run.id)
            or payload["previous_run_id"] != str(run.supersedes_run_id)
            or payload["identity_id"] != str(identity_id)
            or payload["rule"] != RULE
            or not AcceptProcessingRunUseCase._number(payload["iou"])
            or not AcceptProcessingRunUseCase._number(payload["cosine"])
            or payload["iou"] < MIN_IOU
            or payload["cosine"] < MIN_COSINE
            or previous is None
            or previous.processing_run_id != run.supersedes_run_id
            or payload["previous_representation_id"] != str(previous.id)
            or links
            != [
                EvidenceLink(representation.id, EvidenceRepresentationRole.SUBJECT),
                EvidenceLink(previous.id, EvidenceRepresentationRole.SUPPORTING),
            ]
            or len(occurrences) != 1
            or occurrences[0].identity_id != identity_id
            or occurrences[0].state != OccurrenceState.ACTIVE
            or len(operations) != 1
        ):
            raise AcceptanceError("completed processing run has an inconsistent carried face")

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
        keys = _EVIDENCE_KEYS | ({"proposal"} if reason is Reason.TRACK_UNSETTLED else set())
        if set(value) != keys or value.get("schema_version") != EVIDENCE_SCHEMA_VERSION:
            raise AcceptanceError("FINAL checkpoint decision has an unsupported evidence schema")
        if reason is Reason.TRACK_UNSETTLED:
            self._proposal(value["proposal"])
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

    def _proposal(self, value: object) -> None:
        """An unsettled track face's own proposal: a decision the reasoner can make."""
        if not isinstance(value, dict) or set(value) != {"outcome", "reason", "identity_id"}:
            raise AcceptanceError("FINAL checkpoint proposal has an unknown or missing field")
        try:
            outcome, reason = RecognitionOutcome(value["outcome"]), Reason(value["reason"])
        except (TypeError, ValueError) as error:
            raise AcceptanceError("FINAL checkpoint proposal is not a decision") from error
        if reason is Reason.TRACK_UNSETTLED or reason not in _REASONS_BY_OUTCOME[outcome]:
            raise AcceptanceError("FINAL checkpoint proposal reason does not fit its outcome")
        if value["identity_id"] is not None:
            self._uuid(value["identity_id"], "proposal identity")

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
        settled: tuple["_Track", tuple[uuid.UUID, ...]] | None = None,
    ) -> None:
        """`track_members`: a video face's settled track (its occurrence's members)."""
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
            or occurrences[0].kind
            != (OccurrenceKind.IMAGE if settled is None else OccurrenceKind.TRACK)
            or OccurrenceRepository(session).observation_ids(occurrences[0].id)
            != list(settled[1] if settled else (decision.observation_id,))
            or settled is not None
            and (
                occurrences[0].representative_observation_id,
                occurrences[0].start_timestamp_ms,
                occurrences[0].end_timestamp_ms,
                occurrences[0].start_frame,
                occurrences[0].end_frame,
            )
            != (
                settled[1][0],
                settled[0].start_ms,
                settled[0].end_ms,
                settled[0].start_frame,
                settled[0].end_frame,
            )
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


def _validate_track_rule(
    decisions: Sequence[_Decision],
    proposals: Mapping[uuid.UUID, tuple[RecognitionOutcome, uuid.UUID | None]],
    tracks: tuple[_Track, ...] | None,
) -> None:
    """D7 on what each face's own evidence decides: a track keeps its matches only when they all
    name the same identity; otherwise every one of its faces abstains as `TRACK_UNSETTLED`."""
    by_observation = {decision.observation_id: decision for decision in decisions}
    if tracks is None:
        if any(d.reason is Reason.TRACK_UNSETTLED for d in decisions):
            raise AcceptanceError("only a video track's face can be left unsettled")
        return
    for track in tracks:
        agreed = agreed_identity([proposals[o] for o in track.observations])
        unsettled = [by_observation[o].reason is Reason.TRACK_UNSETTLED for o in track.observations]
        if any(unsettled) if agreed is not None else not all(unsettled):
            raise AcceptanceError("FINAL checkpoint track does not follow the track rule")


def _matched(
    decisions: Sequence[_Decision], *, exclude: Collection[uuid.UUID]
) -> dict[uuid.UUID, uuid.UUID]:
    """Each face accepted as a match, by observation, with its identity (`exclude`: faces a
    reprocess suppresses or carries over, by representation)."""
    return {
        d.observation_id: d.identity_id
        for d in decisions
        if d.outcome is RecognitionOutcome.MATCH_EXISTING
        and d.identity_id is not None
        and d.representation_id not in exclude
    }


def _settled_tracks(
    tracks: tuple[_Track, ...] | None, placed: Mapping[uuid.UUID, uuid.UUID]
) -> list[tuple[_Track, uuid.UUID, tuple[uuid.UUID, ...]]]:
    """One occurrence per track and identity: the track's faces that were placed (matched, or a
    reprocess's carried-over human decision), grouped by identity, spanning the track's time."""
    settled: list[tuple[_Track, uuid.UUID, tuple[uuid.UUID, ...]]] = []
    for track in tracks or ():
        by_identity: dict[uuid.UUID, list[uuid.UUID]] = {}
        for observation in track.observations:
            if observation in placed:
                by_identity.setdefault(placed[observation], []).append(observation)
        settled.extend((track, identity, tuple(m)) for identity, m in by_identity.items())
    return settled


def _recorded_proposals(
    decisions: Sequence[_Decision],
) -> dict[uuid.UUID, tuple[RecognitionOutcome, uuid.UUID | None]]:
    """Each face's own decision as recorded: its proposal when left unsettled, else itself."""
    recorded: dict[uuid.UUID, tuple[RecognitionOutcome, uuid.UUID | None]] = {}
    for d in decisions:
        if d.reason is Reason.TRACK_UNSETTLED:
            proposal = d.evidence["proposal"]
            identity = proposal["identity_id"]
            recorded[d.observation_id] = (
                RecognitionOutcome(proposal["outcome"]),
                None if identity is None else uuid.UUID(identity),
            )
        else:
            recorded[d.observation_id] = (d.outcome, d.identity_id)
    return recorded
