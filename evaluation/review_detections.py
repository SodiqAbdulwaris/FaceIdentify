"""Find the faces in a review set's photographs, and suggest which one carries the label (#181).

    PYTHONPATH=. uv run python evaluation/review_detections.py --dataset evaluation/datasets/lfw \
        --local-state-root local-models/state --people "Ada Lovelace,Bob Barker"

This is the step before `label_review.py serve`. It runs the installed detector on each photograph
exactly as the application sees it (its own decoder, EXIF orientation applied, so the boxes are in
the upright normalised frame the gate and the operating-point script use) and appends one record per
photograph to `<dataset>/review/detections.jsonl`: every face found, the model's suggestion for the
photograph's label (if it has one), and the provenance (package key and version, detector and
embedder file digests, detector settings, decoder, suggestion method). It writes nothing else and
never touches the photographs or the manifest. Nothing it stores is ground truth: the reviewer
decides, in the page.

**What the suggestion is based on.** Not on size or position (a centred or largest face is a
dataset artefact, not evidence of who it is). A photograph with exactly one detected face suggests
that face ("sole face"). A photograph with several faces suggests the face that looks most like
faces in the *other photographs of the same label*: each face is scored by the mean, over the
other photographs, of its best cosine similarity to any face there (the person the label names
recurs; people standing beside them mostly do not). It is offered only when at least two other
photographs of the label have faces, the best face scores at least `OFFER_FLOOR` and strictly more
than the next. The score is a raw cosine consensus, not a calibrated confidence and not a
probability; the page says the suggestion is not verified, and the stored decision records whether
the reviewer confirmed, overrode or rejected it. The embeddings are used in memory only and are
never written.
"""

import argparse
import csv
import json
import sys
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Final, Protocol

import numpy as np
from numpy.typing import NDArray

from evaluation.label_review import Review, ReviewError

# The owner's measured different-person tail (2026-10-07, `measure_operating_point.TAIL_FLOOR`):
# used here only as "worth offering", never as a verdict on identity.
OFFER_FLOOR: Final = 0.326
MINIMUM_OTHER_PHOTOGRAPHS: Final = 2
SUGGESTION_METHOD: Final = (
    "sole face, else label recurrence: mean over the label's other photographs of the best cosine "
    f"to any face there; offered when at least {MINIMUM_OTHER_PHOTOGRAPHS} others have faces, "
    f"the best is at least {OFFER_FLOOR} and strictly above the next (uncalibrated)"
)


@dataclass(frozen=True)
class Seen:
    """One face as the detector saw it and the embedder read it (the vector is never stored)."""

    box: list[float]  # [x1, y1, x2, y2], normalised, upright
    score: float
    vector: NDArray[np.float32]


class Perceiver(Protocol):
    provenance: dict[str, Any]

    def see(self, pixels: NDArray[np.uint8]) -> list[Seen]: ...


def suggest(file: str, label_faces: dict[str, list[Seen]]) -> dict[str, Any] | None:
    """The suggestion for one photograph of a label, or None. `label_faces` holds every
    photograph of the label (by file name) with its faces; the order of anything never matters."""
    faces = label_faces.get(file, [])
    if not faces:
        return None
    if len(faces) == 1:
        return {
            "box": faces[0].box,
            "basis": "sole_face",
            "score": None,
            "rationale": "the only face the detector found (it is not checked against anyone)",
        }
    others = [seen for name, seen in label_faces.items() if name != file and seen]
    if len(others) < MINIMUM_OTHER_PHOTOGRAPHS:
        return None
    scored: list[tuple[float, int]] = []
    for position, face in enumerate(faces):
        best = [max(float(np.dot(face.vector, other.vector)) for other in seen) for seen in others]
        scored.append((sum(best) / len(best), position))
    scored.sort(key=lambda item: (-item[0], item[1]))
    (top, at), (second, _) = scored[0], scored[1]
    if top < OFFER_FLOOR or not top > second:
        return None
    return {
        "box": faces[at].box,
        "basis": "label_recurrence",
        "score": round(top, 4),
        "rationale": (
            f"the face most like faces in {len(others)} other photographs of this label "
            f"(mean best cosine {top:.2f}, the next face {second:.2f}); a raw similarity, "
            "not a probability or a confidence"
        ),
    }


def detect_dataset(
    review: Review,
    perceiver: Perceiver,
    decode: Callable[[bytes], NDArray[np.uint8]],
) -> dict[str, int]:
    """Detect every photograph of the people the review lists and append what was found.

    A record equal to the newest one of the same bytes (same faces, suggestion and provenance) is
    not appended again. Returns counts only."""
    counts = dict.fromkeys(
        (
            "photographs",
            "undecodable",
            "refused",
            "no_face",
            "one_face",
            "several_faces",
            "suggestions_offered",
            "appended",
            "unchanged",
        ),
        0,
    )
    wanted = [
        entry
        for entry in review.entries.values()
        if review.shown is None or entry["identity"] in review.shown
    ]
    seen: dict[str, dict[str, Any]] = {}
    for entry in sorted(wanted, key=lambda e: e["file"]):
        data, digest = review.read_photograph(entry["file"])
        counts["photographs"] += 1
        try:
            pixels = decode(data)
            faces = perceiver.see(pixels)
        except Exception:  # noqa: BLE001 - one bad photograph is counted, not fatal
            counts["undecodable"] += 1
            continue
        height, width = pixels.shape[:2]
        seen[entry["file"]] = {"digest": digest, "size": [int(width), int(height)], "faces": faces}
    by_label: dict[str, dict[str, list[Seen]]] = {}
    for entry in wanted:
        if entry["file"] in seen:
            by_label.setdefault(entry["identity"], {})[entry["file"]] = seen[entry["file"]]["faces"]
    existing = review.detections()
    for entry in sorted(wanted, key=lambda e: e["file"]):
        found = seen.get(entry["file"])
        if found is None:
            continue
        faces = found["faces"]
        counts["no_face" if not faces else "one_face" if len(faces) == 1 else "several_faces"] += 1
        suggestion = suggest(entry["file"], by_label[entry["identity"]])
        counts["suggestions_offered"] += suggestion is not None
        record = {
            "file": entry["file"],
            "sha256": found["digest"],
            "image_size": found["size"],
            "faces": [{"box": f.box, "score": f.score} for f in faces],
            "suggestion": suggestion,
            "provenance": perceiver.provenance,
        }
        before = existing.get(entry["file"])
        if before is not None and (
            before["faces"],
            before["suggestion"],
            before["provenance"],
            before["label"],
        ) == (record["faces"], record["suggestion"], record["provenance"], entry["identity"]):
            counts["unchanged"] += 1
            continue
        try:
            review.append_detection(record)
        except ReviewError:
            counts["refused"] += 1
        else:
            counts["appended"] += 1
    return counts


# --- the installed models ------------------------------------------------------------------


def installed(local_state_root: Path, provider: str) -> tuple[Perceiver, Callable[[], None]]:
    """The installed detector and embedder, run through the production worker. Returns the
    perceiver and the function that stops its worker."""
    from backend.app.runtime.package_store import RuntimePackageStore
    from backend.app.runtime.perception_client import PerceptionClient, supervisor_for
    from backend.infrastructure.storage.layout import StorageRoots
    from backend.ml.perception import detection
    from evaluation.measure_operating_point import KEY, POLICY, plan_from

    store = RuntimePackageStore(StorageRoots(Path(), local_state_root), new_id=uuid.uuid4)
    plan, _ = plan_from(store, provider)
    package = store.get(KEY)
    assert package is not None
    version = package.version
    detector, embedder = plan.detector[0], plan.embedder[0]
    supervisor = supervisor_for(plan, POLICY)
    client = PerceptionClient(supervisor, plan, new_id=uuid.uuid4)

    class Installed:
        provenance = {
            "package_key": KEY,
            "package_version": version,
            "detector": {
                "model_file": detector.model_path.name,
                "file_sha256": detector.sha256.hex(),
                "provider": detector.provider,
                "contract": asdict(detection.DetectorContract()),
            },
            "representation": {
                "model_file": embedder.model_path.name,
                "file_sha256": embedder.sha256.hex(),
            },
            "decode": "backend.infrastructure.media.image.decode_image (EXIF orientation applied)",
            "suggestion_method": SUGGESTION_METHOD,
            "tool": "evaluation/review_detections.py",
        }

        def see(self, pixels: NDArray[np.uint8]) -> list[Seen]:
            found = client.detect(pixels).detections
            vectors = client.represent(pixels, found).vectors
            return [
                Seen([float(v) for v in d.box], float(d.score), v.vector)
                for d, v in zip(found, vectors, strict=True)
            ]

    return Installed(), supervisor.stop


def production_decode(data: bytes) -> NDArray[np.uint8]:
    """The picture the application sees: its own decoder, EXIF orientation applied."""
    from backend.api.startup import PROVISIONAL_MAX_PIXELS
    from backend.infrastructure.media.image import decode_image

    pixels: NDArray[np.uint8] = decode_image(data, max_pixels=PROVISIONAL_MAX_PIXELS).pixels
    return pixels


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--local-state-root", required=True)
    parser.add_argument("--provider", default="CPUExecutionProvider")
    parser.add_argument(
        "--people", help="only these people (comma separated, names as the manifest has them)"
    )
    args = parser.parse_args(argv)
    review = Review(Path(args.dataset), "detector")
    if args.people is not None:
        review.focus([n for row in csv.reader([args.people]) for n in row if n.strip()])
    perceiver, stop = installed(Path(args.local_state_root), args.provider)
    try:
        counts = detect_dataset(review, perceiver, production_decode)
    finally:
        stop()
    print(json.dumps(counts, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
