"""A real-worker integration smoke test of the SCRFD and ArcFace models (M5 R3; issue #69).

It runs the real models through the production perception client and supervised worker. It is not
an application workflow: it bypasses catalog registration, the host, the scheduler, persistence,
retrieval and the decision policy, so it is evidence that the models run, not that the product
recognises people (that is the M5 real-world gate).

Excluded from the default run (the weights are developer-supplied local files, never in the
repository or CI). Run it explicitly after installing the models and putting some pictures in
`local-models/images` (public-domain photographs are fine; they are Git-ignored):

    uv run python scripts/install_reference_models.py --models-dir local-models/buffalo_l \
        --detector det_10g.onnx --embedder w600k_r50.onnx --local-state-root local-models/state
    uv run pytest -m e2e tests/e2e/test_real_models.py

`FACEIDENTIFY_PROVIDER` selects the provider (default `CPUExecutionProvider`). Pictures named
`<person>N.jpg` (for example `collins1.jpg`, `collins2.jpg`) are of the same person when the
letters match. It proves the pipeline works on real weights: faces are found, vectors are valid
unit vectors of the model's dimension, and the same person scores higher than different people.
It is not calibration (TST-044).
"""

import os
import re
import uuid
from itertools import combinations
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from backend.app.runtime.package_store import RuntimePackageStore
from backend.app.runtime.perception_client import PerceptionClient, supervisor_for
from backend.app.runtime.worker_config import PerceptionPlan, PlannedVariant
from backend.infrastructure.storage.layout import StorageRoots
from backend.ml.supervisor.supervisor import SupervisorPolicy

ROOT = Path(__file__).resolve().parents[2] / "local-models"
STATE = ROOT / "state"
IMAGES = ROOT / "images"
KEY = "insightface-buffalo-l"
PROVIDER = os.environ.get("FACEIDENTIFY_PROVIDER", "CPUExecutionProvider")
DEVICES = {"CUDAExecutionProvider": "GPU", "CPUExecutionProvider": "CPU"}
POLICY = SupervisorPolicy(120, 120, 10, 10, 1, 600)

pytestmark = pytest.mark.e2e


def plan() -> PerceptionPlan:
    store = RuntimePackageStore(StorageRoots(Path(), STATE), new_id=uuid.uuid4)
    package = store.get(KEY)
    assert package is not None, f"{KEY} is not installed under {STATE}: see this file's docstring"
    components = {c.key: c for c in package.manifest.components}
    stages: dict[str, list[PlannedVariant]] = {"FACE_DETECTOR": [], "FACE_REPRESENTATION": []}
    for export in package.manifest.exports:
        component = components[export.component]
        stages[component.kind].append(
            PlannedVariant(
                uuid.uuid4(), uuid.uuid4(), component.kind,
                str(component.contract["preprocessing_contract"]), PROVIDER,
                DEVICES[PROVIDER], KEY, package.path / export.file, export.sha256,
            )
        )  # fmt: skip
    dimension = int(components["arcface-r50"].contract["dimension"])
    return PerceptionPlan(
        uuid.uuid4(),
        dimension,
        tuple(stages["FACE_DETECTOR"]),
        tuple(stages["FACE_REPRESENTATION"]),
    )


def test_real_faces_are_found_embedded_and_the_same_person_scores_higher() -> None:
    pictures = sorted(IMAGES.glob("*.jpg"))
    assert len(pictures) >= 3, f"put at least three pictures in {IMAGES}"
    perception = plan()
    supervisor = supervisor_for(perception, POLICY)
    client = PerceptionClient(supervisor, perception, new_id=uuid.uuid4)
    faces: list[tuple[str, str, np.ndarray]] = []  # (person, picture, vector)
    try:
        for picture in pictures:
            pixels = np.asarray(Image.open(picture).convert("RGB"), dtype=np.uint8)
            detected = client.detect(pixels)
            represented = client.represent(pixels, detected.detections)
            assert detected.ran.provider == PROVIDER  # no silent fallback in detection either
            assert len(represented.vectors) == len(detected.detections)
            if represented.ran is not None:
                assert represented.ran.provider == PROVIDER  # no silent fallback
            person = re.sub(r"\d+$", "", picture.stem)
            for index, face in enumerate(represented.vectors):
                assert face.vector.shape == (perception.dimension,)
                assert np.isfinite(face.vector).all()
                assert abs(float(np.linalg.norm(face.vector)) - 1.0) < 1e-4
                faces.append((person, f"{picture.name}#{index}", face.vector))
    finally:
        supervisor.stop()

    assert faces, "no face was found in any picture"
    # The first face of each picture is the picture's subject (best score first).
    subjects: dict[str, tuple[str, np.ndarray]] = {}
    for person, name, vector in faces:
        subjects.setdefault(name.split("#")[0], (person, vector))
    same = [
        float(np.dot(a[1], b[1])) for a, b in combinations(subjects.values(), 2) if a[0] == b[0]
    ]
    different = [
        float(np.dot(a[1], b[1])) for a, b in combinations(subjects.values(), 2) if a[0] != b[0]
    ]
    assert same, "need two pictures of one person"
    assert different, "need a picture of another person"
    assert min(same) > max(different), (same, different)
