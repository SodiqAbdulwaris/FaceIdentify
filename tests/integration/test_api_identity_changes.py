"""Merging identities and splitting faces off one, through the API (M5 step 3; TST-058).

Identities and faces are built directly in the library (the pipeline that makes them is tested
elsewhere), so what is checked here is the two commands: what they return, what they refuse and that
a refusal changes nothing.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import select

from backend.app.identities.models import Evidence, Identity
from backend.app.memory.models import Occurrence, OccurrenceObservation
from tests.factories.models import ModelFactory
from tests.fixtures.api import Api, error
from tests.fixtures.deterministic import SeededUUIDs

IDENTITIES = "/api/v1/identities"
PEOPLE = "/api/v1/people"


@dataclass
class Person:
    identity: str
    revision: int
    occurrences: list[str]


def person(api: Api, new_id: SeededUUIDs, faces: int = 1, **kw: str) -> Person:
    assert api.backend.library is not None
    with api.backend.library.session_factory() as session:
        build = ModelFactory(session, api.clock, new_id)
        identity = build.identity(**kw)
        occurrences = []
        for key in range(faces):
            observation = build.observation()
            build.representation(
                observation,
                state="ACTIVE",
                ann_key=1 + key + 10 * len(session.scalars(select(Identity)).all()),
                identity_id=identity.id,
            )
            occurrences.append(
                str(build.occurrence(observation, identity_id=identity.id, state="ACTIVE").id)
            )
            if identity.representative_observation_id is None:
                identity.representative_observation_id = observation.id
        session.commit()
        return Person(str(identity.id), identity.revision, occurrences)


def body(survivor: Person, *others: Person) -> dict[str, object]:
    return {
        "identities": [{"id": p.identity, "revision": p.revision} for p in (survivor, *others)],
        "preferred_identity_id": survivor.identity,
    }


async def test_merging_moves_the_faces_to_the_survivor_and_retires_the_other(
    api: Api, new_id: SeededUUIDs
) -> None:
    keep, lose = person(api, new_id, 2), person(api, new_id)
    subscription = api.backend.events.subscribe()
    try:
        merged = await api.client.post(f"{IDENTITIES}/merge", json=body(keep, lose))
        announced = subscription.queue.qsize()
    finally:
        api.backend.events.unsubscribe(subscription)

    assert merged.status_code == 200
    assert merged.json()["id"] == keep.identity
    assert merged.json()["occurrence_count"] == 3
    assert announced == 1
    error(await api.client.get(f"{IDENTITIES}/{lose.identity}"), 404, "IDENTITY_NOT_FOUND")
    assert (await api.client.get(f"{IDENTITIES}/{keep.identity}/occurrences")).json()["items"]
    assert api.backend.library is not None
    with api.backend.library.session_factory() as session:
        kinds = [e.kind for e in session.scalars(select(Evidence))]
        owners = {o.identity_id for o in session.scalars(select(Occurrence))}
    assert kinds.count("IDENTITY_MERGED") == 1
    assert owners == {uuid.UUID(keep.identity)}


async def test_when_both_are_named_the_survivors_name_wins(api: Api, new_id: SeededUUIDs) -> None:
    keep, lose = person(api, new_id), person(api, new_id)
    for who, name in ((keep, "Alice"), (lose, "Alicia")):
        made = await api.client.post(
            PEOPLE, json={"display_name": name, "identity_id": who.identity}
        )
        assert made.status_code == 201

    merged = (await api.client.post(f"{IDENTITIES}/merge", json=body(keep, lose))).json()

    assert merged["person"]["display_name"] == "Alice"


async def test_a_merge_is_refused_when_it_is_malformed_stale_or_names_nobody(
    api: Api, new_id: SeededUUIDs
) -> None:
    a, b = person(api, new_id), person(api, new_id)
    one = {
        "identities": [{"id": a.identity, "revision": a.revision}],
        "preferred_identity_id": a.identity,
    }
    outside = {**body(a, b), "preferred_identity_id": str(uuid.uuid4())}
    twice = {
        "identities": [{"id": a.identity, "revision": 1}] * 2,
        "preferred_identity_id": a.identity,
    }
    as_member = {"id": b.identity, "revision": b.revision}
    listed_twice = {
        "identities": [{"id": a.identity, "revision": a.revision}, as_member, as_member],
        "preferred_identity_id": a.identity,
    }
    for bad in (one, outside, twice, listed_twice):
        error(await api.client.post(f"{IDENTITIES}/merge", json=bad), 422, "INVALID_MERGE")

    stale = {**body(a, b), "identities": [
        {"id": a.identity, "revision": a.revision}, {"id": b.identity, "revision": a.revision + 5}
    ]}  # fmt: skip
    error(await api.client.post(f"{IDENTITIES}/merge", json=stale), 409, "IDENTITY_CHANGED")
    ghost = Person(str(uuid.uuid4()), 1, [])
    error(
        await api.client.post(f"{IDENTITIES}/merge", json=body(a, ghost)), 404, "IDENTITY_NOT_FOUND"
    )

    assert (await api.client.get(f"{IDENTITIES}/{b.identity}")).status_code == 200  # nobody moved


async def test_a_merge_of_more_than_two_keeps_one_survivor(api: Api, new_id: SeededUUIDs) -> None:
    keep, second, third = person(api, new_id), person(api, new_id), person(api, new_id)

    merged = await api.client.post(f"{IDENTITIES}/merge", json=body(keep, second, third))

    assert merged.json()["occurrence_count"] == 3
    assert (await api.client.get(IDENTITIES)).json()["items"][0]["id"] == keep.identity


async def test_splitting_moves_the_chosen_faces_to_a_new_identity(
    api: Api, new_id: SeededUUIDs
) -> None:
    mine = person(api, new_id, 2)
    subscription = api.backend.events.subscribe()
    try:
        split = await api.client.post(
            f"{IDENTITIES}/{mine.identity}/split", json={"occurrence_ids": [mine.occurrences[0]]}
        )
        announced = subscription.queue.qsize()
    finally:
        api.backend.events.unsubscribe(subscription)

    assert split.status_code == 201
    created = split.json()
    assert created["id"] != mine.identity
    assert created["occurrence_count"] == 1
    assert announced == 2  # the new person and the one it left
    stays = (await api.client.get(f"{IDENTITIES}/{mine.identity}")).json()
    assert stays["occurrence_count"] == 1
    moved = (await api.client.get(f"{IDENTITIES}/{created['id']}/occurrences")).json()["items"]
    assert [o["id"] for o in moved] == [mine.occurrences[0]]


async def test_splitting_off_every_face_leaves_the_first_identity_active(
    api: Api, new_id: SeededUUIDs
) -> None:
    mine = person(api, new_id, 2)

    split = await api.client.post(
        f"{IDENTITIES}/{mine.identity}/split", json={"occurrence_ids": mine.occurrences}
    )

    assert split.json()["occurrence_count"] == 2
    left = (await api.client.get(f"{IDENTITIES}/{mine.identity}")).json()
    assert (left["state"], left["occurrence_count"]) == ("ACTIVE", 0)


async def test_a_split_is_refused_for_bad_input_and_changes_nothing(
    api: Api, new_id: SeededUUIDs
) -> None:
    mine, other = person(api, new_id, 2), person(api, new_id)
    url = f"{IDENTITIES}/{mine.identity}/split"

    error(await api.client.post(url, json={"occurrence_ids": []}), 422, "INVALID_SPLIT")
    error(
        await api.client.post(url, json={"occurrence_ids": [other.occurrences[0]]}),
        404,
        "OCCURRENCE_NOT_FOUND",
    )
    error(
        await api.client.post(url, json={"occurrence_ids": [str(uuid.uuid4())]}),
        404,
        "OCCURRENCE_NOT_FOUND",
    )
    error(
        await api.client.post(
            f"{IDENTITIES}/{uuid.uuid4()}/split", json={"occurrence_ids": mine.occurrences}
        ),
        404,
        "IDENTITY_NOT_FOUND",
    )

    assert (await api.client.get(f"{IDENTITIES}/{mine.identity}")).json()["occurrence_count"] == 2


async def test_a_face_that_is_no_longer_current_cannot_be_chosen(
    api: Api, new_id: SeededUUIDs
) -> None:
    mine = person(api, new_id)
    assert api.backend.library is not None
    with api.backend.library.session_factory() as session:
        build = ModelFactory(session, api.clock, new_id)
        old = build.occurrence(identity_id=uuid.UUID(mine.identity), state="SUPERSEDED")
        session.commit()
        old_id = str(old.id)

    response = await api.client.post(
        f"{IDENTITIES}/{mine.identity}/split", json={"occurrence_ids": [old_id]}
    )

    error(response, 404, "OCCURRENCE_NOT_FOUND")


async def test_a_face_with_nothing_to_split_off_is_refused(api: Api, new_id: SeededUUIDs) -> None:
    assert api.backend.library is not None
    mine = person(api, new_id)
    with api.backend.library.session_factory() as session:
        build = ModelFactory(session, api.clock, new_id)
        bare = build.occurrence(
            identity_id=uuid.UUID(mine.identity), state="ACTIVE"
        )  # no representation
        session.commit()
        bare_id = str(bare.id)

    response = await api.client.post(
        f"{IDENTITIES}/{mine.identity}/split", json={"occurrence_ids": [bare_id]}
    )

    error(response, 422, "INVALID_SPLIT")


async def test_a_split_that_would_cut_a_face_in_two_is_a_conflict_and_changes_nothing(
    api: Api, new_id: SeededUUIDs
) -> None:
    assert api.backend.library is not None
    with api.backend.library.session_factory() as session:
        build = ModelFactory(session, api.clock, new_id)
        identity = build.identity()
        shared, extra = build.observation(), build.observation()
        for key, observation in ((1, shared), (2, extra)):
            build.representation(observation, state="ACTIVE", ann_key=key, identity_id=identity.id)
        # a face resting on two observations, and a second face resting on one of them
        wide = build.occurrence(shared, identity_id=identity.id, state="ACTIVE")
        for ordinal, observation in enumerate((shared, extra)):
            build.add(
                OccurrenceObservation(
                    occurrence_id=wide.id, observation_id=observation.id, ordinal=ordinal
                )
            )
        narrow = build.occurrence(shared, identity_id=identity.id, state="ACTIVE")
        session.commit()
        ids = (str(identity.id), str(wide.id), str(narrow.id))

    refused = await api.client.post(
        f"{IDENTITIES}/{ids[0]}/split", json={"occurrence_ids": [ids[2]]}
    )

    body_ = error(refused, 409, "SPLIT_CONFLICT")
    assert body_["details"]["occurrence_ids"] == [ids[1]]  # the face it would have cut in two
    assert (await api.client.get(f"{IDENTITIES}/{ids[0]}")).json()["occurrence_count"] == 2
    both = await api.client.post(
        f"{IDENTITIES}/{ids[0]}/split", json={"occurrence_ids": [ids[1], ids[2]]}
    )
    assert both.status_code == 201  # choosing everything that rests on it resolves the conflict
