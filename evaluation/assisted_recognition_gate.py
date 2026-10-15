"""TST-057A and the M5 real-world gate: the identity-memory workflow on the real models.

    PYTHONPATH=. uv run python evaluation/assisted_recognition_gate.py \
        --dataset evaluation/datasets/commons-pd --local-state-root local-models/state \
        --workdir evaluation/datasets/gate-run --report evaluation/datasets/reports/gate.json

It starts the real application in this process (the real profile: installed SCRFD and ArcFace
through the supervised worker, the measured abstain-only policy, a fresh library under
`--workdir`) and drives
it only through its HTTP API, as the desktop app does:

1. Enrol: for each chosen person, import all but the held-out photographs (each a separate Source),
   process them, and *place* each photograph's subject face into that person's identity (this stands
   in for the human confirmation that assisted recognition relies on; automatic matching is off, so
   the application places nothing by similarity, though it may start a new identity for a face
   nobody resembles, which is then adopted or corrected) and name the person.
2. Query (TST-057A): every held-out photograph is searched by face (`POST /search/face`). The people
   offered are ranked by similarity; Recall@1, Recall@5 and the mean reciprocal rank are measured
   over
   the queries of people who have at least two enrolled photographs. A query writes nothing: library
   counts are compared before and after.
3. Workflow: name search; recycle and restore (default search excludes, "include" finds); merge and
   split; permanent delete; forget (the person is no longer recognised and stays findable by name).
4. Restart: the application is stopped and started again on the same library; the same queries
   give the
   same rankings, and name search still works.

Hard negatives (`--hard-negatives N --hard-negative-pool <dataset>`, issue 177): random strangers
rarely resemble anyone enrolled, so they say little about look-alikes. After enrolment, each person
of a second dataset (the pool) offers one *selection* photograph, searched against the enrolled
library; the N people whose selection photograph came closest to an enrolled person become
strangers, and only their *other* photographs are scored, so the photograph that chose a person
never counts for them. A pool person with the same name as anyone in the main dataset, or a pool
picture byte-identical to one of its pictures, is left out (the same person under another name is
still possible: the pool's labels are its creators'). The selection queries run inside the
before/after count check. Their results get their own open-set table: they are chosen to be hard,
so it is a deliberately pessimistic read, not an estimate of the rate for random strangers.

The identity labels are the Commons categories of the photographs, a human-curated label that is NOT
verified: a mislabelled photograph can make the numbers look better or worse, with no direction. The
report says so and records the configuration, environment, exclusions and the dataset manifest hash.
This is a local run (the weights are not in CI) and is recorded in the tracker with its evidence.
"""

import argparse
import asyncio
import base64
import hashlib
import json
import math
import os
import platform
import secrets
import shutil
import statistics
import sys
import time
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import anyio
import httpx
import onnxruntime

from backend.api.host import (
    PROVISIONAL_INDEX_BATCH,
    PROVISIONAL_INDEX_PASSES,
    PROVISIONAL_INDEX_RETRY,
    PROVISIONAL_TRANSACTION_RETRY,
)
from backend.api.real import PACKAGE_KEY, providers_from, real_processing
from backend.api.startup import (
    PROVISIONAL_MAX_BYTES,
    PROVISIONAL_MAX_PIXELS,
    LibrarySettings,
    MediaLimits,
    create_backend_app,
)

DATASETS_ROOT = (Path(__file__).resolve().parent / "datasets").resolve()
API = "/api/v1"
DOMINANCE = 2.5  # a subject face is at least this many times larger than any other in the picture
RUN_TIMEOUT = 900.0  # default seconds to wait for the processing runs (`--run-timeout`)


def positive_seconds(text: str) -> float:
    """A wait in seconds: a finite number above zero (`nan` and `inf` would never expire)."""
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a number") from None
    if not math.isfinite(value) or value <= 0:
        raise argparse.ArgumentTypeError(f"{text!r} must be a finite number above zero")
    return value


def guard(path: Path) -> Path:
    """Biometric data stays under the Git-ignored datasets folder."""
    resolved = path.resolve()
    if DATASETS_ROOT not in resolved.parents:
        raise SystemExit(f"{path} must be inside {DATASETS_ROOT} (it holds biometric data)")
    return resolved


class Gate:
    """One running application on the library, and the facts the checks need."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client

    async def get(self, path: str, **params: Any) -> Any:
        response = await self.client.get(API + path, params=params)
        response.raise_for_status()
        return response.json()

    async def post(
        self, path: str, body: Any = None, expect: tuple[int, ...] = (200, 201, 202)
    ) -> Any:
        response = await self.client.post(API + path, json=body)
        if response.status_code not in expect and response.status_code != 204:
            raise RuntimeError(f"POST {path} -> {response.status_code}: {response.text[:300]}")
        return response.json() if response.content else None

    async def delete(self, path: str) -> None:
        response = await self.client.delete(API + path)
        if response.status_code != 204:
            raise RuntimeError(f"DELETE {path} -> {response.status_code}: {response.text[:300]}")

    async def total(self, path: str) -> int:
        """How many items a listing holds, over every page."""
        count, cursor = 0, None
        while True:
            page = await self.get(path, limit=200, **({"cursor": cursor} if cursor else {}))
            count += len(page["items"])
            cursor = page["page"]["next_cursor"]
            if not cursor:
                return count

    async def counts(self) -> dict[str, int]:
        """What a query must not change: how many images, runs and identities the library holds."""
        return {
            "sources": await self.total("/sources"),
            "identities": await self.total("/identities"),
            "runs": await self.total("/processing-runs"),
        }


@asynccontextmanager
async def running(settings: LibrarySettings, providers: tuple[str, ...]) -> Any:
    secret = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode("ascii")
    app = create_backend_app(
        secret,
        settings,
        real_processing(settings, providers=providers),
        MediaLimits(PROVISIONAL_MAX_PIXELS, PROVISIONAL_MAX_BYTES),
    )
    async with app.router.lifespan_context(app):
        backend = app.state.backend
        if not await anyio.to_thread.run_sync(backend.settled.wait, 600):
            raise SystemExit("the application did not finish starting")
        if backend.failure is not None:
            raise SystemExit(f"the application failed to start: {backend.failure}")
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://gate",
            headers={"Authorization": f"Bearer {secret}"},
            timeout=httpx.Timeout(600.0),
        ) as client:
            yield Gate(client)


def choose_people(
    manifest: dict[str, Any], dataset: Path, count: int, minimum: int
) -> list[dict[str, Any]]:
    """People with enough photographs, in a stable order that depends only on their names.

    Every photograph must lie inside the dataset folder, and each distinct picture is used once
    (by content): a picture listed twice, or the same bytes under two names, could otherwise be
    enrolled and queried, and a query that finds itself inflates every number.
    """
    root = dataset.resolve()
    seen: set[str] = set()
    people = []
    for name, entries in manifest.items():
        files = []
        for entry in entries:
            path = (dataset / entry["file"]).resolve()
            if root not in path.parents:
                raise SystemExit(f"{entry['file']} is outside the dataset folder")
            expected = entry.get("sha256")  # (a verified manifest records what was reviewed)
            if not path.is_file():
                if expected:
                    raise SystemExit(f"{entry['file']} was verified but is missing")
                continue
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if expected and digest != expected:
                raise SystemExit(f"{entry['file']} changed after it was verified")
            if digest not in seen:
                seen.add(digest)
                files.append(path)
        files.sort()
        if len(files) >= minimum:
            held = max(1, len(files) // 4)
            people.append({"name": name, "enrol": files[:-held], "query": files[-held:]})
    people.sort(key=lambda p: hashlib.sha256(str(p["name"]).encode()).hexdigest())
    return people[:count]


def load_provenance(path: Path) -> dict[str, Any] | None:
    """The provenance an imported dataset carries (`import_labelled_dataset.py`), checked before a
    library is built: None when there is none, a stop when it is not what it must be."""
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        value = None
    if (
        not isinstance(value, dict)
        or value.get("schema_version") != 1
        or not all(isinstance(value.get(k), str) and value[k] for k in ("dataset", "labels_by"))
    ):
        raise SystemExit(f"{path} is not a valid provenance record (schema 1, dataset, labels_by)")
    return value


def subject(faces: list[dict[str, Any]], box: str) -> dict[str, Any] | None:
    """The one face a photograph is about: its only face, or one DOMINANCE times larger."""
    if not faces:
        return None

    def area(face: dict[str, Any]) -> float:
        return float(face[box]["width"] * face[box]["height"])

    ranked = sorted(faces, key=area, reverse=True)
    if len(ranked) == 1 or area(ranked[0]) >= DOMINANCE * area(ranked[1]):
        return ranked[0]
    return None


async def wait_for_runs(
    gate: Gate, run_ids: list[str], timeout: float = RUN_TIMEOUT
) -> dict[str, str]:
    states: dict[str, str] = {}
    deadline = asyncio.get_event_loop().time() + timeout
    pending = set(run_ids)
    while pending:
        for run_id in list(pending):
            run = await gate.get(f"/processing-runs/{run_id}")
            if run["state"] in ("COMPLETED", "FAILED", "CANCELLED"):
                states[run_id] = run["state"]
                pending.discard(run_id)
        if pending:
            if asyncio.get_event_loop().time() > deadline:
                raise SystemExit(f"{len(pending)} processing runs did not finish in time")
            await asyncio.sleep(1.0)
    return states


async def faces_of(gate: Gate, source_id: str) -> list[dict[str, Any]]:
    """Every face of a photograph: the ones nobody has placed and the ones already placed."""
    unplaced = (await gate.get(f"/sources/{source_id}/unresolved-faces"))["items"]
    placed = (await gate.get(f"/sources/{source_id}/occurrences"))["items"]
    faces = [
        {
            "bounding_box": f["bounding_box"],
            "representation_id": f["representation_id"],
            "occurrence": None,
        }
        for f in unplaced
    ]
    faces += [
        {
            "bounding_box": o["representative_observation"]["bounding_box"],
            "representation_id": None,
            "occurrence": o,
        }
        for o in placed
        if o["representative_observation"]
    ]
    return faces


async def enrol(
    gate: Gate,
    people: list[dict[str, Any]],
    log: dict[str, Any],
    run_timeout: float = RUN_TIMEOUT,
) -> dict[str, dict[str, Any]]:
    """Import and process the enrolment photographs, then place each subject into its person."""
    sources: dict[Path, str] = {}
    for person in people:
        for path in person["enrol"]:
            made = await gate.post(
                "/sources/import", {"path": str(path), "storage_mode": "MANAGED"}
            )
            sources[path] = made["id"]
    runs = {}
    for source_id in sources.values():
        runs[source_id] = (await gate.post(f"/sources/{source_id}/process"))["id"]
    states = await wait_for_runs(gate, list(runs.values()), run_timeout)
    log["processing"] = {
        "runs": len(states),
        "failed": sum(s != "COMPLETED" for s in states.values()),
    }

    enrolled: dict[str, dict[str, Any]] = {}
    skipped: dict[str, int] = {"no_face": 0, "no_subject": 0}
    for person in people:
        record: dict[str, Any] = {
            "identity_id": None,
            "person_id": None,
            "sources": [],
            "photos": [],
            "faces": 0,
        }
        for path in person["enrol"]:
            source_id = sources[path]
            faces = await faces_of(gate, source_id)
            chosen = subject(faces, "bounding_box")
            if chosen is None:
                skipped["no_face" if not faces else "no_subject"] += 1
                continue
            if chosen["occurrence"] is None:  # not placed by the application: place it
                placed = await gate.post(
                    f"/representations/{chosen['representation_id']}/resolve",
                    {"identity_id": record["identity_id"]},
                )
                identity_id = placed["identity_id"]
            else:  # the application already made an identity for it (an empty library does)
                identity_id = chosen["occurrence"]["identity_id"]
                if record["identity_id"] not in (None, identity_id):
                    await gate.post(
                        f"/occurrences/{chosen['occurrence']['id']}/reassign",
                        {
                            "expected_identity_id": identity_id,
                            "identity_id": record["identity_id"],
                        },
                    )
                    identity_id = record["identity_id"]
            if record["identity_id"] is None:
                record["identity_id"] = identity_id
                named = await gate.post(
                    "/people", {"display_name": person["name"], "identity_id": identity_id}
                )
                record["person_id"] = named["id"]
            record["sources"].append(source_id)
            record["photos"].append(path)
            record["faces"] += 1
        enrolled[person["name"]] = record
    log["enrolment"] = {
        "photographs_imported": len(sources),
        "faces_placed": sum(r["faces"] for r in enrolled.values()),
        "skipped_photographs": skipped,
        "people": {n: r["faces"] for n, r in enrolled.items()},
    }
    return enrolled


async def ask(gate: Gate, path: Path) -> dict[str, Any]:
    response = await gate.client.post(f"{API}/search/face", json={"path": str(path)})
    response.raise_for_status()
    body: dict[str, Any] = response.json()
    return body


def subject_status(answer: dict[str, Any]) -> str | None:
    """What the application itself said about the subject face (its own decision, not ours)."""
    chosen = subject(answer["faces"], "bounding_box")
    return None if chosen is None else str(chosen["status"])


def ranking(answer: dict[str, Any]) -> list[dict[str, Any]] | None:
    """The people offered for the photograph's subject face, best first (None: no subject face)."""
    chosen = subject(answer["faces"], "bounding_box")
    if chosen is None:
        return None
    offered = []
    for entry in chosen["possible_people"]:
        person = entry["identity"]["person"]
        offered.append(
            {
                "person": person["display_name"] if person else None,
                "similarity": entry["similarity"],  # (full precision: cut-offs compare it as is)
            }
        )
    return offered


async def run_queries(
    gate: Gate, people: list[dict[str, Any]], enrolled: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    results = []
    for person in people:
        for path in person["query"]:
            answer = await ask(gate, path)
            results.append(
                {
                    "person": person["name"],
                    "file": path.name,
                    "unknown": bool(person.get("unknown")),
                    "hard_negative": bool(person.get("hard_negative")),
                    "eligible": enrolled[person["name"]]["faces"] >= 2,
                    "offered": ranking(answer),
                    "status": subject_status(answer),
                }
            )
    return results


def wilson(k: int, n: int) -> list[float] | None:
    """The Wilson 95% interval of k out of n; None when nothing was observed (n = 0), because an
    interval of [0, 0] would read as evidence."""
    if n == 0:
        return None
    z, p = 1.96, k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    spread = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return [round(max(0.0, centre - spread), 3), round(min(1.0, centre + spread), 3)]


# Candidate similarity cut-offs the open-set table is read at: what a policy that accepted any
# top candidate at or above the cut-off would have done, known and unknown people alike.
THRESHOLDS = tuple(round(0.30 + 0.05 * step, 2) for step in range(11))


def same_name(name: str) -> str:
    """A name compared across datasets: underscores as spaces, case and spacing ignored."""
    return " ".join(name.replace("_", " ").casefold().split())


def digest_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pool_candidates(
    pool: list[dict[str, Any]], taken_names: list[str], taken_digests: set[str]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """The pool people who can be strangers: a name nobody in the main dataset has, no picture
    byte-identical to any of its pictures (one shared picture suggests the same person under
    another name, so the whole person is left out), and at least two pictures (the first, in
    sorted order, selects; the rest are scored)."""
    names = {same_name(name) for name in taken_names}
    kept: list[dict[str, Any]] = []
    dropped: dict[str, Any] = {"same_name": [], "shared_a_picture": [], "too_few_pictures": 0}
    for person in pool:
        if same_name(person["name"]) in names:
            dropped["same_name"].append(person["name"])
            continue
        files = sorted(person["enrol"] + person["query"])
        if any(digest_of(path) in taken_digests for path in files):
            dropped["shared_a_picture"].append(person["name"])
            continue
        if len(files) < 2:
            dropped["too_few_pictures"] += 1
            continue
        kept.append({"name": person["name"], "select": files[0], "score": files[1:]})
    return kept, dropped


def pick_hard_negatives(scored: list[tuple[str, float | None]], count: int) -> list[str]:
    """The `count` names whose selection score is highest (ties broken by a hash of the name, so
    the order the pool lists people in never matters). A candidate without a score (no subject
    face, or nobody offered) cannot be ranked and is left out."""
    ranked = sorted(
        ((score, name) for name, score in scored if score is not None),
        key=lambda item: (-item[0], hashlib.sha256(item[1].encode()).hexdigest()),
    )
    return [name for _, name in ranked[:count]]


async def choose_hard_negatives(
    gate: Gate, candidates: list[dict[str, Any]], count: int
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Search each candidate's selection photograph against the enrolled library and keep the
    `count` closest as never-enrolled people, scored on their other photographs only."""
    scored: list[tuple[str, float | None]] = []
    nearest: dict[str, Any] = {}
    for done, candidate in enumerate(candidates, 1):
        if done % 100 == 0:
            print(f"hard negatives: {done} of {len(candidates)} candidates searched", flush=True)
        offered = ranking(await ask(gate, candidate["select"]))
        top = offered[0] if offered else None
        scored.append((candidate["name"], top["similarity"] if top else None))
        nearest[candidate["name"]] = top
    chosen = pick_hard_negatives(scored, count)
    if len(chosen) < count:
        raise SystemExit(f"only {len(chosen)} pool people could be ranked; asked for {count}")
    by_name = {c["name"]: c for c in candidates}
    people = [
        {
            "name": name,
            "enrol": [],
            "query": by_name[name]["score"],
            "unknown": True,
            "hard_negative": True,
        }
        for name in chosen
    ]
    scores = sorted(s for _, s in scored if s is not None)
    log = {
        "candidates": len(candidates),
        "candidates_without_a_score": sum(1 for _, s in scored if s is None),
        "candidate_selection_similarity": {
            "min": scores[0] if scores else None,
            "median": statistics.median(scores) if scores else None,
            "max": scores[-1] if scores else None,
        },
        "chosen": [
            {
                "name": name,
                "selection_photograph": by_name[name]["select"].name,
                "nearest_enrolled_person": nearest[name]["person"],
                "selection_similarity": nearest[name]["similarity"],
                "scored_photographs": len(by_name[name]["score"]),
            }
            for name in chosen
        ],
    }
    return people, log


def partition_people(
    everyone: list[dict[str, Any]], *, known_count: int, minimum: int, unknown_count: int
) -> list[dict[str, Any]]:
    """The people to enrol (at least `minimum` photographs, `known_count` of them, in the stable
    order) and the people never enrolled (`unknown_count` of the rest, any with a photograph): all
    of an unknown person's photographs become open-set queries. No photograph is in both groups
    (`choose_people` has already used each distinct picture once)."""
    known = [p for p in everyone if len(p["enrol"]) + len(p["query"]) >= minimum][:known_count]
    named = {p["name"] for p in known}
    unknown = [
        {
            "name": person["name"],
            "enrol": [],
            "query": sorted(person["enrol"] + person["query"]),
            "unknown": True,
        }
        for person in [p for p in everyone if p["name"] not in named][:unknown_count]
    ]
    return known + unknown


def per_identity(results: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Retrieval by enrolled person: queries, first-place hits and hits within five."""
    table: dict[str, dict[str, int]] = {}
    for r in results:
        if r.get("unknown") or not r["eligible"] or r["offered"] is None:
            continue
        row = table.setdefault(r["person"], {"queries": 0, "recall_at_1": 0, "recall_at_5": 0})
        names = [o["person"] for o in r["offered"]]
        row["queries"] += 1
        if r["person"] in names[:1]:
            row["recall_at_1"] += 1
        if r["person"] in names[:5]:
            row["recall_at_5"] += 1
    return dict(sorted(table.items()))


def open_set(results: list[dict[str, Any]]) -> dict[str, Any]:
    """What happens to someone who was never enrolled, reported apart from closed-set retrieval.

    For each cut-off, a top candidate at or above it would be *accepted*: for an unknown person that
    is a false match; for a known person it is right or wrong. `policy` counts what the
    application itself decided under its real policy (accepting nothing, today)."""
    attempted = [r for r in results if r.get("unknown")]
    unknown = [r for r in attempted if r["offered"] is not None]
    known = [
        r for r in results if not r.get("unknown") and r["eligible"] and r["offered"] is not None
    ]

    def top(r: dict[str, Any]) -> float | None:
        return r["offered"][0]["similarity"] if r["offered"] else None

    table = []
    for cutoff in THRESHOLDS:
        false_accepts = sum(1 for r in unknown if (s := top(r)) is not None and s >= cutoff)
        right = sum(
            1
            for r in known
            if (s := top(r)) is not None
            and s >= cutoff
            and r["offered"][0]["person"] == r["person"]
        )
        wrong = sum(
            1
            for r in known
            if (s := top(r)) is not None
            and s >= cutoff
            and r["offered"][0]["person"] != r["person"]
        )
        table.append(
            {
                "cutoff": cutoff,
                "unknown_false_accepts": false_accepts,
                "unknown_false_accept_rate": round(false_accepts / len(unknown), 3)
                if unknown
                else None,
                "unknown_false_accept_wilson95": wilson(false_accepts, len(unknown)),
                "known_accepted_correct": right,
                "known_accepted_wrong": wrong,
                "known_recall_at_cutoff": round(right / len(known), 3) if known else None,
            }
        )
    scores = sorted(s for r in unknown if (s := top(r)) is not None)
    return {
        "unknown_people": sorted({r["person"] for r in unknown}),
        "unknown_queries_attempted": len(attempted),
        "unknown_queries_without_a_subject_face": len(attempted) - len(unknown),
        "unknown_queries": len(unknown),  # evaluated: those with a clear subject face
        "unknown_with_no_candidate": sum(1 for r in unknown if not r["offered"]),
        "known_queries": len(known),
        "policy": {
            "identity_answers_for_unknown_people": sum(
                1 for r in unknown if r["status"] == "IDENTITY_ANSWER"
            ),
            "possible_people_offered_for_unknown_people": sum(
                1 for r in unknown if r["status"] == "POSSIBLE_PEOPLE"
            ),
            "unknown_status_for_unknown_people": sum(
                1 for r in unknown if r["status"] == "UNKNOWN"
            ),
        },
        "unknown_top1_similarity": {
            "min": scores[0] if scores else None,
            "median": statistics.median(scores) if scores else None,
            "max": scores[-1] if scores else None,
        },
        "by_cutoff": table,
        "note": (
            "Closed-set retrieval does not show whether a stranger is rejected. Read the cut-off "
            "table as: at this similarity, how many strangers would have been accepted, and how "
            "many known people correctly."
        ),
    }


def metrics(results: list[dict[str, Any]]) -> dict[str, Any]:
    eligible = [r for r in results if r["eligible"] and r["offered"] is not None]
    hits1 = hits5 = 0
    reciprocal = 0.0
    for r in eligible:
        names = [o["person"] for o in r["offered"]]
        if r["person"] in names:
            rank = names.index(r["person"]) + 1
            reciprocal += 1.0 / rank
            hits1 += rank == 1
            hits5 += rank <= 5
    n = len(eligible)

    return {
        "queries": n,
        "recall_at_1": round(hits1 / n, 3) if n else None,
        "recall_at_1_wilson95": wilson(hits1, n),
        "recall_at_5": round(hits5 / n, 3) if n else None,
        "recall_at_5_wilson95": wilson(hits5, n),
        "mrr": round(reciprocal / n, 3) if n else None,
        "ineligible_or_no_subject": len([r for r in results if not r.get("unknown")]) - n,
    }


async def workflow(
    gate: Gate,
    people: list[dict[str, Any]],
    enrolled: dict[str, dict[str, Any]],
    log: dict[str, Any],
) -> dict[str, bool]:
    """Name search, recycle/restore, merge/split, permanent delete and forget, each checked."""
    checks: dict[str, bool] = {}
    rich = [p for p in people if enrolled[p["name"]]["faces"] >= 3]
    if len(rich) < 2:
        raise SystemExit(
            "the workflow needs two people with three enrolled faces: choose more people"
        )
    first, second = rich[0], rich[1]
    one, two = enrolled[first["name"]], enrolled[second["name"]]

    found = await gate.get("/search", q=first["name"].split()[0].lower())
    checks["name_search_finds_the_person"] = any(
        p["display_name"] == first["name"] for p in found["results"]["people"]
    )

    source_id = one["sources"][0]
    await gate.delete(f"/sources/{source_id}")
    default = await gate.get("/search", q=first["name"].lower())
    included = await gate.get("/search", q=first["name"].lower(), recycled="include")

    def count(found: dict[str, Any]) -> int:
        return len(found["results"]["occurrences"])

    checks["recycled_image_left_out_of_default_search"] = count(included) == count(default) + 1
    # the recycled image is itself the best witness: its own face is still in recognition memory
    own = ranking(await ask(gate, one["photos"][0])) or []
    checks["recycled_image_still_recognises_the_person"] = bool(own) and (
        own[0]["person"] == first["name"] and own[0]["similarity"] > 0.99
    )
    await gate.post(f"/sources/{source_id}/restore")
    restored = await gate.get("/search", q=first["name"].lower())
    checks["restore_returns_it_to_normal_search"] = count(restored) == count(included)

    # merge a second identity made from one photograph into the person, then split it off again
    spare = one["sources"][1]
    face = (await gate.get(f"/sources/{spare}/occurrences"))["items"][0]
    detached = await gate.post(
        f"/identities/{one['identity_id']}/split",
        {
            "occurrence_ids": [face["id"]],
            "expected_revision": (await gate.get(f"/identities/{one['identity_id']}"))["revision"],
        },
    )
    members = [
        {
            "id": one["identity_id"],
            "revision": (await gate.get(f"/identities/{one['identity_id']}"))["revision"],
        },
        {"id": detached["id"], "revision": detached["revision"]},
    ]
    await gate.post(
        "/identities/merge", {"identities": members, "preferred_identity_id": one["identity_id"]}
    )
    merged = await gate.get(f"/identities/{one['identity_id']}")
    checks["split_then_merge_restores_the_person"] = merged["occurrence_count"] == one["faces"]

    doomed = two["sources"][0]
    await gate.delete(f"/sources/{doomed}")
    await gate.post(f"/sources/{doomed}/permanent-delete")
    gone = await gate.client.get(f"{API}/sources/{doomed}")
    checks["permanently_deleted_image_is_gone"] = gone.status_code == 404

    await gate.post(f"/people/{two['person_id']}/forget")
    after = ranking(await ask(gate, second["query"][0]))
    checks["forgotten_person_is_not_recognised"] = not any(
        o["person"] == second["name"] for o in after or []
    )
    named = await gate.get("/search", q=second["name"].lower())
    hit = [p for p in named["results"]["people"] if p["display_name"] == second["name"]]
    checks["forgotten_person_stays_findable_by_name"] = (
        bool(hit) and hit[0]["biometric_memory_forgotten"]
    )
    log["workflow_people"] = {
        "recycled_and_merged": first["name"],
        "deleted_and_forgotten": second["name"],
    }
    return checks


async def main_async(args: argparse.Namespace) -> int:
    dataset, workdir = guard(Path(args.dataset)), guard(Path(args.workdir))
    report_path = guard(Path(args.report))
    if workdir.exists() and any(workdir.iterdir()):
        raise SystemExit(f"{workdir} is not empty; a gate run needs a fresh library")
    manifest_path = Path(args.manifest) if args.manifest else dataset / "manifest.json"
    manifest = json.loads(guard(manifest_path).read_text(encoding="utf-8"))
    provenance_path = dataset / "PROVENANCE.json"  # (an imported ready-labelled dataset)
    provenance = load_provenance(provenance_path)
    verified = manifest.get("kind") == "verified-manifest"
    if verified:  # a verified manifest from label_review.py: its schema is checked, its digests too
        if manifest.get("schema_version") != 1 or not isinstance(manifest.get("people"), dict):
            raise SystemExit("the verified manifest is not schema 1")
        manifest = manifest["people"]
    state = workdir / "local-state"
    for part in (
        "runtime",
        "policies",
    ):  # the installed models and the measured policy, not the indexes
        shutil.copytree(Path(args.local_state_root) / part, state / part)
    (workdir / "library").mkdir(parents=True, exist_ok=True)
    settings = LibrarySettings(
        library_root=workdir / "library",
        local_state_root=state,
        clock=lambda: datetime.now(UTC),
        new_id=uuid.uuid4,
        retry=PROVISIONAL_INDEX_RETRY,
        transaction_retry=PROVISIONAL_TRANSACTION_RETRY,
        index_batch=PROVISIONAL_INDEX_BATCH,
        max_index_passes=PROVISIONAL_INDEX_PASSES,
    )
    providers = providers_from(os.environ)
    everyone = choose_people(manifest, dataset, 10**6, 1)
    candidates: list[dict[str, Any]] = []
    pool_dropped: dict[str, Any] = {}
    pool_manifest_sha256 = None
    pool_provenance = None
    if args.hard_negatives:
        pool = guard(Path(args.hard_negative_pool))
        pool_manifest = pool / "manifest.json"
        pool_manifest_sha256 = hashlib.sha256(pool_manifest.read_bytes()).hexdigest()
        pool_provenance = load_provenance(pool / "PROVENANCE.json")
        # Everyone and every picture the main dataset lists, not only what the manifest in use
        # keeps: a person or picture left out of a verified export is still the same person.
        full = json.loads((dataset / "manifest.json").read_text(encoding="utf-8"))
        main_people = everyone + choose_people(full, dataset, 10**6, 1)
        candidates, pool_dropped = pool_candidates(
            choose_people(json.loads(pool_manifest.read_text(encoding="utf-8")), pool, 10**6, 1),
            list(manifest) + list(full),
            {digest_of(path) for p in main_people for path in p["enrol"] + p["query"]},
        )
    people = partition_people(
        everyone,
        known_count=args.people,
        minimum=args.minimum_photographs,
        unknown_count=args.unknown,
    )
    known_names = [p["name"] for p in people if not p.get("unknown")]
    log: dict[str, Any] = {"started": datetime.now(UTC).isoformat(), "providers": list(providers)}
    timings: dict[str, float] = {}  # seconds per phase: a long run shows where its time went
    log["timings_seconds"] = timings
    clock = time.monotonic()

    def phase(name: str) -> None:
        nonlocal clock
        now = time.monotonic()
        timings[name] = round(now - clock, 1)
        clock = now
        print(f"{name}: {timings[name]} s", flush=True)

    async with running(settings, providers) as gate:
        log["readiness"] = (await gate.client.get("/readiness")).json()
        enrolled = await enrol(gate, people, log, args.run_timeout)
        phase("enrolment")
        before = await gate.counts()
        if args.hard_negatives:  # (inside the count check: the selection queries write nothing)
            hard, log["hard_negatives"] = await choose_hard_negatives(
                gate, candidates, args.hard_negatives
            )
            log["hard_negatives"]["pool_left_out"] = pool_dropped
            for person in hard:
                enrolled[person["name"]] = {"identity_id": None, "sources": [], "faces": 0}
            people += hard
            phase("hard_negative_selection")
        results = await run_queries(gate, people, enrolled)
        phase("queries")
        after = await gate.counts()
        log["queries_wrote_nothing"] = before == after
        log["counts"] = {"before_queries": before, "after_queries": after}
        log["metrics"] = metrics(results)
        log["per_identity"] = per_identity(results)
        if args.unknown:  # random strangers only
            log["open_set"] = open_set([r for r in results if not r["hard_negative"]])
        if args.hard_negatives:  # known people and the hard negatives
            log["open_set_hard_negatives"] = open_set(
                [r for r in results if not r["unknown"] or r["hard_negative"]]
            )
        log["queries"] = results
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(
                {
                    "partial": True,
                    "configuration": {"run_timeout_seconds": args.run_timeout},
                    "log": log,
                },
                indent=1,
            ),
            encoding="utf-8",
        )
        print(
            json.dumps({"metrics": log["metrics"], "enrolment": log["enrolment"]}, indent=1),
            flush=True,
        )
        checks = await workflow(gate, people, enrolled, log)
        phase("workflow")
        settled = await run_queries(
            gate, people, enrolled
        )  # (after the workflow, before the restart)
        phase("queries_after_workflow")

    # restart: the same library, a new application
    async with running(settings, providers) as gate:
        again = await run_queries(gate, people, enrolled)
        checks["restart_keeps_name_search"] = bool(
            [p for p in (await gate.get("/search", q=known_names[0].lower()))["results"]["people"]]
        )
        checks["restart_gives_the_same_rankings"] = [r["offered"] for r in settled] == [
            r["offered"] for r in again
        ]
        log["restart_metrics_after_workflow"] = metrics(again)
    phase("restart_and_queries")

    used = hashlib.sha256(
        b"".join(
            hashlib.sha256(path.read_bytes()).digest()
            for person in people
            for path in sorted(person["enrol"] + person["query"])
        )
    ).hexdigest()
    weights = hashlib.sha256(
        json.dumps(sorted(os.listdir(state / "runtime" / "packages"))).encode()
    ).hexdigest()
    log["finished"] = datetime.now(UTC).isoformat()
    report = {
        "what": "TST-057A assisted recognition and the M5 real-world gate "
        + ("(human-verified labels)" if verified else "(labels unverified)"),
        "label_caveat": (
            "Labels come from a manifest exported by label_review.py: each photograph was "
            "verified by a human reviewer, and its digest was checked before use."
            if verified
            else (
                f"Identity labels were {provenance['labels_by']} ({provenance['dataset']}); "
                "this project has not verified them, and a mislabelled photograph can move the "
                "numbers either way. Not ground truth."
                if provenance
                else "Identity labels are Commons categories, not verified; a mislabelled "
                "photograph can move the numbers either way. Not ground truth."
            )
        ),
        "hard_negative_caveat": (
            "Hard negatives come from "
            + (
                f"{pool_provenance['dataset']}, whose labels were {pool_provenance['labels_by']}"
                if pool_provenance
                else "a pool without provenance"
            )
            + "; they are not verified by this project, so the same person under another name "
            "is possible, and the main dataset's label verification does not extend to them."
            if args.hard_negatives
            else None
        ),
        "configuration": {
            "package": PACKAGE_KEY,
            "people": len(people),
            "unknown_people": args.unknown,
            "hard_negatives": args.hard_negatives,
            "hard_negative_pool_manifest_sha256": pool_manifest_sha256,
            "minimum_photographs": args.minimum_photographs,
            "dominance": DOMINANCE,
            "run_timeout_seconds": args.run_timeout,
        },
        "environment": {
            "python": platform.python_version(),
            "onnxruntime": onnxruntime.__version__,
            "platform": platform.platform(),
            "package_listing_sha256": weights,
            "dataset_manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
            "photographs_used_sha256": used,  # (the manifest holds no per-file digest)
        },
        "workflow_checks": checks,
        "log": log,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps({"metrics": log["metrics"], "workflow_checks": checks}, indent=1))
    return 0 if all(checks.values()) and log["queries_wrote_nothing"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--local-state-root", required=True)
    parser.add_argument("--workdir", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--manifest", help="a verified manifest (label_review.py export)")
    parser.add_argument("--people", type=int, default=12)
    parser.add_argument(
        "--unknown",
        type=int,
        default=0,
        help="people never enrolled: their photographs are open-set queries (TST-057B)",
    )
    parser.add_argument(
        "--hard-negatives",
        type=int,
        default=0,
        help="strangers chosen from --hard-negative-pool by similarity to the enrolled people",
    )
    parser.add_argument("--hard-negative-pool", help="a second dataset folder (with manifest.json)")
    parser.add_argument("--minimum-photographs", type=int, default=5)
    parser.add_argument(
        "--run-timeout",
        type=positive_seconds,
        default=RUN_TIMEOUT,
        help="seconds to wait for the enrolment processing runs (a larger set needs longer)",
    )
    args = parser.parse_args()
    if args.hard_negatives < 0 or bool(args.hard_negatives) != bool(args.hard_negative_pool):
        parser.error("--hard-negatives N (N > 0) and --hard-negative-pool go together")
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
