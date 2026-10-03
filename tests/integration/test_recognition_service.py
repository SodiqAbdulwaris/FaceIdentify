"""RecognitionService end to end over real indexes and SQLite: a vector in, an assessment out,
and the reasoner's proposal on top of it (TST-041, TST-042 first half: assessments satisfy their
contract; nothing is committed here)."""

import uuid
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from numpy.typing import NDArray

from backend.app.recognition.assessment import ObservationQuality, RecognitionService
from backend.app.recognition.reasoner import (
    DecisionPolicy,
    IdentityReasoner,
    Reason,
    RecognitionOutcome,
)
from backend.app.recognition.retrieval import IncompatibleSpaceError, Pool
from backend.infrastructure.indexing.representation_index import RepresentationIndex
from backend.infrastructure.indexing.run_local_index import RunLocalIndex
from tests.factories.models import ModelFactory, float32_vector

NDIM = 4
POLICY = DecisionPolicy("policy-test-1", 0.5, 0.8, 0.1, 0.3)
Vec = NDArray[np.float32]


def unit(*values: float) -> Vec:
    array = np.array(values, dtype=np.float32)
    return np.asarray(array / np.linalg.norm(array), dtype=np.float32)


class Memory:
    def __init__(self, build: ModelFactory, directory: Path) -> None:
        self.build = build
        self.space = build.representation_space(dimension=NDIM)
        self.run = build.run()
        self.index = RepresentationIndex.empty(
            directory, representation_space_id=self.space.id, ndim=NDIM, metric="cos"
        )
        self.local = RunLocalIndex(representation_space_id=self.space.id, ndim=NDIM, metric="cos")
        self.next_key = 1

    def known(self, vector: Vec) -> uuid.UUID:
        """An ACTIVE representation of a new ACTIVE identity, in the global index."""
        identity = self.build.identity()
        self.build.representation(
            representation_space_id=self.space.id, state="ACTIVE", ann_key=self.next_key,
            identity_id=identity.id, vector=float32_vector([float(v) for v in vector]),
        )  # fmt: skip
        self.index.add(self.next_key, vector)
        self.next_key += 1
        return identity.id

    def assess(self, vector: Vec, **kw: Any) -> Any:
        arguments: dict[str, Any] = dict(
            representation_space_id=self.space.id, dimension=NDIM, vector=vector,
            quality=ObservationQuality(0.9), global_index=self.index,
            processing_run_id=self.run.id, run_local=self.local,
        )  # fmt: skip
        return RecognitionService(k=5).assess(self.build.session, **(arguments | kw))


@pytest.fixture
def memory(build: ModelFactory, tmp_path: Path) -> Memory:
    return Memory(build, tmp_path / "index")


def test_an_empty_memory_is_a_valid_unknown(memory: Memory) -> None:
    assessment = memory.assess(unit(1, 0, 0, 0))
    assert assessment.groups == ()
    assert assessment.complete
    decision = IdentityReasoner(POLICY).decide(assessment)
    assert decision.outcome is RecognitionOutcome.CREATE_NEW
    assert decision.reason is Reason.NO_CANDIDATE


def test_a_known_face_is_matched_through_the_whole_path(memory: Memory) -> None:
    alice = memory.known(unit(1, 0.02, 0, 0))
    memory.known(unit(0, 1, 0, 0))
    assessment = memory.assess(unit(1, 0, 0, 0))
    assert [g.identity_id for g in assessment.groups][0] == alice
    assert assessment.groups[0].members[0].similarity > assessment.groups[1].members[0].similarity
    assert assessment.requested_k == 5
    assert assessment.returned == 2
    decision = IdentityReasoner(POLICY).decide(assessment)
    assert decision.outcome is RecognitionOutcome.MATCH_EXISTING
    assert decision.identity_id == alice


def test_the_same_new_person_twice_in_one_run_is_recognised_through_the_run_local_pool(
    memory: Memory,
) -> None:
    pending_identity = memory.build.identity(
        state="PENDING", created_by_processing_run_id=memory.run.id
    )
    first = memory.build.representation(
        memory.build.observation(memory.run), representation_space_id=memory.space.id,
        identity_id=pending_identity.id, vector=float32_vector([1.0, 0.0, 0.0, 0.0]),
    )  # fmt: skip
    memory.local.add(first.id, unit(1, 0, 0, 0))
    assessment = memory.assess(unit(1, 0.03, 0, 0))
    (group,) = assessment.groups
    assert [m.pool for m in group.members] == [Pool.RUN_LOCAL]
    decision = IdentityReasoner(POLICY).decide(assessment)
    assert decision.outcome is RecognitionOutcome.MATCH_EXISTING
    assert decision.identity_id == pending_identity.id


def test_a_stale_neighbour_makes_the_assessment_incomplete_and_the_reasoner_abstain(
    memory: Memory,
) -> None:
    memory.known(unit(0, 1, 0, 0))
    stale = memory.build.representation(
        representation_space_id=memory.space.id, state="ERASING", ann_key=99,
        identity_id=memory.build.identity().id, vector=float32_vector([1.0, 0.0, 0.0, 0.0]),
    )  # fmt: skip
    memory.index.add(99, unit(1, 0, 0, 0))
    assessment = memory.assess(unit(1, 0, 0, 0))
    assert assessment.dropped == 1
    assert not assessment.complete
    assert stale.id not in {m.representation_id for g in assessment.groups for m in g.members}
    decision = IdentityReasoner(POLICY).decide(assessment)
    assert decision.reason is Reason.RETRIEVAL_INCOMPLETE
    assert decision.outcome is RecognitionOutcome.ABSTAIN


def test_the_query_s_own_pending_representation_is_never_its_own_neighbour(
    memory: Memory,
) -> None:
    """The representation being recognised exists, PENDING, before it is recognised: without
    `exclude` it would be its own nearest candidate and every face would abstain."""
    own = memory.build.representation(
        memory.build.observation(memory.run), representation_space_id=memory.space.id,
        vector=float32_vector([1.0, 0.0, 0.0, 0.0]),
    )  # fmt: skip
    memory.local.add(own.id, unit(1, 0, 0, 0))
    including = memory.assess(unit(1, 0, 0, 0))
    assert [g.identity_id for g in including.groups] == [None]  # (the self-hit)
    assert IdentityReasoner(POLICY).decide(including).reason is Reason.UNRESOLVED_NEIGHBOUR
    excluding = memory.assess(unit(1, 0, 0, 0), exclude=[own.id])
    assert excluding.groups == ()
    decision = IdentityReasoner(POLICY).decide(excluding)
    assert decision.outcome is RecognitionOutcome.CREATE_NEW


def test_an_index_that_is_behind_sqlite_is_not_complete_even_though_nothing_was_dropped(
    memory: Memory,
) -> None:
    behind = memory.build.representation(
        representation_space_id=memory.space.id, state="ACTIVE", ann_key=50,
        identity_id=memory.build.identity().id, vector=float32_vector([1.0, 0.0, 0.0, 0.0]),
    )  # fmt: skip
    memory.build.index_operation(behind, operation="ADD")  # accepted, but not yet in the index
    assessment = memory.assess(unit(1, 0, 0, 0))
    assert assessment.groups == ()
    assert assessment.dropped == 0
    assert not assessment.converged
    assert not assessment.complete
    decision = IdentityReasoner(POLICY).decide(assessment)
    assert decision.reason is Reason.RETRIEVAL_INCOMPLETE  # not a "valid unknown": no duplicate


def test_the_service_never_mixes_spaces(memory: Memory, tmp_path: Path) -> None:
    other = RepresentationIndex.empty(
        tmp_path / "other", representation_space_id=uuid.uuid4(), ndim=NDIM, metric="cos"
    )
    with pytest.raises(IncompatibleSpaceError):
        memory.assess(unit(1, 0, 0, 0), global_index=other)


def test_the_assessment_is_read_only(memory: Memory) -> None:
    memory.known(unit(1, 0, 0, 0))
    memory.build.session.flush()
    before = memory.build.session.new, memory.build.session.dirty
    memory.assess(unit(1, 0, 0, 0))
    assert (memory.build.session.new, memory.build.session.dirty) == before


def test_a_face_that_looks_like_an_accepted_abstention_is_not_matched_and_not_created(
    memory: Memory,
) -> None:
    """An identity-less ACTIVE neighbour is evidence only (Persistence 6.2): it can never be a
    `MATCH_EXISTING` target, and a new identity beside it would be a duplicate."""
    memory.build.representation(
        representation_space_id=memory.space.id, state="ACTIVE", ann_key=40,
        vector=float32_vector([1.0, 0.0, 0.0, 0.0]),
    )  # fmt: skip
    memory.index.add(40, unit(1, 0, 0, 0))
    assessment = memory.assess(unit(1, 0.01, 0, 0))
    assert [g.identity_id for g in assessment.groups] == [None]
    decision = IdentityReasoner(POLICY).decide(assessment)
    assert decision.outcome is RecognitionOutcome.ABSTAIN
    assert decision.reason is Reason.UNRESOLVED_NEIGHBOUR
