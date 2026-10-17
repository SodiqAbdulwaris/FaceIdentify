"""Automatic acceptance seen from outside (TST-057B, owner decision 2026-10-15).

The development host runs under the approved operating point (`buffalo-l-verified-match-v1`,
0.45 / margin 0.10, no automatic new identity) and the faces are driven over HTTP. What is checked:
an automatically matched face is told apart from one a person placed, it carries the score it was
matched on, the owner can undo it with the ordinary correction routes, its Evidence records the
decision, and a face that abstained before the policy changed stays abstained.
"""

import json
import sqlite3
from pathlib import Path
from typing import Any

import httpx
import pytest

from backend.api import development
from backend.api.development import development_request
from backend.api.real import APPROVED_MATCHING
from tests.integration.test_api_development_profile import (
    ABSTAIN_ONLY,
    abstain_only,
    host,
    identities,
    import_image,
    occurrence_count,
    picture,
    process_and_wait,
    unresolved,
)

RED = (200, 0, 0)


def approved_matching(monkeypatch: pytest.MonkeyPatch) -> None:
    """Run the development host under the policy the owner approved."""
    policy = {
        "schema_version": 1,
        "version": "buffalo-l-verified-match-v1",
        **APPROVED_MATCHING["buffalo-l-verified-match-v1"],
    }

    def request(session: Any) -> dict[str, Any]:
        return {**development_request(session), "decision_policy": policy}

    monkeypatch.setattr(development, "development_request", request)


async def occurrences(client: httpx.AsyncClient, source_id: str) -> list[dict[str, Any]]:
    page = (await client.get(f"/api/v1/sources/{source_id}/occurrences")).json()
    items: list[dict[str, Any]] = page["items"]
    return items


def evidence_of(tmp_path: Path, kind: str) -> list[dict[str, Any]]:
    database = sqlite3.connect(tmp_path / "library" / "database" / "library.db")
    try:
        rows = database.execute("SELECT payload_json FROM evidence WHERE kind = ?", (kind,))
        return [json.loads(row[0]) for row in rows]
    finally:
        database.close()


async def test_an_automatic_match_is_marked_scored_recorded_and_undoable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    approved_matching(monkeypatch)
    folder = tmp_path / "pictures"
    folder.mkdir()
    async with host(tmp_path, development_profile=True) as client:
        first = await import_image(client, picture(folder, "one.png", RED))
        await process_and_wait(client, first["id"])
        second = await import_image(client, picture(folder, "two.png", RED))
        await process_and_wait(client, second["id"])

        (identity,) = await identities(client)  # matched, not a second identity
        (founder,) = await occurrences(client, first["id"])
        (matched,) = await occurrences(client, second["id"])
        assert matched["identity_id"] == identity["id"] == founder["identity_id"]
        assert founder["placement"] == "AUTOMATIC_NEW"  # the first face made the identity
        assert matched["placement"] == "AUTOMATIC_MATCH"
        assert matched["match_similarity"] == pytest.approx(1.0, abs=1e-5)
        assert matched["match_margin"] is None  # a single candidate has no runner-up

        # Evidence: the decision, its similarity and the policy it was made under.
        (record,) = evidence_of(tmp_path, "IDENTITY_MATCHED")
        assert record["outcome"] == "MATCH_EXISTING"
        assert record["reason"] == "MATCHED"
        assert record["identity_id"] == identity["id"]
        assert record["candidates"][0]["similarity"] == matched["match_similarity"]
        assert record["policy"]["version"] == "buffalo-l-verified-match-v1"
        assert record["policy"]["match_threshold"] == 0.45
        assert record["policy"]["margin"] == 0.10

        # The owner confirms it: the face is now a person's decision, not an automatic one.
        confirmed = await client.post(
            f"/api/v1/occurrences/{matched['id']}/confirm",
            json={"expected_identity_id": identity["id"]},
        )
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json()["placement"] == "USER"
        assert confirmed.json()["match_similarity"] is None

        # A third face is matched too; the owner separates it, which undoes the match.
        third = await import_image(client, picture(folder, "three.png", RED))
        await process_and_wait(client, third["id"])
        (again,) = await occurrences(client, third["id"])
        assert again["placement"] == "AUTOMATIC_MATCH"
        separated = await client.post(
            f"/api/v1/occurrences/{again['id']}/reassign",
            json={"expected_identity_id": identity["id"], "identity_id": None},
        )
        assert separated.status_code == 200, separated.text
        assert separated.json()["identity_id"] != identity["id"]
        assert separated.json()["placement"] == "USER"
        assert len(await identities(client)) == 2
        # Nothing was rewritten: both matches and the corrections are on record.
        assert len(evidence_of(tmp_path, "IDENTITY_MATCHED")) == 2
        assert {e["action"] for e in evidence_of(tmp_path, "USER_CORRECTION")} == {
            "CONFIRM",
            "SEPARATE",
        }


async def test_a_face_that_abstained_before_the_policy_changed_stays_abstained(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = tmp_path / "pictures"
    folder.mkdir()
    with monkeypatch.context() as before:
        abstain_only(before)
        async with host(tmp_path, development_profile=True) as client:
            first = await import_image(client, picture(folder, "one.png", RED))
            await process_and_wait(client, first["id"])
            waiting_source = await import_image(client, picture(folder, "two.png", RED))
            await process_and_wait(client, waiting_source["id"])
            (waiting,) = await unresolved(client, waiting_source["id"])
    assert evidence_of(tmp_path, "IDENTITY_MATCHED") == []

    approved_matching(monkeypatch)  # the owner installs the policy; the application restarts
    async with host(tmp_path, development_profile=True) as client:
        assert await unresolved(client, waiting_source["id"]) == [waiting]  # untouched by restart
        # The earlier face is a neighbour with no identity, as close as the founder: the margin
        # between the two is nil, so the new face is ambiguous and waits too, never guessed.
        later = await import_image(client, picture(folder, "three.png", RED))
        await process_and_wait(client, later["id"])
        assert await occurrence_count(client, later["id"]) == 0
        assert len(await unresolved(client, later["id"])) == 1
        assert await unresolved(client, waiting_source["id"]) == [waiting]  # not re-decided
        assert await occurrence_count(client, waiting_source["id"]) == 0
    assert evidence_of(tmp_path, "IDENTITY_MATCHED") == []
    reasons = [e["reason"] for e in evidence_of(tmp_path, "RECOGNITION_ABSTAINED")]
    assert len(reasons) == 2
    assert "AMBIGUOUS_CANDIDATES" in reasons


async def test_a_merge_or_a_split_by_the_owner_replaces_an_automatic_label(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    approved_matching(monkeypatch)
    folder = tmp_path / "pictures"
    folder.mkdir()
    async with host(tmp_path, development_profile=True) as client:
        sources = []
        for name in ("one", "two", "three"):
            sources.append(await import_image(client, picture(folder, f"{name}.png", RED)))
            await process_and_wait(client, sources[-1]["id"])
        (identity,) = await identities(client)
        (two,) = await occurrences(client, sources[1]["id"])
        (three,) = await occurrences(client, sources[2]["id"])
        assert (two["placement"], three["placement"]) == ("AUTOMATIC_MATCH",) * 2

        # Splitting a matched face off is the owner's decision about it.
        split = await client.post(
            f"/api/v1/identities/{identity['id']}/split",
            json={"occurrence_ids": [two["id"]], "expected_revision": identity["revision"]},
        )
        assert split.status_code == 201, split.text
        (moved,) = await occurrences(client, sources[1]["id"])
        assert moved["identity_id"] == split.json()["id"]
        assert (moved["placement"], moved["match_similarity"]) == ("USER", None)

        # So is merging: the other matched face, carried over by a merge, is no longer "automatic".
        current = {i["id"]: i for i in await identities(client)}
        merged = await client.post(
            "/api/v1/identities/merge",
            json={
                "identities": [
                    {"id": i, "revision": current[i]["revision"]}
                    for i in (split.json()["id"], identity["id"])
                ],
                "preferred_identity_id": split.json()["id"],
            },
        )
        assert merged.status_code == 200, merged.text
        (carried,) = await occurrences(client, sources[2]["id"])
        assert carried["identity_id"] == split.json()["id"]
        assert (carried["placement"], carried["match_similarity"]) == ("USER", None)


async def test_a_match_whose_evidence_has_no_scores_still_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The shared writer accepts an IDENTITY_MATCHED row with no recognition payload: reading the
    face must say it was matched automatically, without scores, not fail."""
    approved_matching(monkeypatch)
    folder = tmp_path / "pictures"
    folder.mkdir()
    async with host(tmp_path, development_profile=True) as client:
        for name in ("one", "two"):
            source = await import_image(client, picture(folder, f"{name}.png", RED))
            await process_and_wait(client, source["id"])
    database = sqlite3.connect(tmp_path / "library" / "database" / "library.db")
    try:
        database.execute("UPDATE evidence SET payload_json = '{}' WHERE kind = 'IDENTITY_MATCHED'")
        database.commit()
    finally:
        database.close()
    async with host(tmp_path, development_profile=True) as client:
        (matched,) = await occurrences(client, source["id"])
        assert matched["placement"] == "AUTOMATIC_MATCH"
        assert (matched["match_similarity"], matched["match_margin"]) == (None, None)


def test_the_abstain_only_policy_is_not_an_approved_matching_one() -> None:
    assert ABSTAIN_ONLY["version"] not in APPROVED_MATCHING
