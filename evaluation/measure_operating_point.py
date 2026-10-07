"""Measure how the installed reference models separate people and pick an operating point.

This is TST-044, the initial evaluation.

    uv run python evaluation/measure_operating_point.py --dataset evaluation/datasets/commons-pd \
        --local-state-root local-models/state --report evaluation/reports/commons-pd.json

Open-set protocol, leave-one-out. Persons are split once, deterministically (by a hash of their
name), into *known* (the gallery) and *unknown* (never in the gallery). Every photograph with
exactly one detected face is a query: its gallery is every other photograph of the known people, an
identity scores as its best-matching photograph (the same grouping the recognition assessment
uses), and the query's best identity, best score and margin to the runner-up are recorded.

* A query is **accepted** if best score >= match threshold and margin >= the margin. It is correct
  if the accepted identity is the person; a query of an unknown person that is accepted is wrong.
* The operating point is the policy that reaches at least the target precision (0.99) for accepted
  queries with the highest recall; if none reaches it, nothing is accepted automatically.
* A query whose best score is below the ceiling is **a new identity**; the ceiling is the highest
  value at which at least the target share of such queries truly are new people.

The numbers describe this small public-domain set only; the report says so. The embeddings are
cached next to the dataset, keyed by the weights digest.
"""

import argparse
import hashlib
import json
import math
import uuid
from pathlib import Path

import numpy as np
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


def embed_dataset(dataset: Path, provider: str, store: RuntimePackageStore) -> tuple[dict, dict]:  # type: ignore[type-arg]
    plan, digest = plan_from(store, provider)
    cache = dataset / f"embeddings-{digest[:12]}.npz"
    manifest = json.loads((dataset / "manifest.json").read_text(encoding="utf-8"))
    if cache.exists():
        stored = np.load(cache, allow_pickle=False)
        vectors = {name: stored[name] for name in stored.files}
        return manifest, vectors
    supervisor = supervisor_for(plan, POLICY)
    client = PerceptionClient(supervisor, plan, new_id=uuid.uuid4)
    vectors: dict[str, np.ndarray] = {}
    skipped = {"none": 0, "several": 0, "failed": 0}
    try:
        for photos in manifest.values():
            for photo in photos:
                try:
                    pixels = np.asarray(Image.open(dataset / photo["file"]).convert("RGB"))
                    detected = client.detect(pixels.astype(np.uint8))
                    if len(detected.detections) != 1:
                        skipped["none" if not detected.detections else "several"] += 1
                        continue
                    face = client.represent(pixels.astype(np.uint8), detected.detections).vectors[0]
                    vectors[photo["file"]] = face.vector
                except Exception:  # noqa: BLE001 - a bad photograph is skipped, and counted
                    skipped["failed"] += 1
    finally:
        supervisor.stop()
    print("skipped photographs:", skipped)
    np.savez(cache, **{name.replace("/", "|"): v for name, v in vectors.items()})
    return manifest, {name.replace("/", "|"): v for name, v in vectors.items()}


def is_known(person: str) -> bool:
    """Deterministic 70/30 split of people into known and unknown."""
    return int(hashlib.sha256(person.encode()).hexdigest(), 16) % 10 < 7


def spread(values: list[float], points: list[float]) -> list[float]:
    return [round(float(x), 3) for x in np.percentile(values, points)]


def wilson_lower(correct: int, total: int, z: float = 1.96) -> float:
    if total == 0:
        return 0.0
    p = correct / total
    centre = p + z * z / (2 * total)
    spread = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total))
    return (centre - spread) / (1 + z * z / total)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--local-state-root", type=Path, required=True)
    parser.add_argument("--provider", default="CPUExecutionProvider")
    parser.add_argument("--report", type=Path, required=True)
    arguments = parser.parse_args()
    store = RuntimePackageStore(StorageRoots(Path(), arguments.local_state_root), uuid.uuid4)  # type: ignore[arg-type]
    manifest, vectors = embed_dataset(arguments.dataset, arguments.provider, store)

    photos: list[tuple[str, str, np.ndarray]] = []  # (person, file, vector)
    for person, items in manifest.items():
        for item in items:
            key = item["file"].replace("/", "|")
            if key in vectors:
                photos.append((person, item["file"], vectors[key]))
    known_people = sorted({p for p, _, _ in photos if is_known(p)})
    unknown_people = sorted({p for p, _, _ in photos if not is_known(p)})
    gallery = [(p, f, v) for p, f, v in photos if is_known(p)]
    gallery_matrix = np.stack([v for _, _, v in gallery])
    gallery_people = np.array([p for p, _, _ in gallery])

    queries = []  # (truth, best_person, best, second, known_truth)
    for person, file, vector in photos:
        scores = gallery_matrix @ vector
        mask = np.array([f != file for _, f, _ in gallery])  # leave this photograph out
        scores = np.where(mask, scores, -np.inf)
        best: dict[str, float] = {}
        for who, score in zip(gallery_people, scores, strict=True):
            best[who] = max(best.get(who, -np.inf), float(score))
        ranked = sorted(best.items(), key=lambda item: item[1], reverse=True)
        if len(ranked) < 2:
            continue
        queries.append((person, ranked[0][0], ranked[0][1], ranked[1][1], is_known(person)))

    known_queries = sum(1 for q in queries if q[4])
    sweep = []
    for margin in MARGINS:
        for threshold in np.round(np.arange(0.2, 0.9, 0.01), 2):
            accepted = [q for q in queries if q[2] >= threshold and q[2] - q[3] >= margin]
            correct = sum(1 for q in accepted if q[4] and q[0] == q[1])
            sweep.append(
                {
                    "margin": margin, "threshold": float(threshold), "accepted": len(accepted),
                    "correct": correct,
                    "precision": correct / len(accepted) if accepted else None,
                    "precision_lower_95": wilson_lower(correct, len(accepted)),
                    "recall": correct / known_queries if known_queries else 0.0,
                }
            )  # fmt: skip
    ok = [s for s in sweep if s["precision"] is not None and s["precision"] >= TARGET_PRECISION]
    chosen = max(ok, key=lambda s: (s["recall"], -s["threshold"])) if ok else None

    ceilings = []
    for ceiling in np.round(np.arange(0.1, 0.9, 0.01), 2):
        below = [q for q in queries if q[2] < ceiling]
        truly_new = sum(1 for q in below if not q[4])
        ceilings.append(
            {
                "ceiling": float(ceiling), "below": len(below),
                "truly_new_share": truly_new / len(below) if below else None,
            }
        )  # fmt: skip
    usable = [
        c
        for c in ceilings
        if c["truly_new_share"] is not None and c["truly_new_share"] >= TARGET_PRECISION
    ]
    new_ceiling = max(usable, key=lambda c: c["ceiling"]) if usable else None

    genuine = [
        float(a @ b)
        for (pa, fa, a), (pb, fb, b) in (
            (x, y) for i, x in enumerate(photos) for y in photos[i + 1 :]
        )
        if pa == pb
    ]
    impostor = [
        float(a @ b)
        for (pa, fa, a), (pb, fb, b) in (
            (x, y) for i, x in enumerate(photos) for y in photos[i + 1 :]
        )
        if pa != pb
    ]
    report = {
        "dataset": str(arguments.dataset.name),
        "photographs_used": len(photos),
        "people": {"known": len(known_people), "unknown": len(unknown_people)},
        "queries": {"total": len(queries), "of_known_people": known_queries},
        "genuine_pairs": {"n": len(genuine), "percentiles": spread(genuine, [1, 5, 25, 50, 75])},
        "impostor_pairs": {"n": len(impostor), "percentiles": spread(impostor, [50, 95, 99, 99.9])},
        "target_precision": TARGET_PRECISION,
        "chosen": chosen,
        "new_identity_ceiling": new_ceiling,
        "sweep": sweep,
        "ceilings": ceilings,
        "limits": "Small public-domain set of formal adult photographs; leave-one-out open set.",
    }  # fmt: skip
    arguments.report.parent.mkdir(parents=True, exist_ok=True)
    arguments.report.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k not in ("sweep", "ceilings")}, indent=1))


if __name__ == "__main__":
    main()
