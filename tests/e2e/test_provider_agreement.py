"""DirectML and the CPU give the same face vectors (M7 step 7; TST-076, TST-074 on this machine).

A provider is how the model runs, not what it computes: the representation space, and so the
calibrated policy bound to it, must not change with the provider. The agreement recorded on
2026-10-16 (largest 1 - cosine 1.25e-6 over 686 faces, `docs/implementations/2026-10-16-directml-
remeasure.md`) is re-asserted here on the real weights: the same faces (found once, on the CPU) are
embedded on the CPU and on DirectML through the production client and worker, and every pair must
agree to within 1e-5 (1 - cosine), with no silent fallback on either side.

Excluded from the default run (the weights are developer-supplied local files, never in CI). Run it
explicitly on a machine with DirectML, with the pictures of `test_real_models.py`:

    uv run pytest -m e2e tests/e2e/test_provider_agreement.py
"""

import os
import uuid
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PIL import Image

from backend.app.runtime.perception_client import PerceptionClient, supervisor_for
from backend.app.runtime.worker_config import PerceptionPlan
from backend.ml.contracts.messages import Detection
from tests.e2e import test_real_models as real

pytestmark = pytest.mark.e2e

# A worktree has no `local-models` of its own: `FACEIDENTIFY_E2E_LOCAL_MODELS` names the folder
# (read only) instead of linking it into the worktree.
if given := os.environ.get("FACEIDENTIFY_E2E_LOCAL_MODELS"):
    real.STATE, real.IMAGES = Path(given) / "state", Path(given) / "images"

TOLERANCE = 1e-5  # 1 - cosine; the recorded worst case is 1.25e-6


def planned(provider: str) -> PerceptionPlan:
    """The installed package's plan on one provider (and no other: no fallback)."""
    original = real.PROVIDER
    real.PROVIDER = provider
    try:
        return real.plan()
    finally:
        real.PROVIDER = original


def embed(
    plan: PerceptionPlan, pictures: list[Any], detections: list[tuple[Detection, ...]]
) -> list[list[Any]]:
    supervisor = supervisor_for(plan, real.POLICY)
    client = PerceptionClient(supervisor, plan, new_id=uuid.uuid4)
    try:
        vectors = []
        for pixels, found in zip(pictures, detections, strict=True):
            represented = client.represent(pixels, found)
            if represented.ran is not None:
                assert represented.ran.provider == plan.embedder[0].provider  # no fallback
            vectors.append([face.vector for face in represented.vectors])
        return vectors
    finally:
        supervisor.stop()


def test_directml_and_the_cpu_embed_the_same_faces_alike() -> None:
    paths = sorted(real.IMAGES.glob("*.jpg"))
    assert paths, f"put pictures in {real.IMAGES} (see tests/e2e/test_real_models.py)"
    pictures = [np.asarray(Image.open(p).convert("RGB"), dtype=np.uint8) for p in paths]
    cpu = planned("CPUExecutionProvider")
    supervisor = supervisor_for(cpu, real.POLICY)
    client = PerceptionClient(supervisor, cpu, new_id=uuid.uuid4)
    try:
        detected = [client.detect(pixels) for pixels in pictures]
    finally:
        supervisor.stop()
    assert all(d.ran.provider == cpu.detector[0].provider for d in detected)  # no fallback
    detections = [d.detections for d in detected]
    assert any(detections), "no face was found in any picture"

    on_cpu = embed(cpu, pictures, detections)
    on_dml = embed(planned("DmlExecutionProvider"), pictures, detections)

    drift = [
        1.0 - float(np.dot(a.astype(np.float64), b.astype(np.float64)))  # (float32 rounds to 1)
        for faces_cpu, faces_dml in zip(on_cpu, on_dml, strict=True)
        for a, b in zip(faces_cpu, faces_dml, strict=True)
    ]
    assert drift
    assert max(drift) <= TOLERANCE, max(drift)
    assert all(
        a.shape == b.shape
        for f1, f2 in zip(on_cpu, on_dml, strict=True)
        for a, b in zip(f1, f2, strict=True)
    )
