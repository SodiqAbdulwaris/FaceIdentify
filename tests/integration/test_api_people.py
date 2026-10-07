"""Naming an identity, and reading, renaming, linking and unlinking people through the API (M5).

The routes run on the real application and a real library; identities are created directly (the
pipeline that makes them is tested elsewhere), so what is checked here is the people commands.
"""

import uuid
from typing import Any

from sqlalchemy import select, update

from backend.app.identities.models import Evidence
from backend.app.people.models import Person
from tests.factories.models import ModelFactory
from tests.fixtures.api import Api, error
from tests.fixtures.deterministic import SeededUUIDs

PEOPLE = "/api/v1/people"
IDENTITIES = "/api/v1/identities"


def identity_ids(api: Api, new_id: SeededUUIDs, count: int = 1, **kw: Any) -> list[str]:
    assert api.backend.library is not None
    with api.backend.library.session_factory() as session:
        build = ModelFactory(session, api.clock, new_id)
        ids = [str(build.identity(**kw).id) for _ in range(count)]
        session.commit()
    return ids


async def named(api: Api, identity_id: str, name: str = "Alice") -> dict[str, Any]:
    response = await api.client.post(
        PEOPLE, json={"display_name": name, "identity_id": identity_id}
    )
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()
    return created


async def test_naming_an_identity_creates_the_person_and_shows_on_the_identity(
    api: Api, new_id: SeededUUIDs
) -> None:
    [identity] = identity_ids(api, new_id)

    person = await named(api, identity, "  Alice Smith  ")

    assert person["display_name"] == "Alice Smith"
    assert (person["revision"], person["identity_count"]) == (1, 1)
    seen = (await api.client.get(f"{IDENTITIES}/{identity}")).json()
    assert seen["person"] == {
        "id": person["id"],
        "display_name": "Alice Smith",
        "revision": 1,
    }
    assert (await api.client.get(f"{PEOPLE}/{person['id']}")).json() == person
    assert (await api.client.get(PEOPLE)).json()["items"] == [person]


async def test_an_unnamed_identity_has_no_person(api: Api, new_id: SeededUUIDs) -> None:
    [identity] = identity_ids(api, new_id)
    assert (await api.client.get(f"{IDENTITIES}/{identity}")).json()["person"] is None
    assert (await api.client.get(PEOPLE)).json()["items"] == []


async def test_naming_refuses_a_bad_name_an_unknown_identity_and_a_named_one(
    api: Api, new_id: SeededUUIDs
) -> None:
    [identity] = identity_ids(api, new_id)
    blank = await api.client.post(PEOPLE, json={"display_name": "   ", "identity_id": identity})
    assert blank.status_code == 422
    missing = {"display_name": "Bob", "identity_id": str(uuid.uuid4())}
    error(await api.client.post(PEOPLE, json=missing), 404, "IDENTITY_NOT_FOUND")
    await named(api, identity)
    again = await api.client.post(PEOPLE, json={"display_name": "Bob", "identity_id": identity})
    error(again, 409, "IDENTITY_ALREADY_NAMED")
    assert len((await api.client.get(PEOPLE)).json()["items"]) == 1  # nothing was made for Bob


async def test_a_pending_identity_cannot_be_named(api: Api, new_id: SeededUUIDs) -> None:
    [identity] = identity_ids(api, new_id, state="PENDING")
    response = await api.client.post(PEOPLE, json={"display_name": "A", "identity_id": identity})
    error(response, 404, "IDENTITY_NOT_FOUND")


async def test_renaming_checks_the_revision_and_leaves_one_event(
    api: Api, new_id: SeededUUIDs
) -> None:
    [identity] = identity_ids(api, new_id)
    person = await named(api, identity)
    url = f"{PEOPLE}/{person['id']}"

    renamed = await api.client.patch(url, json={"display_name": "Alicia", "expected_revision": 1})
    assert renamed.status_code == 200
    assert (renamed.json()["display_name"], renamed.json()["revision"]) == ("Alicia", 2)
    stale = await api.client.patch(url, json={"display_name": "Ali", "expected_revision": 1})
    error(stale, 409, "PERSON_REVISION_CONFLICT")
    assert (await api.client.get(url)).json()["display_name"] == "Alicia"
    missing = f"{PEOPLE}/{uuid.uuid4()}"
    error(
        await api.client.patch(missing, json={"display_name": "X", "expected_revision": 1}),
        404,
        "PERSON_NOT_FOUND",
    )
    assert api.backend.library is not None
    with api.backend.library.session_factory() as session:
        kinds = [e.kind for e in session.scalars(select(Evidence))]
    assert kinds.count("PERSON_RENAMED") == 1


async def test_another_identity_can_be_linked_to_the_person_and_unlinked(
    api: Api, new_id: SeededUUIDs
) -> None:
    first, second = identity_ids(api, new_id, count=2)
    person = await named(api, first)
    url = f"{PEOPLE}/{person['id']}"

    linked = await api.client.post(f"{url}/assign-identity", json={"identity_id": second})
    assert linked.json()["identity_count"] == 2
    assert (await api.client.get(f"{IDENTITIES}/{second}")).json()["person"]["id"] == person["id"]
    unlinked = await api.client.post(f"{url}/remove-identity", json={"identity_id": second})
    assert unlinked.json()["identity_count"] == 1
    assert (await api.client.get(f"{IDENTITIES}/{second}")).json()["person"] is None
    again = await api.client.post(f"{url}/remove-identity", json={"identity_id": second})
    error(again, 409, "IDENTITY_NOT_LINKED")


async def test_linking_refuses_an_identity_already_linked_there_and_unknown_things(
    api: Api, new_id: SeededUUIDs
) -> None:
    [identity] = identity_ids(api, new_id)
    person = await named(api, identity)
    url = f"{PEOPLE}/{person['id']}"

    same = await api.client.post(f"{url}/assign-identity", json={"identity_id": identity})
    error(same, 409, "IDENTITY_NOT_ASSIGNABLE")
    unknown = {"identity_id": str(uuid.uuid4())}
    error(await api.client.post(f"{url}/assign-identity", json=unknown), 404, "IDENTITY_NOT_FOUND")
    error(await api.client.post(f"{url}/remove-identity", json=unknown), 404, "IDENTITY_NOT_FOUND")
    elsewhere = f"{PEOPLE}/{uuid.uuid4()}"
    error(
        await api.client.post(f"{elsewhere}/assign-identity", json={"identity_id": identity}),
        404,
        "PERSON_NOT_FOUND",
    )
    assert (await api.client.get(f"{elsewhere}")).status_code == 404


async def test_the_people_list_pages_newest_first(api: Api, new_id: SeededUUIDs) -> None:
    first, second = identity_ids(api, new_id, count=2)
    older = await named(api, first, "Older")
    api.clock.advance(seconds=1)
    newer = await named(api, second, "Newer")

    head = (await api.client.get(PEOPLE, params={"limit": 1})).json()
    tail = (
        await api.client.get(PEOPLE, params={"limit": 1, "cursor": head["page"]["next_cursor"]})
    ).json()

    assert [p["id"] for p in head["items"] + tail["items"]] == [newer["id"], older["id"]]
    assert (head["page"]["has_more"], tail["page"]["has_more"]) == (True, False)


async def test_an_identity_cannot_be_unlinked_through_another_person(
    api: Api, new_id: SeededUUIDs
) -> None:
    first, second = identity_ids(api, new_id, count=2)
    alice = await named(api, first, "Alice")
    bob = await named(api, second, "Bob")

    wrong = await api.client.post(
        f"{PEOPLE}/{bob['id']}/remove-identity", json={"identity_id": first}
    )

    error(wrong, 409, "IDENTITY_NOT_LINKED")
    assert (await api.client.get(f"{IDENTITIES}/{first}")).json()["person"]["id"] == alice["id"]


async def test_a_person_who_is_not_active_is_not_found(api: Api, new_id: SeededUUIDs) -> None:
    [identity] = identity_ids(api, new_id)
    person = await named(api, identity)
    assert api.backend.library is not None
    with api.backend.library.session_factory() as session:
        session.execute(update(Person).values(state="RECYCLED", recycled_at=api.clock()))
        session.commit()

    error(await api.client.get(f"{PEOPLE}/{person['id']}"), 404, "PERSON_NOT_FOUND")
    assert (await api.client.get(PEOPLE)).json()["items"] == []


async def test_every_change_to_a_person_is_announced_and_a_refusal_is_not(
    api: Api, new_id: SeededUUIDs
) -> None:
    first, second = identity_ids(api, new_id, count=2)
    subscription = api.backend.events.subscribe()
    try:
        person = await named(api, first)
        url = f"{PEOPLE}/{person['id']}"
        await api.client.patch(url, json={"display_name": "Alicia", "expected_revision": 1})
        await api.client.post(f"{url}/assign-identity", json={"identity_id": second})
        await api.client.post(f"{url}/remove-identity", json={"identity_id": second})
        await api.client.patch(url, json={"display_name": "Late", "expected_revision": 1})  # stale
        await api.client.post(PEOPLE, json={"display_name": "Again", "identity_id": first})  # named

        events = []
        while not subscription.queue.empty():
            events.append(subscription.queue.get_nowait())
    finally:
        api.backend.events.unsubscribe(subscription)

    assert [(e["type"], e["resource"]) for e in events] == [
        ("person.updated", {"type": "person", "id": person["id"]})
    ] * 4
