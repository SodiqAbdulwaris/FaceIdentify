"""Run the installed reference models on real pictures through the production perception client.

    uv run python scripts/smoke_real_models.py --local-state-root <dir> \
        --providers CPUExecutionProvider img1.jpg img2.jpg

It builds the plan straight from the installed package (no library), starts the real worker behind
the supervisor, detects and embeds every face, and prints what it found, how long it took and the
cosine similarity of every pair of faces. A local developer check (issue 69), not part of CI: the
weights are never in the repository.
"""

import argparse
import time
import uuid
from itertools import combinations
from pathlib import Path

import numpy as np
from PIL import Image

from backend.app.runtime.package_store import RuntimePackageStore
from backend.app.runtime.perception_client import PerceptionClient, supervisor_for
from backend.app.runtime.worker_config import PerceptionPlan, PlannedVariant
from backend.infrastructure.storage.layout import StorageRoots
from backend.ml.supervisor.supervisor import SupervisorPolicy

POLICY = SupervisorPolicy(120, 120, 10, 10, 1, 600)
DEVICES = {"CUDAExecutionProvider": "GPU", "CPUExecutionProvider": "CPU"}


def plan_from(store: RuntimePackageStore, key: str, providers: list[str]) -> PerceptionPlan:
    package = store.get(key)
    assert package is not None, f"{key} is not installed"
    kinds = {c.key: c for c in package.manifest.components}
    stages: dict[str, list[PlannedVariant]] = {"FACE_DETECTOR": [], "FACE_REPRESENTATION": []}
    for export in package.manifest.exports:
        component = kinds[export.component]
        for provider in providers:
            stages[component.kind].append(
                PlannedVariant(
                    uuid.uuid4(), uuid.uuid4(), component.kind,
                    str(component.contract["preprocessing_contract"]), provider,
                    DEVICES[provider], key, package.path / export.file, export.sha256,
                )
            )  # fmt: skip
    dimension = int(kinds["arcface-r50"].contract["dimension"])
    return PerceptionPlan(
        uuid.uuid4(),
        dimension,
        tuple(stages["FACE_DETECTOR"]),
        tuple(stages["FACE_REPRESENTATION"]),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local-state-root", type=Path, required=True)
    parser.add_argument("--key", default="insightface-buffalo-l")
    parser.add_argument(
        "--providers", default="CPUExecutionProvider", help="comma-separated, preferred first"
    )
    parser.add_argument("--allow-fallback", action="store_true", help="accept a later provider")
    parser.add_argument("images", nargs="+", type=Path)
    arguments = parser.parse_args()

    store = RuntimePackageStore(StorageRoots(Path(), arguments.local_state_root), new_id=uuid.uuid4)
    providers = arguments.providers.split(",")
    plan = plan_from(store, arguments.key, providers)
    supervisor = supervisor_for(plan, POLICY)
    client = PerceptionClient(supervisor, plan, new_id=uuid.uuid4)
    vectors: list[tuple[str, np.ndarray]] = []
    try:
        for path in arguments.images:
            pixels = np.asarray(Image.open(path).convert("RGB"), dtype=np.uint8)
            started = time.perf_counter()
            detected = client.detect(pixels)
            found = time.perf_counter()
            represented = client.represent(pixels, detected.detections)
            done = time.perf_counter()
            ran = represented.ran.provider if represented.ran else "-"
            if represented.ran and not arguments.allow_fallback:
                assert ran == providers[0], f"ran on {ran}, not {providers[0]}"
            print(
                f"{path.name}: {len(detected.detections)} face(s); detect {found - started:.2f}s, "
                f"embed {done - found:.2f}s on {ran}; scores "
                f"{[round(d.score, 3) for d in detected.detections]}"
            )
            for i, vector in enumerate(represented.vectors):
                assert vector.vector.shape == (plan.dimension,), "wrong dimension"
                assert np.isfinite(vector.vector).all(), "a vector is not finite"
                assert abs(float(np.linalg.norm(vector.vector)) - 1.0) < 1e-4, "not a unit vector"
                vectors.append((f"{path.name}#{i}", vector.vector))
    finally:
        supervisor.stop()
    assert vectors, "no face was found in any picture"
    for (a, va), (b, vb) in combinations(vectors, 2):
        print(f"cosine {a} ~ {b}: {float(np.dot(va, vb)):.3f}")


if __name__ == "__main__":
    main()
