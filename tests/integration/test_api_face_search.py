"""Face search through the API (M5 step 5b; TST-056; API section 12.2).

A picture goes in, the people it may show come out, and nothing is remembered: no row, no file, no
job. Perception is planted (no weights); the library, the index and the recognition policy are real.
"""

import hashlib
import threading
from dataclasses import replace
from pathlib import Path
from typing import Any

import anyio
import pytest
from sqlalchemy import select
from sqlalchemy.orm import class_mapper

from backend.api.startup import ProcessingUnavailableError
from backend.app.identities.models import Evidence, Identity
from backend.app.jobs.models import Job
from backend.app.memory.models import Observation, Occurrence, Representation
from backend.app.processing.models import ProcessingRun
from backend.app.runtime.perception_client import (
    Detected,
    FaceVector,
    PerceptionError,
    Represented,
)
from backend.app.sources.models import Artifact, Source
from backend.infrastructure.indexing.representation_index import IndexUnusableError
from backend.ml.contracts.messages import Detection
from backend.ml.contracts.protocol import ContractError, MLErrorCode
from backend.ml.supervisor.supervisor import MLUnavailableError
from tests.fixtures.api import Api, error, processing_app
from tests.integration.test_api_memory import processed
from tests.integration.test_api_search import FACES, face, name_identity

FACE_SEARCH = "/api/v1/search/face"
SOURCES = "/api/v1/sources"
PEOPLE = "/api/v1/people"

MODELS = (
    Source,
    Artifact,
    Observation,
    Representation,
    Occurrence,
    Identity,
    Evidence,
    Job,
    ProcessingRun,
)


def snapshot(api: Api) -> dict[str, Any]:
    """Everything a query could have written: the full contents of every authoritative table and
    the hash of every file in the library (a same-size overwrite or an update shows)."""
    assert api.backend.library is not None
    with api.backend.library.session_factory() as session:
        rows = {
            model.__tablename__: sorted(
                repr({c.key: getattr(row, c.key) for c in class_mapper(model).column_attrs})
                for row in session.scalars(select(model))
            )
            for model in MODELS
        }
    files = {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for root in (api.backend.settings.library_root, api.backend.settings.local_state_root)
        for path in sorted(root.rglob("*"))
        if path.is_file() and not path.name.endswith((".db-wal", ".db-shm", ".lock"))
    }
    return {"rows": rows, "files": files}


async def look(api: Api, vector: Any, name: str = "query.png") -> dict[str, Any]:
    """Search with the picture `name`, which the planted perception sees as `vector`."""
    assert api.perception is not None
    api.perception.vector = vector
    response = await api.client.post(FACE_SEARCH, json={"path": str(api.image(name))})
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def test_a_known_face_finds_its_person_and_shows_the_similarity(processing_api: Api) -> None:
    api = processing_api
    ada = await name_identity(api, await face(api, "ada.png", 0), "Ada")
    await name_identity(api, await face(api, "bob.png", 1), "Bob")

    found = await look(api, FACES[0])

    [only] = found["faces"]
    assert only["index"] == 0
    assert 0 < only["bounding_box"]["width"] <= 1
    names = [p["identity"]["person"]["display_name"] for p in only["possible_people"]]
    assert names[0] == "Ada"  # the nearest first
    assert only["possible_people"][0]["similarity"] > 0.99
    assert only["possible_people"][0]["identity"]["person"]["id"] == ada["id"]
    assert only["retrieval_complete"] is True
    assert only["status"] in {"IDENTITY_ANSWER", "POSSIBLE_PEOPLE"}
    assert found["ranking"]["plan"] == "FACE_QUERY"
    assert (
        found["ranking"]["similarity"] == "COSINE_UNCALIBRATED"
    )  # a similarity, not a probability


async def test_a_face_nobody_resembles_is_not_given_a_name(processing_api: Api) -> None:
    api = processing_api
    await name_identity(api, await face(api, "ada.png", 0), "Ada")

    found = await look(api, FACES[3])

    [only] = found["faces"]
    assert only["status"] != "IDENTITY_ANSWER"
    assert only["identity_answer"] is None
    assert all(p["similarity"] < 0.5 for p in only["possible_people"])


async def test_a_picture_with_no_face_answers_with_nothing(processing_api: Api) -> None:
    api = processing_api
    assert api.perception is not None
    detector = api.perception.detector
    api.perception.detect = lambda pixels: Detected((), detector)  # type: ignore[method-assign]

    response = await api.client.post(FACE_SEARCH, json={"path": str(api.image("empty.png"))})

    assert response.status_code == 200
    assert response.json()["faces"] == []


async def test_a_search_writes_nothing_and_repeating_it_changes_nothing(
    processing_api: Api,
) -> None:
    api = processing_api
    await name_identity(api, await face(api, "ada.png", 0), "Ada")
    before = snapshot(api)

    first = await look(api, FACES[0])
    second = await look(api, FACES[0])
    await look(api, FACES[2])  # a stranger too
    raw = await api.client.post(
        FACE_SEARCH,
        content=api.image("again.png").read_bytes(),
        headers={"content-type": "image/png"},
    )

    assert first == second
    assert raw.status_code == 200
    assert snapshot(api) == before  # no Source, Observation, Identity, Evidence, job, run or file


async def test_the_picture_can_be_sent_as_bytes_or_named_by_path(processing_api: Api) -> None:
    api = processing_api
    await name_identity(api, await face(api, "ada.png", 0), "Ada")
    assert api.perception is not None
    api.perception.vector = FACES[0]
    path = api.image("q.png")

    by_path = await api.client.post(FACE_SEARCH, json={"path": str(path)})
    by_bytes = await api.client.post(
        FACE_SEARCH, content=path.read_bytes(), headers={"content-type": "application/octet-stream"}
    )

    assert by_path.status_code == by_bytes.status_code == 200
    assert by_path.json() == by_bytes.json()


async def test_a_bad_picture_is_refused_plainly(processing_api: Api, tmp_path: Path) -> None:
    api = processing_api
    note = tmp_path / "note.txt"
    note.write_text("not a picture")

    error(
        await api.client.post(FACE_SEARCH, json={"path": str(tmp_path / "nowhere.png")}),
        400,
        "QUERY_IMAGE_UNREADABLE",
    )
    error(await api.client.post(FACE_SEARCH, json={"nope": 1}), 400, "QUERY_IMAGE_UNREADABLE")
    error(
        await api.client.post(FACE_SEARCH, json={"path": str(note)}),
        415,
        "MEDIA_FORMAT_UNSUPPORTED",
    )
    error(
        await api.client.post(
            FACE_SEARCH, content=b"\x89PNG\r\n\x1a\nbroken", headers={"content-type": "image/png"}
        ),
        422,
        "MEDIA_CORRUPT",
    )
    error(
        await api.client.post(
            FACE_SEARCH, content=b"x" * 100_001, headers={"content-type": "image/png"}
        ),
        413,
        "MEDIA_TOO_LARGE",
    )
    error(
        await api.client.post(
            FACE_SEARCH, json={"path": str(api.image("big.png", size=(200, 200)))}
        ),
        413,
        "MEDIA_TOO_LARGE",
    )


async def test_a_forgotten_face_is_never_offered_and_a_recycled_one_still_is(
    processing_api: Api,
) -> None:
    api = processing_api
    forgotten = await name_identity(api, await face(api, "gone.png", 0), "Ada Forgotten")
    binned = await face(api, "bin.png", 1)
    await name_identity(api, binned, "Bob Recycled")
    deleted = await face(api, "del.png", 2)
    await name_identity(api, deleted, "Cy Deleted")
    await api.client.delete(f"{SOURCES}/{binned['id']}")
    await api.client.delete(f"{SOURCES}/{deleted['id']}")
    assert (await api.client.post(f"{SOURCES}/{deleted['id']}/permanent-delete")).status_code == 204
    assert (await api.client.post(f"{PEOPLE}/{forgotten['id']}/forget")).status_code == 204

    ada = await look(api, FACES[0])
    bob = await look(api, FACES[1])
    cy = await look(api, FACES[2])

    def offered(found: dict[str, Any]) -> list[str]:
        return [
            p["identity"]["person"]["display_name"]
            for f in found["faces"]
            for p in f["possible_people"]
            if p["identity"]["person"]
        ]

    assert "Ada Forgotten" not in offered(ada)  # biometric memory forgotten: not recognisable
    assert offered(bob)[0] == "Bob Recycled"  # the bin keeps recognition memory (section 39)
    assert "Cy Deleted" not in offered(cy)  # its vector went with the image


async def test_when_the_faces_cannot_be_looked_for_the_answer_says_so(
    processing_api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = processing_api
    assert api.perception is not None
    assert api.backend.processing is not None
    path = str(api.image("q.png"))

    def broken(_pixels: Any) -> Any:
        raise PerceptionError(MLErrorCode.INFERENCE_FAILED, "the worker is gone")

    monkeypatch.setattr(api.perception, "detect", broken)
    failed = await api.client.post(FACE_SEARCH, json={"path": path})
    monkeypatch.undo()

    def no_configuration(_session: Any) -> Any:
        raise ProcessingUnavailableError("nothing is configured")

    monkeypatch.setattr(
        api.backend, "processing", replace(api.backend.processing, request_for=no_configuration)
    )
    unavailable = await api.client.post(FACE_SEARCH, json={"path": path})

    assert error(failed, 503, "PERCEPTION_UNAVAILABLE")["retryable"] is True
    error(unavailable, 503, "PROCESSING_UNAVAILABLE")


async def test_face_search_needs_processing_and_a_ready_library(api: Api) -> None:
    error(await api.client.post(FACE_SEARCH, json={"path": "x.png"}), 503, "PROCESSING_UNAVAILABLE")


async def test_an_empty_library_knows_nobody_and_a_poor_detection_says_so(
    processing_api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = processing_api
    assert api.perception is not None
    detector = api.perception.detector

    nobody = await look(api, FACES[0])
    monkeypatch.setattr(
        api.perception,
        "detect",
        lambda _pixels: Detected((Detection(0, 0, (0.2, 0.2, 0.8, 0.8), 0.01, None),), detector),
    )
    poor = await look(api, FACES[0])

    assert nobody["faces"][0]["status"] == "UNKNOWN"
    assert nobody["faces"][0]["possible_people"] == []
    assert poor["faces"][0]["reason"] == "LOW_QUALITY"
    assert poor["faces"][0]["detection_score"] == 0.01


async def test_a_person_seen_twice_counts_both_faces(processing_api: Api) -> None:
    api = processing_api
    await name_identity(api, await face(api, "one.png", 0), "Ada")
    await face(api, "two.png", 0)

    found = await look(api, FACES[0])

    people = found["faces"][0]["possible_people"]
    assert [(p["identity"]["person"]["display_name"], p["matching_faces"]) for p in people] == [
        ("Ada", 2)
    ]


async def test_the_same_search_gives_the_same_answer_after_a_restart(
    tmp_path: Path, clock: Any, new_id: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with processing_app(tmp_path, clock, new_id, monkeypatch) as first:
        await name_identity(first, await face(first, "ada.png", 0), "Ada")
        before = await look(first, FACES[0])
        catalog = first.catalog
    assert catalog is not None

    async with processing_app(
        tmp_path, clock, new_id, monkeypatch, catalog=catalog, folder="after-restart"
    ) as second:
        again = await look(second, FACES[0])
        files = snapshot(second)
        repeat = await look(second, FACES[0])
        unchanged = snapshot(second) == files

    assert again == before  # the memory and its index survived, and the query changed nothing
    assert repeat == again
    assert unchanged


async def test_limits_are_kept_while_the_picture_arrives(
    processing_api: Api, tmp_path: Path
) -> None:
    api = processing_api
    big = tmp_path / "big.bin"
    big.write_bytes(b"x" * 100_001)

    error(await api.client.post(FACE_SEARCH, json={"path": str(big)}), 413, "MEDIA_TOO_LARGE")
    error(await api.client.post(FACE_SEARCH, json={"path": "x" * 9000}), 413, "MEDIA_TOO_LARGE")
    error(
        await api.client.post(FACE_SEARCH, json={"path": "\\server\\share\a.png"}),
        400,
        "QUERY_IMAGE_UNREADABLE",
    )
    for network in ("//server/share/a.png", r"/\server/share/a.png", r"\/server/share/a.png"):
        error(
            await api.client.post(FACE_SEARCH, json={"path": network}),
            400,
            "QUERY_IMAGE_UNREADABLE",
        )


async def test_the_search_index_or_worker_being_unavailable_is_said_plainly(
    processing_api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = processing_api
    assert api.perception is not None
    assert api.backend.library is not None
    path = str(api.image("q.png"))

    def failed(_pixels: Any) -> Any:
        raise MLUnavailableError("the worker failed")

    monkeypatch.setattr(api.perception, "detect", failed)
    worker = await api.client.post(FACE_SEARCH, json={"path": path})
    monkeypatch.undo()

    def unusable(_space: Any) -> Any:
        raise IndexUnusableError("the index is damaged")

    monkeypatch.setattr(api.backend.library.coordinator, "open_for_recognition", unusable)
    index = await api.client.post(FACE_SEARCH, json={"path": path})

    assert error(worker, 503, "PERCEPTION_UNAVAILABLE")["retryable"] is True
    error(index, 503, "SEARCH_INDEX_UNAVAILABLE")


async def test_a_picture_of_several_faces_is_answered_face_by_face(
    processing_api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = processing_api
    assert api.perception is not None
    await name_identity(api, await face(api, "ada.png", 0), "Ada")
    await name_identity(api, await face(api, "bob.png", 1), "Bob")
    perception = api.perception
    boxes = [(0.1, 0.1, 0.4, 0.4), (0.5, 0.5, 0.9, 0.9)]

    def detect(_pixels: Any) -> Detected:
        return Detected(
            tuple(Detection(0, i, box, 0.9, None) for i, box in enumerate(boxes)),
            perception.detector,
        )

    def represent(_pixels: Any, _detections: Any) -> Represented:
        vectors = (FACES[0], FACES[1])
        return Represented(
            tuple(FaceVector(i, v, "L2_NORMALIZED") for i, v in enumerate(vectors)),
            perception.embedder,
            (),
        )

    monkeypatch.setattr(perception, "detect", detect)
    monkeypatch.setattr(perception, "represent", represent)

    found = await api.client.post(FACE_SEARCH, json={"path": str(api.image("two.png"))})

    first, second = found.json()["faces"]
    assert (first["index"], second["index"]) == (0, 1)
    assert first["possible_people"][0]["identity"]["person"]["display_name"] == "Ada"
    assert second["possible_people"][0]["identity"]["person"]["display_name"] == "Bob"
    assert second["bounding_box"]["x"] == 0.5


async def test_a_merged_person_is_offered_once_under_the_survivor(processing_api: Api) -> None:
    api = processing_api
    await name_identity(api, await face(api, "ada.png", 0), "Ada")
    await face(api, "other.png", 1)
    items = (await api.client.get("/api/v1/identities")).json()["items"]
    named = next(i for i in items if i["person"])
    other = next(i for i in items if not i["person"])
    merged = await api.client.post(
        "/api/v1/identities/merge",
        json={
            "identities": [
                {"id": named["id"], "revision": named["revision"]},
                {"id": other["id"], "revision": other["revision"]},
            ],
            "preferred_identity_id": named["id"],
        },
    )
    assert merged.status_code == 200, merged.text

    found = await look(api, FACES[1])

    people = found["faces"][0]["possible_people"]
    assert [p["identity"]["id"] for p in people].count(named["id"]) == 1
    assert other["id"] not in [p["identity"]["id"] for p in people]


async def test_searches_made_at_the_same_time_all_get_their_answer(processing_api: Api) -> None:
    api = processing_api
    await name_identity(api, await face(api, "ada.png", 0), "Ada")
    assert api.perception is not None
    api.perception.vector = FACES[0]
    path = str(api.image("q.png"))

    async with anyio.create_task_group() as group:
        answers: list[Any] = []

        async def ask_once() -> None:
            answers.append(await api.client.post(FACE_SEARCH, json={"path": path}))

        for _ in range(3):
            group.start_soon(ask_once)

    assert [a.status_code for a in answers] == [200] * 3
    assert len({a.text for a in answers}) == 1


async def test_too_many_searches_at_once_are_turned_away_and_the_slot_is_given_back(
    processing_api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = processing_api
    assert api.perception is not None
    api.perception.vector = FACES[0]
    path = str(api.image("q.png"))
    taken = threading.BoundedSemaphore(1)
    taken.acquire()
    monkeypatch.setattr(api.backend, "face_search_slots", taken)

    busy = await api.client.post(FACE_SEARCH, json={"path": path})
    taken.release()
    again = await api.client.post(FACE_SEARCH, json={"path": path})
    refused = await api.client.post(FACE_SEARCH, json={"path": str(api.folder / "nowhere.png")})
    after = await api.client.post(FACE_SEARCH, json={"path": path})

    assert error(busy, 429, "FACE_SEARCH_BUSY")["retryable"] is True
    assert again.status_code == 200
    assert refused.status_code == 400  # a refusal gives its slot back too
    assert after.status_code == 200


async def test_a_worker_output_lost_between_calls_is_a_retryable_503(
    processing_api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = processing_api
    assert api.perception is not None

    def lost(_pixels: Any, _detections: Any) -> Any:
        raise ContractError(MLErrorCode.SHARED_MEMORY_UNAVAILABLE, "the output segment is gone")

    monkeypatch.setattr(api.perception, "represent", lost)

    response = await api.client.post(FACE_SEARCH, json={"path": str(api.image("q.png"))})

    assert error(response, 503, "PERCEPTION_UNAVAILABLE")["retryable"] is True


async def test_a_person_beyond_the_nearest_few_faces_is_still_offered(processing_api: Api) -> None:
    api = processing_api
    assert api.perception is not None
    await name_identity(api, await face(api, "x0.png", 0), "Xavier")
    for index in range(1, 7):  # seven faces of one person, all nearer than anyone else
        await face(api, f"x{index}.png", 0)
    api.perception.vector = FACES[1]
    await name_identity(api, await processed(api, "y.png"), "Yolanda")

    found = await look(api, FACES[0])

    names = [p["identity"]["person"]["display_name"] for p in found["faces"][0]["possible_people"]]
    assert names == ["Xavier", "Yolanda"]  # the processing shortlist (2 here) would stop at Xavier
