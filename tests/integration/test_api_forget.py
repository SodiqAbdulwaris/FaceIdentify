"""Forgetting an identity and a person through the API (M5 step 4c; API section 8.3; TST-059).

The library really processes the images (planted perception), so what is forgotten has real vectors.
Forgetting is authoritative at once: the identity is gone from every view and cannot be recognised,
the media stays, a named Person keeps their name. `204` means every vector is gone; `202` means the
cleanup is still owed (and the identity is already forgotten).
"""

from typing import Any

import pytest
from sqlalchemy import select

from backend.app.memory.models import Representation
from tests.fixtures.api import Api, error
from tests.integration.test_api_memory import processed

IDENTITIES = "/api/v1/identities"
PEOPLE = "/api/v1/people"
SOURCES = "/api/v1/sources"


async def only_identity(api: Api) -> dict[str, Any]:
    [identity] = (await api.client.get(IDENTITIES)).json()["items"]
    return identity  # type: ignore[no-any-return]


def drained(api: Api, subscription: Any) -> list[str]:
    seen = []
    while not subscription.queue.empty():
        kind = subscription.queue.get_nowait()["type"]
        if kind.startswith(("identity.", "person.")):  # (a finished run may still be announcing)
            seen.append(kind)
    return seen


async def test_forgetting_an_identity_removes_it_from_every_view_and_keeps_the_media(
    processing_api: Api,
) -> None:
    api = processing_api
    source = await processed(api, "alice.png")
    identity = await only_identity(api)
    subscription = api.backend.events.subscribe()
    try:
        forgotten = await api.client.post(
            f"{IDENTITIES}/{identity['id']}/forget",
            json={"expected_revision": identity["revision"]},
        )
        again = await api.client.post(
            f"{IDENTITIES}/{identity['id']}/forget", json={"expected_revision": 1}
        )
        events = drained(api, subscription)
    finally:
        api.backend.events.unsubscribe(subscription)

    assert (forgotten.status_code, again.status_code) == (204, 204)  # a repeat is harmless
    assert forgotten.content == b""
    assert events == ["identity.updated"]  # announced once, for the change only
    assert (await api.client.get(IDENTITIES)).json()["items"] == []
    error(await api.client.get(f"{IDENTITIES}/{identity['id']}"), 404, "IDENTITY_NOT_FOUND")
    assert (await api.client.get(f"{SOURCES}/{source['id']}/occurrences")).json()["items"] == []
    assert (await api.client.get(f"{SOURCES}/{source['id']}")).json()["state"] == "ACTIVE"
    assert (await api.client.get(f"{SOURCES}/{source['id']}/media")).status_code == 200
    assert api.backend.library is not None
    with api.backend.library.session_factory() as session:
        assert {r.state for r in session.scalars(select(Representation))} == {"ERASED"}
        assert all(r.vector is None for r in session.scalars(select(Representation)))


async def test_a_changed_or_unknown_identity_is_refused(processing_api: Api) -> None:
    api = processing_api
    await processed(api, "alice.png")
    identity = await only_identity(api)
    unknown = "00000000-0000-0000-0000-00000000dead"

    stale = await api.client.post(
        f"{IDENTITIES}/{identity['id']}/forget",
        json={"expected_revision": identity["revision"] + 3},
    )

    error(stale, 409, "IDENTITY_CHANGED")
    error(
        await api.client.post(f"{IDENTITIES}/{unknown}/forget", json={"expected_revision": 1}),
        404,
        "IDENTITY_NOT_FOUND",
    )
    assert (await only_identity(api))["id"] == identity["id"]  # nothing was forgotten


async def test_forgetting_a_person_keeps_their_name_and_forgets_their_faces(
    processing_api: Api,
) -> None:
    api = processing_api
    await processed(api, "alice.png")
    identity = await only_identity(api)
    named = await api.client.post(
        PEOPLE, json={"display_name": "Ada", "identity_id": identity["id"]}
    )
    person = named.json()
    subscription = api.backend.events.subscribe()
    try:
        forgotten = await api.client.post(f"{PEOPLE}/{person['id']}/forget")
        again = await api.client.post(f"{PEOPLE}/{person['id']}/forget")
        events = drained(api, subscription)
    finally:
        api.backend.events.unsubscribe(subscription)

    assert (forgotten.status_code, again.status_code) == (204, 204)
    assert events == ["identity.updated"]
    kept = (await api.client.get(f"{PEOPLE}/{person['id']}")).json()
    assert (kept["display_name"], kept["identity_count"]) == ("Ada", 0)  # named, without any face
    assert (await api.client.get(IDENTITIES)).json()["items"] == []
    unknown = "00000000-0000-0000-0000-00000000dead"
    error(await api.client.post(f"{PEOPLE}/{unknown}/forget"), 404, "PERSON_NOT_FOUND")


async def test_cleanup_still_owed_is_reported_and_the_identity_is_already_forgotten(
    processing_api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = processing_api
    await processed(api, "alice.png")
    identity = await only_identity(api)
    monkeypatch.setattr("backend.app.memory.erasure.truncate_wal", lambda *_a, **_k: False)

    pending = await api.client.post(
        f"{IDENTITIES}/{identity['id']}/forget", json={"expected_revision": identity["revision"]}
    )

    assert pending.status_code == 202
    assert any("write-ahead log" in item for item in pending.json()["outstanding"])
    assert (await api.client.get(IDENTITIES)).json()["items"] == []  # unrecognizable already
    readiness = (await api.client.get("/readiness")).json()
    assert readiness["capabilities"]["recovery"] == "DEGRADED"  # the owed work stays visible
    monkeypatch.undo()

    settled = await api.client.post(
        f"{IDENTITIES}/{identity['id']}/forget", json={"expected_revision": 1}
    )

    assert settled.status_code == 204
