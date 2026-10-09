"""Confirming, moving and separating a face through the API (M5 step 2; TST-054).

Faces are built directly in the library (the pipeline that makes them is tested elsewhere), so what
is checked here is the correction commands: what they return, what they refuse, and that they
announce a change only when one was made.
"""

import sqlite3
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import event, select, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from backend.app.identities.models import Evidence, EvidenceCandidate, EvidenceRepresentation
from backend.app.memory.models import Representation
from backend.app.processing.models import ProcessingRun
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


async def test_a_stale_view_is_reported_before_an_unusable_target(
    api: Api, new_id: SeededUUIDs
) -> None:
    f = faces(api, new_id)
    await api.client.post(
        f"{OCCURRENCES}/{f.occurrence}/reassign",
        json={"expected_identity_id": f.identity, "identity_id": f.other},
    )

    response = await api.client.post(
        f"{OCCURRENCES}/{f.occurrence}/reassign",
        json={"expected_identity_id": f.identity, "identity_id": str(uuid.uuid4())},
    )

    error(response, 409, "OCCURRENCE_MOVED")


async def test_a_busy_database_retries_the_whole_correction_once(
    api: Api, new_id: SeededUUIDs
) -> None:
    f = faces(api, new_id)
    failures = {"left": 1}

    def fail_first_commit(_session: Session) -> None:
        if failures["left"]:
            failures["left"] -= 1
            inner = sqlite3.OperationalError("database is locked")
            inner.sqlite_errorcode = sqlite3.SQLITE_BUSY
            raise OperationalError("COMMIT", {}, inner)

    event.listen(Session, "before_commit", fail_first_commit)
    subscription = api.backend.events.subscribe()
    try:
        response = await api.client.post(
            f"{OCCURRENCES}/{f.occurrence}/reassign",
            json={"expected_identity_id": f.identity, "identity_id": f.other},
        )
        announced = subscription.queue.qsize()
    finally:
        event.remove(Session, "before_commit", fail_first_commit)
        api.backend.events.unsubscribe(subscription)

    assert response.status_code == 200
    assert failures["left"] == 0  # the first commit really failed
    assert kinds(api) == ["REASSIGN"]  # one evidence row, not two
    assert response.json()["identity_id"] == f.other
    assert announced == 1  # announced once, after the commit that held


# --- faces recognition declined to place -------------------------------------------------------


@dataclass
class Unresolved:
    source: str
    representation: str
    observation: str
    alice: str
    bob: str


def unresolved(api: Api, new_id: SeededUUIDs) -> Unresolved:
    assert api.backend.library is not None
    with api.backend.library.session_factory() as session:
        build = ModelFactory(session, api.clock, new_id)
        alice, bob = build.identity(), build.identity()
        observation = build.observation(state="ACTIVE", bbox_x=0.1, bbox_y=0.2, bbox_width=0.3)
        representation = build.representation(
            observation, state="ACTIVE", ann_key=1, identity_id=None
        )
        abstention = build.evidence(kind="RECOGNITION_ABSTAINED", source_id=observation.source_id)
        build.add(
            EvidenceRepresentation(
                evidence_id=abstention.id, representation_id=representation.id, role="SUBJECT"
            )
        )
        others = [build.identity().id for _ in range(3)]
        hidden = build.identity(state="PENDING").id  # not a person anyone can be told it is
        ranked = (
            (bob.id, 0.38), (alice.id, 0.41), (alice.id, 0.2), (hidden, 0.9),
            (others[0], 0.1), (others[1], 0.09), (others[2], 0.08),
        )  # fmt: skip
        for rank, (who, score) in enumerate(ranked):
            seen_with = build.representation(  # the face this candidate was compared with
                build.observation(
                    session.get(ProcessingRun, observation.processing_run_id), state="SUPERSEDED"
                ),
                state="ACTIVE", ann_key=10 + rank, identity_id=who,
            )  # fmt: skip
            build.add(
                EvidenceCandidate(
                    evidence_id=abstention.id, rank=rank, identity_id=who, raw_similarity=score,
                    decision="CANDIDATE", details_json=compared_with(seen_with.id, score),
                )
            )  # fmt: skip
        stray = build.evidence(kind="RECOGNITION_ABSTAINED")  # cites this face only as a candidate
        build.add(
            EvidenceRepresentation(
                evidence_id=stray.id, representation_id=representation.id, role="CANDIDATE"
            )
        )
        build.add(
            EvidenceCandidate(
                evidence_id=stray.id, rank=0, identity_id=build.identity().id,
                raw_similarity=0.99, decision="CANDIDATE", details_json={},
            )
        )  # fmt: skip
        session.commit()
        return Unresolved(
            str(observation.source_id), str(representation.id), str(observation.id),
            str(alice.id), str(bob.id),
        )  # fmt: skip


def compared_with(representation_id: uuid.UUID, similarity: float) -> dict[str, Any]:
    """What a recorded candidate keeps of the face it was compared with."""
    return {"members": [{"representation_id": str(representation_id), "similarity": similarity}]}


async def test_unresolved_faces_are_listed_with_who_they_resembled(
    api: Api, new_id: SeededUUIDs
) -> None:
    u = unresolved(api, new_id)

    listed = (await api.client.get(f"/api/v1/sources/{u.source}/unresolved-faces")).json()

    [face] = listed["items"]
    assert face["representation_id"] == u.representation
    assert face["observation_id"] == u.observation
    assert face["bounding_box"]["x"] == 0.1
    assert [(p["identity_id"], p["similarity"]) for p in face["likely"][:2]] == [
        (u.alice, 0.41),
        (u.bob, 0.38),
    ]  # best first, each person once, never a person who is not active
    assert len(face["likely"]) == 3  # at most three hints
    error(
        await api.client.get(f"/api/v1/sources/{uuid.uuid4()}/unresolved-faces"),
        404,
        "SOURCE_NOT_FOUND",
    )


async def likely_after_changing_alices_evidence(
    api: Api,
    u: Unresolved,
    members: list[tuple[str, float]],
    *,
    erase_support: bool = False,
    reassign_support: bool = False,
) -> list[tuple[str, float]]:
    """Alice's recorded candidate is made of `members`: `support` and `second` are faces of hers
    that exist, `gone` one that does not. `erase_support` erases `support`'s memory and
    `reassign_support` hands it to Bob. What the unresolved-face list then says she resembled."""
    assert api.backend.library is not None
    with api.backend.library.session_factory() as session:
        [support, second] = session.scalars(
            select(Representation.id)
            .where(Representation.identity_id == uuid.UUID(u.alice))
            .order_by(Representation.ann_key)
        )
        if reassign_support:
            session.execute(
                update(Representation)
                .where(Representation.id == support)
                .values(identity_id=uuid.UUID(u.bob))
            )
        if erase_support:
            session.execute(
                update(Representation)
                .where(Representation.id == support)
                .values(state="ERASED", vector=None, ann_key=None)
            )
        for candidate in session.scalars(
            select(EvidenceCandidate).where(EvidenceCandidate.identity_id == uuid.UUID(u.alice))
        ):
            candidate.details_json = {
                "members": [
                    {
                        "representation_id": str(
                            {
                                "support": support,
                                "second": second,
                                "gone": uuid.uuid4(),
                            }[which]
                        ),
                        "similarity": score,
                    }
                    for which, score in members
                ]
            }
        session.commit()
    [face] = (await api.client.get(f"/api/v1/sources/{u.source}/unresolved-faces")).json()["items"]
    return [(p["identity_id"], p["similarity"]) for p in face["likely"]]


async def test_a_hint_needs_a_face_that_still_exists(api: Api, new_id: SeededUUIDs) -> None:
    u = unresolved(api, new_id)
    seen = await likely_after_changing_alices_evidence(api, u, [("gone", 0.9)])

    assert u.alice not in [who for who, _ in seen]  # the only face that supported her was deleted
    assert u.bob in [who for who, _ in seen]


async def test_a_hint_is_not_supported_by_a_face_whose_memory_was_erased(
    api: Api, new_id: SeededUUIDs
) -> None:
    u = unresolved(api, new_id)

    seen = await likely_after_changing_alices_evidence(
        api, u, [("support", 0.4)], erase_support=True
    )

    assert u.alice not in [who for who, _ in seen]


async def test_a_hint_is_not_supported_by_a_face_that_now_belongs_to_someone_else(
    api: Api, new_id: SeededUUIDs
) -> None:
    u = unresolved(api, new_id)

    seen = await likely_after_changing_alices_evidence(
        api, u, [("support", 0.4)], reassign_support=True
    )

    assert u.alice not in [who for who, _ in seen]  # that face was moved to Bob since


async def test_a_hint_takes_the_best_of_the_faces_that_remain(
    api: Api, new_id: SeededUUIDs
) -> None:
    u = unresolved(api, new_id)

    seen = await likely_after_changing_alices_evidence(
        api, u, [("support", 0.30), ("second", 0.35), ("gone", 0.99)]
    )

    assert [score for _, score in seen][:2] == [0.38, 0.35]


async def test_a_hint_is_scored_by_the_faces_that_remain(api: Api, new_id: SeededUUIDs) -> None:
    u = unresolved(api, new_id)
    seen = await likely_after_changing_alices_evidence(api, u, [("gone", 0.99), ("support", 0.30)])

    assert [score for _, score in seen][:2] == [0.38, 0.30]  # not her old 0.99, so Bob is first


async def test_an_unresolved_face_becomes_an_occurrence_and_leaves_the_list(
    api: Api, new_id: SeededUUIDs
) -> None:
    u = unresolved(api, new_id)
    subscription = api.backend.events.subscribe()
    try:
        resolved = await api.client.post(
            f"/api/v1/representations/{u.representation}/resolve", json={"identity_id": u.bob}
        )
        announced = subscription.queue.qsize()
    finally:
        api.backend.events.unsubscribe(subscription)

    assert resolved.status_code == 200
    assert resolved.json()["identity_id"] == u.bob
    assert resolved.json()["source_id"] == u.source
    assert announced == 1
    after = (await api.client.get(f"/api/v1/sources/{u.source}/unresolved-faces")).json()
    assert after["items"] == []
    assert kinds(api) == ["RESOLVE"]
    occurrences = (await api.client.get(f"/api/v1/sources/{u.source}/occurrences")).json()
    assert [o["identity_id"] for o in occurrences["items"]] == [u.bob]


async def test_an_unresolved_face_can_be_a_new_person_and_cannot_be_resolved_twice(
    api: Api, new_id: SeededUUIDs
) -> None:
    u = unresolved(api, new_id)
    url = f"/api/v1/representations/{u.representation}/resolve"

    first = await api.client.post(url, json={"identity_id": None})
    again = await api.client.post(url, json={"identity_id": None})

    assert first.status_code == 200
    assert first.json()["identity_id"] not in (u.alice, u.bob)
    error(again, 409, "FACE_NOT_RESOLVABLE")
    assert kinds(api) == ["RESOLVE_NEW"]


async def test_resolving_refuses_unknown_things(api: Api, new_id: SeededUUIDs) -> None:
    u = unresolved(api, new_id)
    url = f"/api/v1/representations/{u.representation}/resolve"

    error(
        await api.client.post(
            f"/api/v1/representations/{uuid.uuid4()}/resolve", json={"identity_id": None}
        ),
        404,
        "FACE_NOT_FOUND",
    )
    error(
        await api.client.post(url, json={"identity_id": str(uuid.uuid4())}),
        404,
        "IDENTITY_NOT_FOUND",
    )
    assert kinds(api) == []


async def test_a_busy_database_retries_a_resolution_once(api: Api, new_id: SeededUUIDs) -> None:
    u = unresolved(api, new_id)
    failures = {"left": 1}

    def fail_first_commit(_session: Session) -> None:
        if failures["left"]:
            failures["left"] -= 1
            inner = sqlite3.OperationalError("database is locked")
            inner.sqlite_errorcode = sqlite3.SQLITE_BUSY
            raise OperationalError("COMMIT", {}, inner)

    event.listen(Session, "before_commit", fail_first_commit)
    subscription = api.backend.events.subscribe()
    try:
        response = await api.client.post(
            f"/api/v1/representations/{u.representation}/resolve", json={"identity_id": u.bob}
        )
        announced = subscription.queue.qsize()
    finally:
        event.remove(Session, "before_commit", fail_first_commit)
        api.backend.events.unsubscribe(subscription)

    assert response.status_code == 200
    assert failures["left"] == 0
    assert kinds(api) == ["RESOLVE"]  # one evidence row, one occurrence
    occurrences = (await api.client.get(f"/api/v1/sources/{u.source}/occurrences")).json()
    assert len(occurrences["items"]) == 1
    assert announced == 1
