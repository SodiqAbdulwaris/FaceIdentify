"""Historical and name search through the API (M5 step 5a; TST-055; API section 12.1).

The library really processes the images (planted perception), so what is searched is what the
pipeline made authoritative. The point of TST-055: search reflects authoritative relationships, so
every change to them (a name, a merge, a recycle, a delete, a forget) changes what a search finds,
and a search itself writes nothing.
"""

import uuid
from typing import Any

from sqlalchemy import func, select, update

from backend.app.identities.models import Evidence, Identity, IdentityState
from backend.app.memory.models import Observation, Occurrence, OccurrenceState, Representation
from backend.app.people.models import Person, PersonState
from backend.app.processing.models import ProcessingRun, ProcessingRunState
from backend.app.sources.models import Source
from tests.fixtures.api import Api, error
from tests.fixtures.pipeline import unit
from tests.integration.test_api_memory import processed

SEARCH = "/api/v1/search"
SOURCES = "/api/v1/sources"
IDENTITIES = "/api/v1/identities"
PEOPLE = "/api/v1/people"

FACES = [unit(1, 0, 0, 0), unit(0, 1, 0, 0), unit(0, 0, 1, 0), unit(0, 0, 0, 1)]


async def face(api: Api, name: str, index: int) -> dict[str, Any]:
    """An image whose one face is face number `index`: a different `index`, a different person."""
    assert api.perception is not None
    api.perception.vector = FACES[index]
    return await processed(api, name)


async def ask(api: Api, q: str, **params: str) -> dict[str, Any]:
    response = await api.client.get(SEARCH, params={"q": q, **params})
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def name_identity(api: Api, source: dict[str, Any], name: str) -> dict[str, Any]:
    [item] = (await api.client.get(f"{SOURCES}/{source['id']}/occurrences")).json()["items"]
    made = await api.client.post(
        PEOPLE, json={"display_name": name, "identity_id": item["identity_id"]}
    )
    assert made.status_code == 201, made.text
    person: dict[str, Any] = made.json()
    return person


def table_counts(api: Api) -> dict[str, int]:
    assert api.backend.library is not None
    with api.backend.library.session_factory() as session:
        return {
            model.__tablename__: session.scalar(select(func.count()).select_from(model)) or 0
            for model in (Source, Observation, Representation, Occurrence, Identity, Evidence)
        }


async def test_a_search_needs_a_word_and_a_known_kind(api: Api) -> None:
    error(await api.client.get(SEARCH), 422, "VALIDATION_ERROR")
    error(await api.client.get(SEARCH, params={"q": "   "}), 422, "INVALID_SEARCH")
    error(
        await api.client.get(SEARCH, params={"q": "ada", "types": "people,cats"}),
        422,
        "INVALID_SEARCH",
    )
    error(
        await api.client.get(SEARCH, params={"q": "ada", "recycled": "maybe"}),
        422,
        "VALIDATION_ERROR",
    )


async def test_people_are_found_by_name_best_match_first_with_their_appearances(
    processing_api: Api,
) -> None:
    api = processing_api
    for index, (image, name) in enumerate([("a.png", "Nada"), ("b.png", "Adam"), ("c.png", "Ada")]):
        await name_identity(api, await face(api, image, index), name)

    found = await ask(api, "  ADA ")

    assert found["query"] == "ada"
    assert [(p["display_name"], p["match"]) for p in found["results"]["people"]] == [
        ("Ada", "EXACT"),
        ("Adam", "PREFIX"),
        ("Nada", "CONTAINS"),
    ]
    ada = found["results"]["people"][0]
    assert (ada["occurrence_count"], ada["source_count"], ada["visual_support"]) == (1, 1, True)
    assert len(ada["identity_ids"]) == 1
    names = {o["source_display_name"] for o in found["results"]["occurrences"]}
    assert names == {"a.png", "b.png", "c.png"}  # the appearances of everyone found
    assert found["ranking"] == {
        "plan": "NAME_LOOKUP",
        "ranker": "rule-v1",
        "recycled": "include",
        "types": ["people", "identities", "sources", "occurrences"],
    }


async def test_the_result_kinds_can_be_chosen_and_limited(processing_api: Api) -> None:
    api = processing_api
    for index, name in enumerate(["Ada", "Adam"]):
        await name_identity(api, await face(api, f"ada{index}.png", index), name)

    only_people = await ask(api, "ada", types="people", limit="1")

    assert [p["display_name"] for p in only_people["results"]["people"]] == ["Ada"]
    assert only_people["results"]["sources"] == []
    assert only_people["results"]["occurrences"] == []  # not asked for


async def test_an_unnamed_person_is_found_by_their_label_and_a_sources_by_its_file_name(
    processing_api: Api,
) -> None:
    api = processing_api
    source = await face(api, "beach.png", 0)
    [identity] = (await api.client.get(IDENTITIES)).json()["items"]
    label = identity["id"].replace("-", "")[:6]

    by_label = await ask(api, f"person {label}")
    by_start = await ask(api, label[:4])
    by_file = await ask(api, "BEACH")
    nobody = await ask(api, "zzzz-not-here")

    [hit] = by_label["results"]["identities"]
    assert (hit["id"], hit["label"], hit["match"]) == (
        identity["id"],
        f"Person {label.upper()}",
        "EXACT",
    )
    assert [i["id"] for i in by_start["results"]["identities"]] == [identity["id"]]
    assert [o["identity_id"] for o in by_label["results"]["occurrences"]] == [identity["id"]]
    [source_hit] = by_file["results"]["sources"]
    assert (source_hit["id"], source_hit["match"], source_hit["processed"]) == (
        source["id"],
        "PREFIX",
        True,
    )
    assert nobody["results"] == {"people": [], "identities": [], "sources": [], "occurrences": []}


async def test_a_named_person_is_not_listed_as_an_unnamed_one(processing_api: Api) -> None:
    api = processing_api
    source = await face(api, "a.png", 0)
    person = await name_identity(api, source, "Ada")
    [identity] = (await api.client.get(IDENTITIES)).json()["items"]

    found = await ask(api, identity["id"].replace("-", "")[:6])

    assert found["results"]["identities"] == []
    assert person["display_name"] == "Ada"


async def test_a_merge_and_a_rename_change_what_is_found(processing_api: Api) -> None:
    api = processing_api
    first = await face(api, "one.png", 0)
    await face(api, "two.png", 1)
    await name_identity(api, first, "Ada")
    items = (await api.client.get(IDENTITIES)).json()["items"]
    [named] = [i for i in items if i["person"]]
    [unnamed] = [i for i in items if not i["person"]]

    # merge the unnamed identity into Ada: their appearance now belongs to her
    merged = await api.client.post(
        f"{IDENTITIES}/merge",
        json={
            "identities": [
                {"id": named["id"], "revision": named["revision"]},
                {"id": unnamed["id"], "revision": unnamed["revision"]},
            ],
            "preferred_identity_id": named["id"],
        },
    )
    assert merged.status_code == 200, merged.text
    after_merge = await ask(api, "ada", types="people")
    assert after_merge["results"]["people"][0]["occurrence_count"] == 2
    assert (await ask(api, unnamed["id"].replace("-", "")[:6]))["results"]["identities"] == []

    # rename her: the old exact name now only matches the start of the new one
    person = after_merge["results"]["people"][0]
    renamed = await api.client.patch(
        f"{PEOPLE}/{person['id']}", json={"display_name": "Adaline", "expected_revision": 1}
    )
    assert renamed.status_code == 200, renamed.text
    [now] = (await ask(api, "ada", types="people"))["results"]["people"]
    assert (now["display_name"], now["match"]) == ("Adaline", "PREFIX")
    assert (await ask(api, "adaline", types="people"))["results"]["people"][0]["match"] == "EXACT"


async def test_a_recycled_image_is_marked_and_can_be_filtered_out_or_asked_for(
    processing_api: Api,
) -> None:
    api = processing_api
    kept = await face(api, "kept.png", 0)
    gone = await face(api, "bin.png", 1)
    await name_identity(api, kept, "Ada")
    await name_identity(api, gone, "Adam")
    await api.client.delete(f"{SOURCES}/{gone['id']}")

    everything = await ask(api, "ada")
    without = await ask(api, "ada", recycled="exclude")
    just_bin = await ask(api, "ada", recycled="only")
    by_file = await ask(api, "bin")

    marked = {
        o["source_display_name"]: o["source_recycled"] for o in everything["results"]["occurrences"]
    }
    assert marked == {"kept.png": False, "bin.png": True}  # included by default, and marked
    assert {o["source_display_name"] for o in without["results"]["occurrences"]} == {"kept.png"}
    assert {o["source_display_name"] for o in just_bin["results"]["occurrences"]} == {"bin.png"}
    adam = next(p for p in without["results"]["people"] if p["display_name"] == "Adam")
    assert (adam["occurrence_count"], adam["visual_support"]) == (0, False)  # none outside the bin
    assert [(s["display_name"], s["source_recycled"]) for s in by_file["results"]["sources"]] == [
        ("bin.png", True)
    ]
    assert (without["coverage"]["sources"], just_bin["coverage"]["sources"]) == (1, 1)

    await api.client.post(f"{SOURCES}/{gone['id']}/restore")
    restored = await ask(api, "ada", recycled="exclude")
    assert {o["source_display_name"] for o in restored["results"]["occurrences"]} == {
        "kept.png",
        "bin.png",
    }


async def test_a_deleted_image_and_a_forgotten_person_disappear_from_the_results(
    processing_api: Api,
) -> None:
    api = processing_api
    doomed = await face(api, "doomed.png", 0)
    other = await face(api, "other.png", 1)
    await name_identity(api, doomed, "Ada")
    await name_identity(api, other, "Adam")
    await api.client.delete(f"{SOURCES}/{doomed['id']}")
    assert (await api.client.post(f"{SOURCES}/{doomed['id']}/permanent-delete")).status_code == 204

    after_delete = await ask(api, "doomed")
    ada = (await ask(api, "ada"))["results"]["people"]

    assert after_delete["results"]["sources"] == []  # the image is gone, tombstone included
    assert [p["display_name"] for p in ada] == ["Ada", "Adam"]  # the named people stay
    assert (ada[0]["occurrence_count"], ada[0]["visual_support"]) == (0, False)  # nothing to see
    forgotten = await api.client.post(f"{PEOPLE}/{ada[1]['id']}/forget")
    assert forgotten.status_code == 204
    adam = next(p for p in (await ask(api, "adam"))["results"]["people"])
    assert (adam["occurrence_count"], adam["visual_support"], adam["identity_ids"]) == (
        0,
        False,
        [],
    )
    assert (await ask(api, "adam"))["results"]["occurrences"] == []


async def test_the_coverage_says_how_much_of_the_library_was_processed(
    processing_api: Api,
) -> None:
    from tests.fixtures.api import imported

    api = processing_api
    await face(api, "done.png", 0)
    await imported(api, path=str(api.image("waiting.png")), display_name="waiting.png")

    found = await ask(api, "png")

    assert found["coverage"] == {"sources": 2, "processed": 1, "not_processed": 1}
    assert {s["display_name"]: s["processed"] for s in found["results"]["sources"]} == {
        "done.png": True,
        "waiting.png": False,
    }


async def test_searching_writes_nothing_and_repeating_it_changes_nothing(
    processing_api: Api,
) -> None:
    api = processing_api
    await name_identity(api, await face(api, "a.png", 0), "Ada")
    before = table_counts(api)

    first = await ask(api, "ada")
    second = await ask(api, "ada")

    assert first == second
    assert table_counts(api) == before  # a query is not an ingest


async def test_only_active_things_are_found(processing_api: Api) -> None:
    """States the API cannot reach today (a recycled person, a merged identity, a superseded
    appearance, a run still going) are written directly: search must not show or count them."""
    api = processing_api
    assert api.backend.library is not None
    names = ["Ada Active", "Ada Recycled", "Ada Merged", "Ada Superseded"]
    sources = [await face(api, f"{i}.png", i) for i in range(4)]
    persons = [await name_identity(api, s, n) for s, n in zip(sources, names, strict=True)]
    merged_identity = (await ask(api, "ada merged"))["results"]["people"][0]["identity_ids"][0]
    survivor = (await ask(api, "ada active"))["results"]["people"][0]["identity_ids"][0]

    def degrade(session: Any) -> None:
        session.get(Person, uuid.UUID(persons[1]["id"])).state = PersonState.RECYCLED
        gone = session.get(Identity, uuid.UUID(merged_identity))
        gone.state = IdentityState.MERGED
        gone.merged_into_identity_id = uuid.UUID(survivor)
        session.execute(
            update(Occurrence)
            .where(Occurrence.source_id == uuid.UUID(sources[3]["id"]))
            .values(state=OccurrenceState.SUPERSEDED)
        )
        session.execute(update(ProcessingRun).values(state=ProcessingRunState.RUNNING))

    api.backend.library.unit_of_work.write(degrade)

    found = await ask(api, "ada")

    by_name = {p["display_name"]: p for p in found["results"]["people"]}
    assert by_name["Ada Merged"]["occurrence_count"] == 0  # a merged identity holds nothing
    assert by_name["Ada Superseded"]["occurrence_count"] == 0
    assert "Ada Recycled" not in by_name
    assert {o["source_display_name"] for o in found["results"]["occurrences"]} == {"0.png"}
    assert found["coverage"]["processed"] == 0  # no run has completed any more


async def test_occurrences_can_be_asked_for_alone_and_a_limit_keeps_the_best(
    processing_api: Api,
) -> None:
    api = processing_api
    for index, name in enumerate(["Adam", "Ada", "Adaline"]):
        await name_identity(api, await face(api, f"p{index}.png", index), name)
    unnamed = (await api.client.get(IDENTITIES)).json()["items"]

    only = await ask(api, "ada", types="occurrences")
    best = await ask(api, "ada", types="people", limit="1")

    assert only["results"]["people"] == []
    assert len(only["results"]["occurrences"]) == 3  # the appearances of everyone found
    assert [p["display_name"] for p in best["results"]["people"]] == ["Ada"]  # exact, cut by SQL
    label = unnamed[0]["id"].replace("-", "")[:6]
    assert (await ask(api, label, types="occurrences"))["results"]["occurrences"] == []  # named


async def test_file_names_match_with_the_same_folding_as_the_query(processing_api: Api) -> None:
    from tests.fixtures.api import imported

    api = processing_api
    for name in ["family  holiday.png", "École.png", "Straße.png"]:
        await imported(api, path=str(api.image(name)), display_name=name)

    spaced = await ask(api, "family  holiday.png")
    accent = await ask(api, "ÉCOLE")
    sharp = await ask(api, "strasse")

    assert [s["display_name"] for s in spaced["results"]["sources"]] == ["family  holiday.png"]
    assert [s["display_name"] for s in accent["results"]["sources"]] == ["École.png"]
    assert [s["display_name"] for s in sharp["results"]["sources"]] == ["Straße.png"]
