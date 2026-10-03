"""TST-040: candidate retrieval respects representation compatibility (Persistence 23).

Two pools, one space: the global index of ACTIVE representations and the run's own PENDING ones.
SQLite revalidates what either returns; a stale or foreign candidate is dropped and counted.
"""

import uuid
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from numpy.typing import NDArray
from sqlalchemy import update

from backend.app.memory.models import Representation, RepresentationSpace
from backend.app.processing.models import ProcessingRun
from backend.app.recognition import retrieval
from backend.app.recognition.retrieval import (
    IncompatibleSpaceError,
    Pool,
    Retrieval,
    index_converged,
    rebuild_run_local_index,
    retrieve,
)
from backend.infrastructure.indexing.representation_index import RepresentationIndex
from backend.infrastructure.indexing.run_local_index import RunLocalIndex
from tests.factories.models import ModelFactory, float32_vector

NDIM = 4
METRIC = "cos"
Vec = NDArray[np.float32]


def unit(*values: float) -> Vec:
    array = np.array(values, dtype=np.float32)
    return np.asarray(array / np.linalg.norm(array), dtype=np.float32)


def blob(vector: Vec) -> bytes:
    return float32_vector([float(v) for v in vector])


class World:
    """One space, one run, and the two indexes retrieval is given."""

    def __init__(self, build: ModelFactory, directory: Path) -> None:
        self.build = build
        self.space: RepresentationSpace = build.representation_space(dimension=NDIM)
        self.run: ProcessingRun = build.run()
        self.global_index = RepresentationIndex.empty(
            directory, representation_space_id=self.space.id, ndim=NDIM, metric=METRIC
        )
        self.local = RunLocalIndex(representation_space_id=self.space.id, ndim=NDIM, metric=METRIC)

    def active(self, key: int, vector: Vec, **kw: Any) -> Representation:
        """An ACTIVE representation of its own ACTIVE identity, in the global index under `key`."""
        fields: dict[str, Any] = dict(
            representation_space_id=self.space.id, state="ACTIVE", ann_key=key,
            identity_id=self.build.identity().id, vector=blob(vector),
        )  # fmt: skip
        rep = self.build.representation(**(fields | kw))
        self.global_index.add(key, vector)
        return rep

    def pending(self, vector: Vec, **kw: Any) -> Representation:
        """A PENDING representation of this run, in the run-local index."""
        fields: dict[str, Any] = dict(representation_space_id=self.space.id, vector=blob(vector))
        rep = self.build.representation(self.build.observation(self.run), **(fields | kw))
        self.local.add(rep.id, vector)
        return rep

    def stranger(self, run: ProcessingRun, space_id: uuid.UUID, vector: Vec) -> Representation:
        """A PENDING representation that is not this run's in this space (not in any index)."""
        return self.build.representation(
            self.build.observation(run), representation_space_id=space_id, vector=blob(vector)
        )

    def ask(self, vector: Vec, k: int = 5, **kw: Any) -> Retrieval:
        arguments: dict[str, Any] = dict(
            representation_space_id=self.space.id, dimension=NDIM, vector=vector, k=k,
            global_index=self.global_index, processing_run_id=self.run.id, run_local=self.local,
        )  # fmt: skip
        return retrieve(self.build.session, **(arguments | kw))


@pytest.fixture
def world(build: ModelFactory, tmp_path: Path) -> World:
    return World(build, tmp_path / "index")


# --- the two pools -----------------------------------------------------------------------------


def test_global_candidates_carry_their_identity_and_come_nearest_first(world: World) -> None:
    far = world.active(2, unit(0, 1, 0, 0))
    near = world.active(1, unit(1, 0.05, 0, 0))
    found = world.ask(unit(1, 0, 0, 0))
    assert [c.representation_id for c in found.candidates] == [near.id, far.id]
    assert [c.pool for c in found.candidates] == [Pool.GLOBAL, Pool.GLOBAL]
    assert found.candidates[0].identity_id == near.identity_id
    assert found.candidates[0].similarity == pytest.approx(1.0, abs=2e-3)
    assert found.candidates[1].similarity == pytest.approx(0.0, abs=1e-3)
    assert found.dropped == 0
    assert found.requested_k == 5
    assert found.representation_space_id == world.space.id


def test_a_run_local_candidate_carries_the_pending_identity_the_run_gave_it_or_none(
    world: World,
) -> None:
    pending_identity = world.build.identity(
        state="PENDING", created_by_processing_run_id=world.run.id
    )
    named = world.pending(unit(1, 0, 0, 0), identity_id=pending_identity.id)
    left_alone = world.pending(unit(0, 1, 0, 0))  # (an abstention: no identity)
    found = {c.representation_id: c for c in world.ask(unit(1, 0.01, 0, 0)).candidates}
    assert found[named.id].pool is Pool.RUN_LOCAL
    assert found[named.id].identity_id == pending_identity.id
    assert found[left_alone.id].pool is Pool.RUN_LOCAL
    assert found[left_alone.id].identity_id is None


def test_both_pools_are_merged_nearest_first_and_cut_to_k(world: World) -> None:
    g_near = world.active(1, unit(1, 0.1, 0, 0))
    g_far = world.active(2, unit(1, 1, 0, 0))
    l_nearest = world.pending(unit(1, 0.01, 0, 0))
    l_far = world.pending(unit(0, 1, 0, 0))
    query = unit(1, 0, 0, 0)
    everything = world.ask(query, k=4).candidates
    assert [c.representation_id for c in everything] == [
        l_nearest.id,
        g_near.id,
        g_far.id,
        l_far.id,  # fmt: skip
    ]
    cut = world.ask(query, k=2)
    assert [c.representation_id for c in cut.candidates] == [l_nearest.id, g_near.id]
    assert cut.requested_k == 2


def test_an_exact_tie_puts_the_global_candidate_first(world: World) -> None:
    same = unit(1, 1, 0, 0)
    local = world.pending(same, id=uuid.UUID(int=1))  # (an id that sorts before the global's)
    shared = world.active(1, same, id=uuid.UUID(int=2))
    found = world.ask(unit(1, 0, 0, 0)).candidates
    assert [c.representation_id for c in found] == [shared.id, local.id]


@pytest.mark.parametrize("ids", [(1, 2, 3), (3, 2, 1), (2, 3, 1)])
def test_candidates_at_one_distance_are_ordered_by_id_whatever_order_they_were_indexed_in(
    world: World, ids: tuple[int, ...]
) -> None:
    same = unit(1, 1, 0, 0)
    for number in ids:
        world.pending(same, id=uuid.UUID(int=number))
    found = world.ask(unit(1, 0, 0, 0)).candidates
    assert [c.representation_id for c in found] == [uuid.UUID(int=n) for n in (1, 2, 3)]


def test_without_a_run_local_index_only_the_global_pool_is_searched(world: World) -> None:
    world.pending(unit(1, 0, 0, 0))
    world.active(1, unit(0, 1, 0, 0))
    found = world.ask(unit(1, 0, 0, 0), run_local=None).candidates
    assert [c.pool for c in found] == [Pool.GLOBAL]


def test_an_empty_library_and_an_empty_run_have_no_candidates_and_nothing_dropped(
    world: World,
) -> None:
    found = world.ask(unit(1, 0, 0, 0))
    assert found.candidates == ()
    assert found.dropped == 0


# --- revalidation: what SQLite refuses is dropped and counted ----------------------------------


@pytest.mark.parametrize("state", ["ERASING", "SUPERSEDED", "DELETED"])
def test_a_global_candidate_that_is_no_longer_active_is_dropped_and_counted(
    world: World, state: str
) -> None:
    kept = world.active(1, unit(1, 0.2, 0, 0))
    world.active(2, unit(1, 0.1, 0, 0), state=state)
    found = world.ask(unit(1, 0, 0, 0))
    assert [c.representation_id for c in found.candidates] == [kept.id]
    assert found.dropped == 1


def test_a_global_candidate_of_an_identity_that_is_gone_is_dropped(world: World) -> None:
    world.active(1, unit(1, 0, 0, 0), identity_id=world.build.identity(state="FORGOTTEN").id)
    found = world.ask(unit(1, 0, 0, 0))
    assert found.candidates == ()
    assert found.dropped == 1


def test_another_spaces_representation_with_the_same_key_is_never_returned(world: World) -> None:
    other = world.build.representation_space(dimension=NDIM)
    world.build.representation(
        representation_space_id=other.id, state="ACTIVE", ann_key=1,
        identity_id=world.build.identity().id, vector=blob(unit(1, 0, 0, 0)),
    )  # fmt: skip
    world.global_index.add(1, unit(1, 0, 0, 0))  # (the index names key 1; only `other` holds it)
    found = world.ask(unit(1, 0, 0, 0))
    assert found.candidates == ()
    assert found.dropped == 1


@pytest.mark.parametrize("state", ["ACTIVE", "SUPERSEDED", "ERASING", "DELETED"])
def test_a_run_local_candidate_that_is_no_longer_pending_is_dropped_and_counted(
    world: World, state: str
) -> None:
    kept = world.pending(unit(1, 0.2, 0, 0))
    stale = world.pending(unit(1, 0.1, 0, 0))
    world.build.session.execute(
        update(Representation)
        .where(Representation.id == stale.id)
        .values(state=state, identity_id=world.build.identity().id, ann_key=77)
    )
    world.build.session.expire_all()
    found = world.ask(unit(1, 0, 0, 0))
    assert [c.representation_id for c in found.candidates] == [kept.id]
    assert found.dropped == 1


def test_a_pending_representation_of_another_run_or_space_is_never_returned(
    world: World,
) -> None:
    mine = world.pending(unit(1, 0.2, 0, 0))
    other_run = world.stranger(world.build.run(), world.space.id, unit(1, 0, 0, 0))
    other_space = world.stranger(
        world.run, world.build.representation_space(dimension=NDIM).id, unit(1, 0, 0, 0)
    )
    world.local.add(other_run.id, unit(1, 0, 0, 0))  # (a corrupt local index naming strangers)
    world.local.add(other_space.id, unit(1, 0, 0, 0))
    found = world.ask(unit(1, 0, 0, 0))
    assert [c.representation_id for c in found.candidates] == [mine.id]
    assert found.dropped == 2


def test_a_long_shortlist_is_revalidated_in_chunks(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(retrieval, "_IDS_PER_QUERY", 2)
    made = [world.pending(unit(1, 0.01 * (n + 1), 0, 0)) for n in range(5)]
    found = world.ask(unit(1, 0, 0, 0), k=5).candidates
    assert [c.representation_id for c in found] == [r.id for r in made]


# --- compatibility is enforced, not trusted ---------------------------------------------------


def test_a_global_index_of_another_space_is_refused_before_anything_is_searched(
    world: World, tmp_path: Path
) -> None:
    other = RepresentationIndex.empty(
        tmp_path / "other", representation_space_id=uuid.uuid4(), ndim=NDIM, metric=METRIC
    )
    with pytest.raises(IncompatibleSpaceError, match="global"):
        world.ask(unit(1, 0, 0, 0), global_index=other)


def test_a_global_index_of_another_dimension_is_refused(world: World, tmp_path: Path) -> None:
    wide = RepresentationIndex.empty(
        tmp_path / "wide", representation_space_id=world.space.id, ndim=NDIM + 1, metric=METRIC
    )
    with pytest.raises(IncompatibleSpaceError, match="global"):
        world.ask(unit(1, 0, 0, 0), global_index=wide)


def test_a_run_local_index_of_another_space_or_dimension_is_refused(world: World) -> None:
    foreign = RunLocalIndex(representation_space_id=uuid.uuid4(), ndim=NDIM, metric=METRIC)
    with pytest.raises(IncompatibleSpaceError, match="run-local"):
        world.ask(unit(1, 0, 0, 0), run_local=foreign)
    wide = RunLocalIndex(representation_space_id=world.space.id, ndim=NDIM + 1, metric=METRIC)
    with pytest.raises(IncompatibleSpaceError, match="run-local"):
        world.ask(unit(1, 0, 0, 0), run_local=wide)


def test_a_query_of_the_wrong_dimension_is_refused(world: World) -> None:
    with pytest.raises(ValueError, match="dimensions"):
        world.ask(unit(1, 0, 0))


def test_k_must_be_at_least_one(world: World) -> None:
    with pytest.raises(ValueError, match="at least 1"):
        world.ask(unit(1, 0, 0, 0), k=0)


# --- rebuilding the run-local pool after a crash ----------------------------------------------


def rebuild(world: World) -> RunLocalIndex:
    return rebuild_run_local_index(
        world.build.session, processing_run_id=world.run.id,
        representation_space_id=world.space.id, dimension=NDIM, metric=METRIC,
    )  # fmt: skip


def test_the_run_local_index_is_rebuilt_from_this_runs_pending_representations_only(
    world: World,
) -> None:
    mine = [world.pending(unit(1, 0.1 * n, 0, 0)) for n in range(1, 4)]
    world.pending(
        unit(1, 0.5, 0, 0), state="SUPERSEDED", identity_id=world.build.identity().id, ann_key=9
    )
    world.stranger(world.build.run(), world.space.id, unit(1, 0, 0, 0))
    world.stranger(world.run, world.build.representation_space(dimension=NDIM).id, unit(1, 0, 0, 0))
    rebuilt = rebuild(world)
    assert len(rebuilt) == 3
    assert rebuilt.representation_space_id == world.space.id
    found = rebuilt.search(unit(1, 0, 0, 0), 10)
    assert [c.representation_id for c in found] == [r.id for r in mine]


def test_a_rebuilt_index_answers_retrieval_like_the_original(world: World) -> None:
    for n in range(1, 4):
        world.pending(unit(1, 0.1 * n, 0, 0))
    before = world.ask(unit(1, 0, 0, 0))
    after = world.ask(unit(1, 0, 0, 0), run_local=rebuild(world))
    assert len(after.candidates) == 3
    assert after == before


def test_a_vector_that_cannot_be_decoded_is_an_error_and_not_skipped(world: World) -> None:
    world.pending(unit(1, 0, 0, 0))
    world.build.representation(
        world.build.observation(world.run), representation_space_id=world.space.id,
        vector=float32_vector([1.0, float("nan"), 0.0, 0.0]),
    )  # fmt: skip
    with pytest.raises(ValueError, match="finite"):
        rebuild(world)


def test_stale_candidates_of_both_pools_are_all_counted(world: World) -> None:
    world.active(1, unit(1, 0.2, 0, 0))
    world.active(2, unit(1, 0.1, 0, 0), state="ERASING")
    world.active(3, unit(1, 0.15, 0, 0), state="DELETED")
    world.pending(unit(1, 0.3, 0, 0))
    gone = world.pending(unit(1, 0.05, 0, 0))
    world.build.session.execute(
        update(Representation).where(Representation.id == gone.id).values(state="DELETED")
    )
    world.build.session.expire_all()
    found = world.ask(unit(1, 0, 0, 0))
    assert len(found.candidates) == 2
    assert found.dropped == 3


@pytest.mark.parametrize("metric", ["ip", "l2sq"])
def test_an_index_of_a_metric_other_than_cosine_is_refused_in_either_pool(
    world: World, tmp_path: Path, metric: str
) -> None:
    other = RepresentationIndex.empty(
        tmp_path / metric, representation_space_id=world.space.id, ndim=NDIM, metric=metric
    )
    with pytest.raises(IncompatibleSpaceError, match="cosine"):
        world.ask(unit(1, 0, 0, 0), global_index=other)
    foreign = RunLocalIndex(representation_space_id=world.space.id, ndim=NDIM, metric=metric)
    with pytest.raises(IncompatibleSpaceError, match="cosine"):
        world.ask(unit(1, 0, 0, 0), run_local=foreign)


# --- representations that must never be candidates, and an index that is behind -------


def test_excluded_representations_are_left_out_of_both_pools_without_shortening_the_list(
    world: World,
) -> None:
    own = world.pending(unit(1, 0.0, 0, 0))
    sibling = world.active(1, unit(1, 0.01, 0, 0))
    kept = [world.active(n + 2, unit(1, 0.05 * (n + 1), 0, 0)) for n in range(3)]
    found = world.ask(unit(1, 0, 0, 0), k=3, exclude=[own.id, sibling.id])
    assert [c.representation_id for c in found.candidates] == [r.id for r in kept]
    assert found.dropped == 0  # (leaving them out is not SQLite refusing them)


def test_without_an_exclusion_the_query_s_own_pending_representation_is_found(
    world: World,
) -> None:
    own = world.pending(unit(1, 0.0, 0, 0))
    (found,) = world.ask(unit(1, 0, 0, 0)).candidates
    assert found.representation_id == own.id
    assert found.similarity == pytest.approx(1.0, abs=1e-6)


@pytest.mark.parametrize(
    ("state", "converged"),
    [("PENDING", False), ("FAILED", False), ("APPLIED", True)],
)
def test_the_index_has_caught_up_only_when_no_operation_of_the_space_waits_or_failed(
    world: World, state: str, converged: bool
) -> None:
    applied = {"applied_at": world.build.clock()} if state == "APPLIED" else {}
    world.build.index_operation(
        world.build.representation(representation_space_id=world.space.id),
        state=state, **applied,
    )  # fmt: skip
    assert index_converged(world.build.session, world.space.id) is converged
    assert world.ask(unit(1, 0, 0, 0)).converged is converged


def test_another_spaces_waiting_operation_does_not_make_this_space_unconverged(
    world: World,
) -> None:
    other = world.build.representation_space(dimension=NDIM)
    world.build.index_operation(world.build.representation(representation_space_id=other.id))
    assert index_converged(world.build.session, world.space.id) is True
    assert index_converged(world.build.session, other.id) is False
