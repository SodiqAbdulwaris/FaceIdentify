"""Confirming, moving and separating a face through the API (M5 step 2; TST-054).

Faces are built directly in the library (the pipeline that makes them is tested elsewhere), so what
is checked here is the correction commands: what they return, what they refuse, and that they
announce a change only when one was made.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import select

from backend.app.identities.models import Evidence
from tests.factories.models import ModelFactory
from tests.fixtures.api import Api, error
from tests.fixtures.deterministic import SeededUUIDs

OCCURRENCES = "/api/v1/occurrences"
IDENTITIES = "/api/v1/identities"


@dataclass
class Faces:
    identity: str
    other: str
    occurrence: str


def faces(api: Api, new_id: SeededUUIDs) -> Faces:
    assert api.backend.library is not None
    with api.backend.library.session_factory() as session:
        build = ModelFactory(session, api.clock, new_id)
        mine, other = build.identity(), build.identity()
        observation = build.observation()
        build.representation(observation, state="ACTIVE", ann_key=1, identity_id=mine.id)
        occurrence = build.occurrence(observation, identity_id=mine.id, state="ACTIVE")
        mine.representative_observation_id = observation.id
        session.commit()
        return Faces(str(mine.id), str(other.id), str(occurrence.id))


def kinds(api: Api) -> list[object]:
    assert api.backend.library is not None
    with api.backend.library.session_factory() as session:
        return [e.payload_json.get("action") for e in session.scalars(
            select(Evidence).where(Evidence.kind == "USER_CORRECTION")
        )]  # fmt: skip


async def test_a_face_can_be_read_and_confirmed(api: Api, new_id: SeededUUIDs) -> None:
    f = faces(api, new_id)
    seen = (await api.client.get(f"{OCCURRENCES}/{f.occurrence}")).json()
    assert seen["identity_id"] == f.identity

    confirmed = await api.client.post(
        f"{OCCURRENCES}/{f.occurrence}/confirm", json={"expected_identity_id": f.identity}
    )

    assert confirmed.status_code == 200
    assert confirmed.json() == seen
    assert kinds(api) == ["CONFIRM"]


async def test_a_face_can_be_moved_to_another_identity(api: Api, new_id: SeededUUIDs) -> None:
    f = faces(api, new_id)

    moved = await api.client.post(
        f"{OCCURRENCES}/{f.occurrence}/reassign",
        json={"expected_identity_id": f.identity, "identity_id": f.other},
    )

    assert moved.status_code == 200
    assert moved.json()["identity_id"] == f.other
    assert (await api.client.get(f"{OCCURRENCES}/{f.occurrence}")).json()["identity_id"] == f.other
    assert kinds(api) == ["REASSIGN"]


async def test_a_face_can_be_separated_into_a_new_identity(api: Api, new_id: SeededUUIDs) -> None:
    f = faces(api, new_id)

    separated = await api.client.post(
        f"{OCCURRENCES}/{f.occurrence}/reassign",
        json={"expected_identity_id": f.identity, "identity_id": None},
    )

    created = separated.json()["identity_id"]
    assert separated.status_code == 200
    assert created not in (f.identity, f.other)
    assert (await api.client.get(f"{IDENTITIES}/{created}")).status_code == 200
    assert kinds(api) == ["SEPARATE"]


async def test_a_stale_view_is_refused_and_changes_nothing(api: Api, new_id: SeededUUIDs) -> None:
    f = faces(api, new_id)
    await api.client.post(
        f"{OCCURRENCES}/{f.occurrence}/reassign",
        json={"expected_identity_id": f.identity, "identity_id": f.other},
    )
    subscription = api.backend.events.subscribe()
    try:
        again = await api.client.post(
            f"{OCCURRENCES}/{f.occurrence}/reassign",
            json={"expected_identity_id": f.identity, "identity_id": None},
        )
        stale = await api.client.post(
            f"{OCCURRENCES}/{f.occurrence}/confirm", json={"expected_identity_id": f.identity}
        )
        assert subscription.queue.empty()  # a refusal announces nothing
    finally:
        api.backend.events.unsubscribe(subscription)

    error(again, 409, "OCCURRENCE_MOVED")
    error(stale, 409, "OCCURRENCE_MOVED")
    assert kinds(api) == ["REASSIGN"]


async def test_the_refusals_for_unknown_things_and_a_move_to_the_same_identity(
    api: Api, new_id: SeededUUIDs
) -> None:
    f = faces(api, new_id)
    nobody = str(uuid.uuid4())
    body = {"expected_identity_id": f.identity}
    error(await api.client.get(f"{OCCURRENCES}/{nobody}"), 404, "OCCURRENCE_NOT_FOUND")
    error(
        await api.client.post(f"{OCCURRENCES}/{nobody}/confirm", json=body),
        404,
        "OCCURRENCE_NOT_FOUND",
    )
    error(
        await api.client.post(
            f"{OCCURRENCES}/{nobody}/reassign", json={**body, "identity_id": None}
        ),
        404,
        "OCCURRENCE_NOT_FOUND",
    )
    error(
        await api.client.post(
            f"{OCCURRENCES}/{f.occurrence}/reassign", json={**body, "identity_id": nobody}
        ),
        404,
        "IDENTITY_NOT_FOUND",
    )
    error(
        await api.client.post(
            f"{OCCURRENCES}/{f.occurrence}/reassign", json={**body, "identity_id": f.identity}
        ),
        409,
        "FACE_NOT_CORRECTABLE",
    )
    assert kinds(api) == []


async def test_a_face_whose_identity_is_not_active_cannot_be_confirmed(
    api: Api, new_id: SeededUUIDs
) -> None:
    assert api.backend.library is not None
    with api.backend.library.session_factory() as session:
        build = ModelFactory(session, api.clock, new_id)
        pending = build.identity(state="PENDING")
        occurrence = build.occurrence(identity_id=pending.id, state="ACTIVE")
        session.commit()
        ids = (str(pending.id), str(occurrence.id))

    response = await api.client.post(
        f"{OCCURRENCES}/{ids[1]}/confirm", json={"expected_identity_id": ids[0]}
    )

    error(response, 409, "FACE_NOT_CORRECTABLE")


async def test_corrections_are_announced(api: Api, new_id: SeededUUIDs) -> None:
    f = faces(api, new_id)
    subscription = api.backend.events.subscribe()
    try:
        await api.client.post(
            f"{OCCURRENCES}/{f.occurrence}/confirm", json={"expected_identity_id": f.identity}
        )
        await api.client.post(
            f"{OCCURRENCES}/{f.occurrence}/reassign",
            json={"expected_identity_id": f.identity, "identity_id": f.other},
        )
        events = []
        while not subscription.queue.empty():
            events.append(subscription.queue.get_nowait())
    finally:
        api.backend.events.unsubscribe(subscription)

    assert [(e["type"], e["resource"]) for e in events] == [
        ("occurrence.updated", {"type": "occurrence", "id": f.occurrence})
    ] * 2
