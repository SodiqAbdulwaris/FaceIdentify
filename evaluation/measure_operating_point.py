"""Measure how the installed reference models separate people and pick an operating point.

This is TST-044, the initial evaluation.

    uv run python evaluation/measure_operating_point.py --dataset evaluation/datasets/commons-pd \
        --local-state-root local-models/state --report evaluation/datasets/reports/commons-pd.json

Protocol (open set, leave-one-out, subject-disjoint):

* A photograph is usable if it has a subject: its only face, or a face at least 2.5 times larger
  than any other. A person needs at least two usable photographs (one to enrol, one to query).
* People are split by a hash of their name into a *selection* half and a *final* half. The two
  halves share no person. Inside each half people are split again into *known* (the gallery) and
  *unknown* (never enrolled).
* Every usable photograph is a query against the known people of its own half, with itself left
  out; an identity scores as its best-matching photograph (the grouping the recognition assessment
  uses). A query needs at least two competing known identities to be counted.
* A query is *accepted* if its best score and its margin to the runner-up reach the policy; it is
  correct if the accepted identity is the person. An unknown person's accepted query is wrong.
* The operating point is chosen **on the selection half only**: the candidate thresholds are the
  scores actually observed; among the points with precision >= the target (0.99) and at least
  `--minimum-accepted` accepted queries and recall >= `--minimum-recall`, the one with the highest
  recall. If there is none, nothing is accepted automatically (ABSTAIN). The chosen point is then
  **reported on the final half**, which took no part in the choice, with a Wilson 95% interval.
* The new-identity ceiling is chosen the same way: the highest observed best-score below which at
  least the target share of queries truly are unknown people (with at least `--minimum-below`).

The numbers describe this small public-domain set only. Its identity labels are Commons categories,
not verified: a mislabelled photograph can make the result look better or worse, so the residual
label uncertainty has no direction. The report records the configuration, the environment, the
exclusions and the hash of the dataset manifest so the run can be repeated. Embeddings are cached
beside the dataset, keyed by the weights digest.
"""

import argparse
import hashlib
import json
import math
import platform
import uuid
from pathlib import Path
from typing import Any

import numpy as np
import onnxruntime
from PIL import Image

from backend.app.runtime.package_store import RuntimePackageStore
from backend.app.runtime.perception_client import PerceptionClient, supervisor_for
from backend.app.runtime.worker_config import PerceptionPlan, PlannedVariant
from backend.infrastructure.storage.layout import StorageRoots
from backend.ml.supervisor.supervisor import SupervisorPolicy

KEY = "insightface-buffalo-l"
POLICY = SupervisorPolicy(120, 120, 10, 10, 1, 600)
DEVICES = {"CUDAExecutionProvider": "GPU", "CPUExecutionProvider": "CPU"}
TARGET_PRECISION = 0.99
MARGINS = (0.0, 0.02, 0.05, 0.1)
DOMINANCE = 2.5  # a subject's face is this many times larger than any other face in the photograph
Query = tuple[str, str, float, float, bool]  # (person, best person, best score, runner-up, known)
Photo = tuple[str, str, np.ndarray]  # (person, file, vector)


def plan_from(store: RuntimePackageStore, provider: str) -> tuple[PerceptionPlan, str]:
    package = store.get(KEY)
    assert package is not None, f"{KEY} is not installed"
    components = {c.key: c for c in package.manifest.components}
    stages: dict[str, list[PlannedVariant]] = {"FACE_DETECTOR": [], "FACE_REPRESENTATION": []}
    digests = []
    for export in package.manifest.exports:
        component = components[export.component]
        digests.append(export.sha256.hex())
        stages[component.kind].append(
            PlannedVariant(
                uuid.uuid4(), uuid.uuid4(), component.kind,
                str(component.contract["preprocessing_contract"]), provider,
                DEVICES[provider], KEY, package.path / export.file, export.sha256,
            )
        )  # fmt: skip
    dimension = int(components["arcface-r50"].contract["dimension"])
    plan = PerceptionPlan(
        uuid.uuid4(),
        dimension,
        tuple(stages["FACE_DETECTOR"]),
        tuple(stages["FACE_REPRESENTATION"]),
    )
    return plan, hashlib.sha256("".join(digests).encode()).hexdigest()


def dominant(detections: tuple[Any, ...], ratio: float = DOMINANCE) -> Any:
    """The photograph's subject: its only face, or a face at least `ratio` times the area of the
    next one (a group photograph has no subject, so it is not used). None if there is none."""
    if not detections:
        return None

    def area(d: Any) -> float:
        x1, y1, x2, y2 = d.box
        return float((x2 - x1) * (y2 - y1))

    ranked = sorted(detections, key=area, reverse=True)
    if len(ranked) == 1 or area(ranked[0]) >= ratio * area(ranked[1]):
        return ranked[0]
    return None


def embed_dataset(
    dataset: Path, provider: str, store: RuntimePackageStore
) -> tuple[dict[str, Any], dict[str, np.ndarray], dict[str, int], str]:
    plan, digest = plan_from(store, provider)
    cache = dataset / f"embeddings-{digest[:12]}-subject.npz"
    manifest = json.loads((dataset / "manifest.json").read_text(encoding="utf-8"))
    skipped = {"no_face": 0, "no_subject": 0, "failed": 0}
    if cache.exists():
        stored = np.load(cache, allow_pickle=False)
        vectors = {name.replace("|", "/"): stored[name] for name in stored.files}
        skipped["not_embedded_in_the_cached_run"] = sum(
            len(photos) for photos in manifest.values()
        ) - len(vectors)
        return manifest, vectors, skipped, digest
    supervisor = supervisor_for(plan, POLICY)
    client = PerceptionClient(supervisor, plan, new_id=uuid.uuid4)
    vectors: dict[str, np.ndarray] = {}
    try:
        for photos in manifest.values():
            for photo in photos:
                try:
                    pixels = np.asarray(Image.open(dataset / photo["file"]).convert("RGB"))
                    detected = client.detect(pixels.astype(np.uint8))
                    subject = dominant(detected.detections)
                    if subject is None:
                        skipped["no_face" if not detected.detections else "no_subject"] += 1
                        continue
                    face = client.represent(pixels.astype(np.uint8), (subject,)).vectors[0]
                    vectors[photo["file"]] = face.vector
                except Exception:  # noqa: BLE001 - a bad photograph is skipped, and counted
                    skipped["failed"] += 1
    finally:
        supervisor.stop()
    np.savez(cache, **{name.replace("/", "|"): v for name, v in vectors.items()})
    return manifest, vectors, skipped, digest


def hashed(person: str, salt: str) -> int:
    return int(hashlib.sha256(f"{salt}:{person}".encode()).hexdigest(), 16)


def wilson(correct: int, total: int, z: float = 1.96) -> tuple[float, float]:
    if total == 0:
        return (0.0, 1.0)
    p = correct / total
    centre = p + z * z / (2 * total)
    spread = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total))
    denominator = 1 + z * z / total
    return ((centre - spread) / denominator, (centre + spread) / denominator)


def percentiles(values: list[float], points: list[float]) -> list[float]:
    return [round(float(x), 3) for x in np.percentile(values, points)] if values else []


def queries_of(photos: list[Photo], known: set[str]) -> tuple[list[Query], int]:
    """Every photograph as a query against the known people, itself left out; and how many were
    set aside for lack of two competing known identities."""
    gallery = [(p, f, v) for p, f, v in photos if p in known]
    matrix = np.stack([v for _, _, v in gallery]) if gallery else np.zeros((0, 1))
    queries: list[Query] = []
    set_aside = 0
    for person, file, vector in photos:
        scores = matrix @ vector
        best: dict[str, float] = {}
        for (who, other, _), score in zip(gallery, scores, strict=True):
            if other != file:
                best[who] = max(best.get(who, -np.inf), float(score))
        ranked = sorted(best.items(), key=lambda item: item[1], reverse=True)
        if len(ranked) < 2:
            set_aside += 1
            continue
        queries.append((person, ranked[0][0], ranked[0][1], ranked[1][1], person in known))
    return queries, set_aside


def accepted_at(queries: list[Query], threshold: float, margin: float) -> tuple[int, int]:
    """(accepted, correct) for a policy."""
    taken = [q for q in queries if q[2] >= threshold and q[2] - q[3] >= margin]
    return len(taken), sum(1 for q in taken if q[4] and q[0] == q[1])


def choose_policy(
    queries: list[Query], minimum_accepted: int, minimum_recall: float
) -> dict[str, Any] | None:
    known_queries = sum(1 for q in queries if q[4])
    best: dict[str, Any] | None = None
    for margin in MARGINS:
        for threshold in sorted({round(q[2], 4) for q in queries}):
            accepted, correct = accepted_at(queries, threshold, margin)
            if accepted < minimum_accepted or correct / accepted < TARGET_PRECISION:
                continue
            recall = correct / known_queries if known_queries else 0.0
            if recall < minimum_recall:
                continue
            if best is None or (recall, -threshold) > (best["recall"], -best["threshold"]):
                best = {
                    "margin": margin, "threshold": threshold, "accepted": accepted,
                    "correct": correct, "precision": correct / accepted, "recall": recall,
                }  # fmt: skip
    return best


def choose_ceiling(queries: list[Query], minimum_below: int) -> dict[str, Any] | None:
    best: dict[str, Any] | None = None
    for ceiling in sorted({round(q[2], 4) for q in queries}):
        below = [q for q in queries if q[2] < ceiling]
        if len(below) < minimum_below:
            continue
        share = sum(1 for q in below if not q[4]) / len(below)
        if share >= TARGET_PRECISION and (best is None or ceiling > best["ceiling"]):
            best = {"ceiling": ceiling, "below": len(below), "truly_new_share": share}
    return best


def evaluate_final(
    queries: list[Query], policy: dict[str, Any] | None, ceiling: dict[str, Any] | None
) -> dict[str, Any]:
    known_queries = sum(1 for q in queries if q[4])
    result: dict[str, Any] = {"queries": len(queries), "of_known_people": known_queries}
    if policy is None:
        result["match"] = "nothing accepted automatically: no point met the rule on the selection"
    else:
        accepted, correct = accepted_at(queries, policy["threshold"], policy["margin"])
        low, high = wilson(correct, accepted)
        result["match"] = {
            "accepted": accepted, "correct": correct,
            "precision": correct / accepted if accepted else None,
            "precision_95_interval": [round(low, 3), round(high, 3)],
            "recall": correct / known_queries if known_queries else None,
        }  # fmt: skip
    if ceiling is not None:
        below = [q for q in queries if q[2] < ceiling["ceiling"]]
        truly = sum(1 for q in below if not q[4])
        low, high = wilson(truly, len(below))
        result["new_identity"] = {
            "below": len(below), "truly_new": truly,
            "share": truly / len(below) if below else None,
            "share_95_interval": [round(low, 3), round(high, 3)],
        }  # fmt: skip
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--local-state-root", type=Path, required=True)
    parser.add_argument("--provider", default="CPUExecutionProvider")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--minimum-accepted", type=int, default=30)
    parser.add_argument("--minimum-recall", type=float, default=0.5)
    parser.add_argument("--minimum-below", type=int, default=20)
    arguments = parser.parse_args()
    roots = StorageRoots(Path(), arguments.local_state_root)
    store = RuntimePackageStore(roots, new_id=uuid.uuid4)
    manifest, vectors, skipped, digest = embed_dataset(arguments.dataset, arguments.provider, store)

    by_person: dict[str, list[Photo]] = {}
    for person, items in manifest.items():
        for item in items:
            if item["file"] in vectors:
                by_person.setdefault(person, []).append(
                    (person, item["file"], vectors[item["file"]])
                )
    single = sorted(p for p, v in by_person.items() if len(v) < 2)
    by_person = {p: v for p, v in by_person.items() if len(v) >= 2}

    halves: dict[str, dict[str, Any]] = {}
    for half in ("selection", "final"):
        people = sorted(
            p for p in by_person if (hashed(p, "half") % 2 == 0) == (half == "selection")
        )
        known = {p for p in people if hashed(p, half) % 10 < 7}
        photos = [x for p in people for x in by_person[p]]
        queries, set_aside = queries_of(photos, known)
        halves[half] = {"people": people, "known": known, "queries": queries, "aside": set_aside}

    policy = choose_policy(
        halves["selection"]["queries"], arguments.minimum_accepted, arguments.minimum_recall
    )
    ceiling = choose_ceiling(halves["selection"]["queries"], arguments.minimum_below)
    everyone = [x for v in by_person.values() for x in v]
    pairs = [(a, b) for i, a in enumerate(everyone) for b in everyone[i + 1 :]]
    genuine = [float(a[2] @ b[2]) for a, b in pairs if a[0] == b[0]]
    impostor = [float(a[2] @ b[2]) for a, b in pairs if a[0] != b[0]]
    manifest_hash = hashlib.sha256((arguments.dataset / "manifest.json").read_bytes()).hexdigest()
    report = {
        "configuration": {
            "provider": arguments.provider, "target_precision": TARGET_PRECISION,
            "minimum_accepted": arguments.minimum_accepted,
            "minimum_recall": arguments.minimum_recall, "minimum_below": arguments.minimum_below,
            "margins": MARGINS, "dominance": DOMINANCE,
        },
        "environment": {
            "python": platform.python_version(), "onnxruntime": onnxruntime.__version__,
            "platform": platform.platform(), "weights_digest": digest,
            "dataset_manifest_sha256": manifest_hash,
        },
        "exclusions": {
            "photographs_without_a_usable_subject": skipped,
            "people_with_a_single_usable_photograph": single,
        },
        "people_used": len(by_person),
        "photographs_used": len(everyone),
        "halves": {
            name: {
                "people": len(half["people"]), "known": len(half["known"]),
                "queries": len(half["queries"]), "set_aside_without_two_identities": half["aside"],
            }
            for name, half in halves.items()
        },
        "genuine_pairs": {
            "n": len(genuine), "percentiles": percentiles(genuine, [1, 5, 25, 50, 75])
        },
        "impostor_pairs": {
            "n": len(impostor), "percentiles": percentiles(impostor, [50, 95, 99, 99.9])
        },
        "chosen_on_selection_half": {"match": policy, "new_identity_ceiling": ceiling},
        "reported_on_final_half": evaluate_final(halves["final"]["queries"], policy, ceiling),
        "limits": (
            "Small public-domain set of formal adult photographs; labels are Commons categories, "
            "not verified; leave-one-out open set; point estimates carry the intervals shown."
        ),
    }  # fmt: skip
    arguments.report.parent.mkdir(parents=True, exist_ok=True)
    arguments.report.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
