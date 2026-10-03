"""Representation-level revalidation of ANN candidates (persistence §23, §6.2; TESTING_STRATEGY
INDEX-03, SEARCH-01; GitHub issue #44).

An index returns `ann_key`s, and SQLite decides which are still candidates: the row must be in the
space, `ACTIVE`, with an `ACTIVE` identity. The case that matters most is a representation whose
erasure is queued (`ERASING`): it keeps its vector and key until the index has been rebuilt without
it, so a stale index can still return its key for an identity that is perfectly active. Checking the
identity alone, as `resolve_recognition_candidates` does, would accept it.
"""

import uuid
from pathlib import Path

import numpy as np
import pytest
from sqlalchemy import event, func, select, update

from backend.app.identities.models import Identity, IdentityState
from backend.app.identities.use_cases import merge_identities, resolve_ann_candidates
from backend.app.memory.models import IndexOperation, Representation, RepresentationState
from backend.infrastructure.indexing.representation_index import RepresentationIndex
from tests.factories.models import ModelFactory, float32_vector
from tests.fixtures.deterministic import FrozenClock, SeededUUIDs

NDIM = 4


def keyed(build: ModelFactory, space_id: uuid.UUID, key: int, **kw: object) -> Representation:
    fields: dict[str, object] = dict(
        representation_space_id=space_id, state="ACTIVE", identity_id=build.identity().id,
        ann_key=key, vector=float32_vector([float(key), 1.0, 0.0, 0.0]),
    )  # fmt: skip
    return build.representation(**(fields | kw))


def keys_of(candidates: list) -> list[int]:  # type: ignore[type-arg]
    return [candidate.ann_key for candidate in candidates]


# --- what is kept -----------------------------------------------------------------------------


def test_an_active_representation_of_an_active_identity_is_kept_with_both_rows(
    build: ModelFactory,
) -> None:
    space = build.representation_space(dimension=NDIM)
    rep = keyed(build, space.id, 7)

    (candidate,) = resolve_ann_candidates(build.session, space.id, [7])

    assert candidate.ann_key == 7
    assert candidate.representation_id == rep.id
    assert candidate.identity_id == rep.identity_id


def test_input_order_is_kept_a_repeated_key_is_listed_once_and_unknown_keys_are_dropped(
    build: ModelFactory,
) -> None:
    space = build.representation_space(dimension=NDIM)
    for key in (1, 2, 3):
        keyed(build, space.id, key)

    resolved = resolve_ann_candidates(build.session, space.id, [3, 99, 1, 3, 2, 1])

    assert keys_of(resolved) == [3, 1, 2]


def test_no_keys_means_no_candidates_and_no_query(build: ModelFactory) -> None:
    space = build.representation_space(dimension=NDIM)
    statements: list[str] = []

    def record(_c: object, _cur: object, statement: str, *_r: object) -> None:
        statements.append(statement)

    engine = build.session.get_bind()
    event.listen(engine, "before_cursor_execute", record)
    try:
        assert resolve_ann_candidates(build.session, space.id, []) == []
    finally:
        event.remove(engine, "before_cursor_execute", record)

    assert statements == []


# --- what is dropped --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "state", [s.value for s in RepresentationState if s != RepresentationState.ACTIVE]
)
def test_a_representation_that_is_not_active_is_dropped_whatever_its_identity(
    build: ModelFactory, state: str
) -> None:
    space = build.representation_space(dimension=NDIM)
    # (a vector and key are only both present outside ERASED, so give ERASED neither)
    extra: dict[str, object] = {"vector": None, "ann_key": None} if state == "ERASED" else {}
    rep = keyed(build, space.id, 5, state=state, **extra)
    assert rep.identity_id is not None  # the identity is ACTIVE

    assert resolve_ann_candidates(build.session, space.id, [5]) == []


@pytest.mark.parametrize("state", [s.value for s in IdentityState if s != IdentityState.ACTIVE])
def test_an_active_representation_of_an_identity_that_is_not_active_is_dropped(
    build: ModelFactory, state: str
) -> None:
    space = build.representation_space(dimension=NDIM)
    extra: dict[str, object] = (
        {"merged_into_identity_id": build.identity().id} if state == "MERGED" else {}
    )
    identity = build.identity(state=state, **extra)
    keyed(build, space.id, 5, identity_id=identity.id)

    assert resolve_ann_candidates(build.session, space.id, [5]) == []


def test_another_spaces_key_is_dropped(build: ModelFactory) -> None:
    mine = build.representation_space(dimension=NDIM)
    other = build.representation_space(dimension=NDIM)
    keyed(build, other.id, 5)  # a valid candidate, but of a different semantic space

    assert resolve_ann_candidates(build.session, mine.id, [5]) == []
    assert keys_of(resolve_ann_candidates(build.session, other.id, [5])) == [5]


def test_a_representation_moved_by_a_merge_resolves_to_the_survivor(
    build: ModelFactory, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    space = build.representation_space(dimension=NDIM)
    survivor = build.identity()
    loser = build.identity()
    rep = keyed(build, space.id, 5, identity_id=loser.id)
    merge_identities(
        build.session,
        loser.id,
        survivor.id,
        expected_revision=loser.revision,
        new_id=new_id,
        clock=clock,
    )

    (candidate,) = resolve_ann_candidates(build.session, space.id, [5])

    assert candidate.representation_id == rep.id
    assert candidate.identity_id == survivor.id  # the stale key is answered by the current owner


# --- INDEX-03: a queued erasure is never retrieved ----------------------------------------------


def test_a_stale_index_that_still_holds_an_erasing_vector_does_not_return_it(
    build: ModelFactory, tmp_path: Path, clock: FrozenClock, new_id: SeededUUIDs
) -> None:
    """The index was built while the representation was ACTIVE and has not been rebuilt since: it
    still returns the vector's key as the nearest neighbour. The erasure is queued (ERASING), the
    identity is untouched and ACTIVE; revalidation refuses the key."""
    space = build.representation_space(dimension=NDIM)
    erasing = keyed(build, space.id, 1, vector=float32_vector([1.0, 0.0, 0.0, 0.0]))
    kept = keyed(build, space.id, 2, vector=float32_vector([0.9, 0.1, 0.0, 0.0]))
    index = RepresentationIndex.empty(
        tmp_path, representation_space_id=space.id, ndim=NDIM, metric="cos"
    )
    index.add(1, np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32))
    index.add(2, np.array([0.9, 0.1, 0.0, 0.0], dtype=np.float32))
    query = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
    returned = [candidate.key for candidate in index.search(query, 2)]
    assert returned[0] == 1  # the stale index offers the erasing vector first

    build.session.execute(
        update(Representation)
        .where(Representation.id == erasing.id)
        .values(state=RepresentationState.ERASING),
        execution_options={"synchronize_session": False},
    )  # step one of an erasure; nothing has touched the index

    resolved = resolve_ann_candidates(build.session, space.id, returned)

    assert [candidate.representation_id for candidate in resolved] == [kept.id]
    assert build.session.get(Identity, erasing.identity_id, populate_existing=True).state == (  # type: ignore[union-attr]
        "ACTIVE"
    )  # the identity check alone would have let the key through


# --- freshness, reading only, one query -----------------------------------------------------------


def test_a_row_this_session_already_loaded_does_not_outvote_the_database(
    build: ModelFactory,
) -> None:
    space = build.representation_space(dimension=NDIM)
    rep = keyed(build, space.id, 5)
    assert keys_of(resolve_ann_candidates(build.session, space.id, [5])) == [5]  # now cached
    build.session.execute(
        update(Representation).where(Representation.id == rep.id).values(state="ERASING"),
        execution_options={"synchronize_session": False},
    )

    assert resolve_ann_candidates(build.session, space.id, [5]) == []


def test_a_change_the_caller_has_made_but_not_flushed_is_neither_seen_nor_overwritten(
    build: ModelFactory,
) -> None:
    """The project's sessions do not autoflush, so a caller can hold an unflushed `ERASING`. The
    function answers from the database and must not refresh the caller's objects over it."""
    space = build.representation_space(dimension=NDIM)
    rep = keyed(build, space.id, 5)
    build.session.flush()
    rep.state = RepresentationState.ERASING  # pending, not flushed
    identity = build.session.get(Identity, rep.identity_id)
    assert identity is not None
    identity.revision = 99  # pending, not flushed

    resolved = resolve_ann_candidates(build.session, space.id, [5])

    assert keys_of(resolved) == [5]  # the database still says ACTIVE
    assert rep.state == RepresentationState.ERASING  # and the caller's pending change survived
    assert identity.revision == 99


def test_it_reads_only_and_asks_the_database_once(build: ModelFactory) -> None:
    space = build.representation_space(dimension=NDIM)
    for key in range(1, 6):
        keyed(build, space.id, key)
    build.session.flush()
    counts_before = (
        build.session.scalar(select(func.count()).select_from(Representation)),
        build.session.scalar(select(func.count()).select_from(Identity)),
        build.session.scalar(select(func.count()).select_from(IndexOperation)),
    )
    statements: list[tuple[str, object]] = []

    def record(_c: object, _cur: object, statement: str, parameters: object, *_r: object) -> None:
        statements.append((statement, parameters))

    engine = build.session.get_bind()
    event.listen(engine, "before_cursor_execute", record)
    try:
        resolve_ann_candidates(build.session, space.id, [1, 2, 3])
    finally:
        event.remove(engine, "before_cursor_execute", record)

    ((statement, parameters),) = statements  # one read for three keys, and nothing written
    assert statement.lstrip().upper().startswith("SELECT")
    assert "ann_key IN" in statement  # it asks for those keys, not for the whole space
    assert {1, 2, 3} <= set(parameters)  # type: ignore[call-overload]
    assert not build.session.dirty
    assert counts_before == (
        build.session.scalar(select(func.count()).select_from(Representation)),
        build.session.scalar(select(func.count()).select_from(Identity)),
        build.session.scalar(select(func.count()).select_from(IndexOperation)),
    )


def test_a_long_candidate_list_is_read_in_chunks_and_still_answered_in_order(
    build: ModelFactory,
) -> None:
    """More keys than fit one statement (SQLite limits bound variables): read a chunk at a time,
    with the answer as if it had been one query."""
    space = build.representation_space(dimension=NDIM)
    # positions 0, 499, 500, 999, 1000 and 1149 of the list: the first and last key of every chunk
    boundary = (1150, 651, 650, 151, 150, 1)
    valid = {key: keyed(build, space.id, key) for key in boundary}
    build.session.flush()
    keys = list(range(1150, 0, -1))  # 1150 distinct keys, so three chunks
    statements: list[str] = []

    def record(_c: object, _cur: object, statement: str, *_r: object) -> None:
        statements.append(statement)

    engine = build.session.get_bind()
    event.listen(engine, "before_cursor_execute", record)
    try:
        resolved = resolve_ann_candidates(build.session, space.id, keys)
    finally:
        event.remove(engine, "before_cursor_execute", record)

    assert keys_of(resolved) == list(boundary)  # input order, across chunks, none lost at an edge
    assert [c.representation_id for c in resolved] == [valid[k].id for k in boundary]
    assert len(statements) == 3


def test_repeats_are_removed_before_the_query_so_they_cannot_overflow_it(
    build: ModelFactory,
) -> None:
    space = build.representation_space(dimension=NDIM)
    keyed(build, space.id, 5)
    build.session.flush()
    statements: list[tuple[str, object]] = []

    def record(_c: object, _cur: object, statement: str, parameters: object, *_r: object) -> None:
        statements.append((statement, parameters))

    engine = build.session.get_bind()
    event.listen(engine, "before_cursor_execute", record)
    try:
        resolved = resolve_ann_candidates(build.session, space.id, [5] * 5000)
    finally:
        event.remove(engine, "before_cursor_execute", record)

    assert keys_of(resolved) == [5]
    ((_, parameters),) = statements  # one statement, not ten
    assert len(parameters) <= 5  # type: ignore[arg-type]  # the key once, plus the space and states


# --- an accepted ABSTAIN representation: ACTIVE, no identity (decision 2026-10-02) -------------


def abstained(build: ModelFactory, space_id: uuid.UUID, key: int, **kw: object) -> Representation:
    fields: dict[str, object] = dict(
        representation_space_id=space_id, state="ACTIVE", ann_key=key,
        vector=float32_vector([float(key), 1.0, 0.0, 0.0]),
    )  # fmt: skip
    return build.representation(**(fields | kw))


def test_an_accepted_abstention_is_kept_as_a_candidate_with_no_identity(
    build: ModelFactory,
) -> None:
    space = build.representation_space(dimension=NDIM)
    rep = abstained(build, space.id, 7)
    known = keyed(build, space.id, 8)

    resolved = resolve_ann_candidates(build.session, space.id, [8, 7])

    assert keys_of(resolved) == [8, 7]
    assert resolved[1].representation_id == rep.id
    assert resolved[1].identity_id is None  # evidence only: never a target to match
    assert resolved[0].identity_id == known.identity_id


@pytest.mark.parametrize("state", ["PENDING", "SUPERSEDED", "ERASING", "DELETED"])
def test_an_identity_less_representation_that_is_not_active_is_still_dropped(
    build: ModelFactory, state: str
) -> None:
    space = build.representation_space(dimension=NDIM)
    abstained(build, space.id, 5, state=state)

    assert resolve_ann_candidates(build.session, space.id, [5]) == []


def test_an_identity_less_representation_of_another_space_is_dropped(build: ModelFactory) -> None:
    mine = build.representation_space(dimension=NDIM)
    other = build.representation_space(dimension=NDIM)
    abstained(build, other.id, 5)

    assert resolve_ann_candidates(build.session, mine.id, [5]) == []
