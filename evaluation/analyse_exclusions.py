"""Where do photographs drop out before recognition? A read-only diagnostic (M5, 2026-10-13).

    PYTHONPATH=. uv run python evaluation/analyse_exclusions.py --dataset evaluation/datasets/lfw \
        --local-state-root local-models/state --people 100 --unknown 50 \
        --report evaluation/datasets/reports/exclusions-lfw.json

It runs the installed SCRFD detector in this process, on exactly the photographs the assisted gate
used, and records every face the detector sees, including the ones the production contract
discards (score below its 0.5 floor, or a landmark outside the image). It then applies the gate's
subject rule (`DOMINANCE`) to the production faces and, separately, to counterfactual settings, so
the effect of each rule is measured on its own and the overlaps are visible.

It changes nothing: no library, no policy, no threshold. The counterfactuals are measurements, not
proposals. It does not embed or match anything: identity accuracy is a separate question. The
report names photographs, so it stays under the Git-ignored `evaluation/datasets/`.
"""

import argparse
import json
import sys
import uuid
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

from backend.app.runtime.package_store import RuntimePackageStore
from backend.infrastructure.storage.layout import StorageRoots
from backend.ml.perception import detection
from backend.ml.worker.onnx_session import load_session
from evaluation.assisted_recognition_gate import (
    DOMINANCE,
    choose_people,
    guard,
    partition_people,
)
from scripts.smoke_real_models import plan_from

PRODUCTION_FLOOR = detection.DetectorContract().score_threshold  # 0.5
DIAGNOSTIC_FLOOR = 0.05  # what the detector sees; used only to look, never to decide
BUCKETS = ((1.0, 1.5), (1.5, 2.0), (2.0, DOMINANCE))


def _nms(boxes: np.ndarray, scores: np.ndarray) -> list[int]:
    if not len(boxes):
        return []
    return detection.non_maximum_suppression(boxes, scores, detection.DetectorContract().nms_iou)


def look(session: Any, input_name: str, pixels: np.ndarray) -> dict[str, Any]:
    """Every candidate of one image, split the way the production contract would split it."""
    contract = detection.DetectorContract(score_threshold=DIAGNOSTIC_FLOOR)
    boxed = detection.letterbox(pixels, contract)
    outputs = [
        np.asarray(o, dtype=np.float32) for o in session.run(None, {input_name: boxed.tensor})
    ]
    height, width = pixels.shape[:2]
    # production decode, for the cross-check below
    production = detection.decode(
        outputs, detection.DetectorContract(), boxed.scale, (height, width)
    )

    # the same decoding as detection.decode, kept candidate by candidate (a diagnostic copy)
    boxes, scores, points = [], [], []
    for level, stride in enumerate(detection.STRIDES):
        centres = detection._anchor_centres(contract.input_size, stride)
        score = outputs[level][:, 0]
        distance = outputs[level + 3] * stride
        offset = outputs[level + 6]
        keep = score >= DIAGNOSTIC_FLOOR
        c, s, d, o = centres[keep], score[keep], distance[keep], offset[keep]
        boxes.append(
            np.stack(
                [c[:, 0] - d[:, 0], c[:, 1] - d[:, 1], c[:, 0] + d[:, 2], c[:, 1] + d[:, 3]], 1
            )
        )
        scores.append(s)
        points.append(c[:, None, :] + o.reshape(-1, detection.LANDMARKS, 2) * stride)
    b = np.concatenate(boxes) / boxed.scale
    s = np.concatenate(scores)
    p = np.concatenate(points) / boxed.scale
    b[:, [0, 2]] = np.clip(b[:, [0, 2]], 0.0, width)
    b[:, [1, 3]] = np.clip(b[:, [1, 3]], 0.0, height)
    usable = (
        (b[:, 0] < b[:, 2])
        & (b[:, 1] < b[:, 3])
        & (p[:, :, 0] >= 0).all(axis=1)
        & (p[:, :, 0] <= width).all(axis=1)
        & (p[:, :, 1] >= 0).all(axis=1)
        & (p[:, :, 1] <= height).all(axis=1)
    )

    def faces(mask: np.ndarray) -> list[dict[str, Any]]:
        bb, ss = b[mask], s[mask]
        return [
            {
                "score": round(float(ss[i]), 4),
                "box": [
                    round(float(bb[i, 0]) / width, 4),
                    round(float(bb[i, 1]) / height, 4),
                    round(float(bb[i, 2]) / width, 4),
                    round(float(bb[i, 3]) / height, 4),
                ],
            }
            for i in _nms(bb, ss)
        ]

    kept = faces(usable & (s >= PRODUCTION_FLOOR))
    mine = sorted(f["score"] for f in kept)  # the diagnostic copy must equal production
    theirs = sorted(round(f.score, 4) for f in production)
    assert len(mine) == len(theirs), "the diagnostic decoding no longer matches production"
    assert np.allclose(mine, theirs, atol=1e-3), "the diagnostic scores differ from production"
    below = [f for f in faces(usable & (s >= DIAGNOSTIC_FLOOR)) if f["score"] < PRODUCTION_FLOOR]
    # a face the border rule removed: confident, but alignment would need a landmark outside
    cut = [
        f for f in faces(~usable & (s >= PRODUCTION_FLOOR)) if not any(_overlap(f, k) for k in kept)
    ]
    return {"size": [width, height], "kept": kept, "below_floor": below, "border_dropped": cut}


def _overlap(a: dict[str, Any], b: dict[str, Any]) -> bool:
    ax0, ay0, ax1, ay1 = a["box"]
    bx0, by0, bx1, by1 = b["box"]
    inter = max(0.0, min(ax1, bx1) - max(ax0, bx0)) * max(0.0, min(ay1, by1) - max(ay0, by0))
    union = (ax1 - ax0) * (ay1 - ay0) + (bx1 - bx0) * (by1 - by0) - inter
    return bool(union > 0 and inter / union > detection.DetectorContract().nms_iou)


def area(face: dict[str, Any]) -> float:
    x0, y0, x1, y1 = face["box"]
    return float((x1 - x0) * (y1 - y0))


def verdict(faces: list[dict[str, Any]], dominance: float) -> str:
    """The gate's `subject` rule, on detector output: ok, no_face or no_subject."""
    if not faces:
        return "no_face"
    ranked = sorted((area(f) for f in faces), reverse=True)
    return "ok" if len(ranked) == 1 or ranked[0] >= dominance * ranked[1] else "no_subject"


def faces_at(rec: dict[str, Any], floor: float) -> list[dict[str, Any]]:
    """The faces kept at a floor; below-floor faces are added only when they do not duplicate a
    kept one (the diagnostic NMS already separated them)."""
    pool = rec["kept"] + rec["below_floor"]
    return [f for f in pool if f["score"] >= floor]


def _touches_border(face: dict[str, Any], margin: float = 0.01) -> bool:
    x0, y0, x1, y1 = face["box"]
    return bool(x0 <= margin or y0 <= margin or x1 >= 1 - margin or y1 >= 1 - margin)


def _centre_distance(face: dict[str, Any]) -> float:
    x0, y0, x1, y1 = face["box"]
    return float(np.hypot((x0 + x1) / 2 - 0.5, (y0 + y1) / 2 - 0.5))


def describe(rec: dict[str, Any]) -> dict[str, Any]:
    """Why a photograph is excluded, as facts a person can check against the picture."""
    state = verdict(rec["kept"], DOMINANCE)
    out: dict[str, Any] = {"status": state, "faces": len(rec["kept"])}
    if state == "no_face":
        # flags, not one cause: both can hold, and a border-dropped face may be someone else
        out["below_floor_faces"] = len(rec["below_floor"])
        out["border_dropped_faces"] = len(rec["border_dropped"])
        out["best_below_floor_score"] = max((f["score"] for f in rec["below_floor"]), default=None)
        out["largest_below_floor_area_fraction"] = round(
            max((area(f) for f in rec["below_floor"]), default=0.0), 4
        )
    elif state == "no_subject":
        ranked = sorted(rec["kept"], key=area, reverse=True)
        ratio = area(ranked[0]) / area(ranked[1])
        out["ratio"] = round(ratio, 3)
        out["bucket"] = next(f"{lo}-{hi}" for lo, hi in BUCKETS if lo <= ratio < hi)
        out["second_score"] = ranked[1]["score"]
        out["second_area_fraction"] = round(area(ranked[1]), 4)
        out["largest_area_fraction"] = round(area(ranked[0]), 4)
        out["second_touches_border"] = _touches_border(ranked[1])
        out["largest_is_most_central"] = min(rec["kept"], key=_centre_distance) is ranked[0]
    return out


def counterfactuals(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Each rule alone, against the production baseline. Diagnostic; nothing here is a proposal."""
    base = [verdict(r["kept"], DOMINANCE) for r in records]
    table: dict[str, Any] = {"baseline": dict(Counter(base))}
    settings: dict[str, tuple[float, float]] = {
        "floor_0.3_only": (0.3, DOMINANCE),
        "floor_0.1_only": (0.1, DOMINANCE),
        "dominance_2.0_only": (PRODUCTION_FLOOR, 2.0),
        "dominance_1.5_only": (PRODUCTION_FLOOR, 1.5),
        "largest_face_wins": (PRODUCTION_FLOOR, 1.0),
    }
    for name, (floor, dominance) in settings.items():
        now = [verdict(faces_at(r, floor), dominance) for r in records]
        moves = Counter((a, b) for a, b in zip(base, now, strict=True) if a != b)
        table[name] = {
            "statuses": dict(Counter(now)),
            "moved": {f"{a}->{b}": n for (a, b), n in sorted(moves.items())},
        }
    cut = sum(
        1 for r in records if verdict(r["kept"], DOMINANCE) == "no_face" and r["border_dropped"]
    )
    table["border_rule"] = {
        "no_face_photographs_with_a_border_dropped_face": cut,
        "note": "alignment needs all five landmarks inside the image; a floor cannot rescue these",
    }
    return table


def sheet(records: list[dict[str, Any]], dataset: Path, out: Path, title: str) -> None:
    """Contact sheet: kept faces green (score), below-floor red, border-dropped blue."""
    size, cols = 250, 6
    rows = (len(records) + cols - 1) // cols
    canvas = Image.new("RGB", (cols * size, rows * (size + 14)), "white")
    for i, rec in enumerate(records):
        image = Image.open(dataset / rec["file"]).convert("RGB")
        w, h = image.size
        draw = ImageDraw.Draw(image)
        for key, colour in (("kept", "lime"), ("below_floor", "red"), ("border_dropped", "blue")):
            for f in rec[key]:
                x0, y0, x1, y1 = f["box"]
                draw.rectangle([x0 * w, y0 * h, x1 * w, y1 * h], outline=colour, width=2)
                draw.text((x0 * w + 2, y0 * h + 2), f"{f['score']:.2f}", fill=colour)
        image = image.resize((size, int(size * h / w)))
        x, y = (i % cols) * size, (i // cols) * (size + 14)
        canvas.paste(image, (x, y + 14))
        ImageDraw.Draw(canvas).text((x + 2, y + 1), f"{i}: {rec['file'][:34]}", fill="black")
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out)
    print(f"{title}: {len(records)} -> {out}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--local-state-root", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--people", type=int, default=100)
    parser.add_argument("--unknown", type=int, default=50)
    parser.add_argument("--minimum-photographs", type=int, default=5)
    parser.add_argument("--sheets", help="a folder (under evaluation/datasets) for contact sheets")
    args = parser.parse_args()

    dataset = guard(Path(args.dataset))
    manifest = json.loads((dataset / "manifest.json").read_text(encoding="utf-8"))
    people = partition_people(
        choose_people(manifest, dataset, 10**6, 1),
        known_count=args.people,
        minimum=args.minimum_photographs,
        unknown_count=args.unknown,
    )
    groups: dict[str, list[Path]] = {"enrolment": [], "known_query": [], "stranger": []}
    for person in people:
        if person.get("unknown"):
            groups["stranger"] += person["query"]
        else:
            groups["enrolment"] += person["enrol"]
            groups["known_query"] += person["query"]

    store = RuntimePackageStore(
        StorageRoots(Path(), Path(args.local_state_root)), new_id=uuid.uuid4
    )
    plan = plan_from(store, "insightface-buffalo-l", ["CPUExecutionProvider"])
    variant = plan.detector[0]
    session = load_session(variant.model_path, variant.sha256, variant.provider)
    input_name = session.get_inputs()[0].name

    report: dict[str, Any] = {
        "what": "exclusions before recognition, per rule (diagnostic; changes nothing)",
        "dominance": DOMINANCE,
        "production_floor": PRODUCTION_FLOOR,
        "diagnostic_floor": DIAGNOSTIC_FLOOR,
        "groups": {},
    }
    for name, paths in groups.items():
        records = []
        for path in sorted(paths):
            pixels = np.asarray(Image.open(path).convert("RGB"), dtype=np.uint8)
            rec = look(session, input_name, pixels)
            rec["file"] = path.relative_to(dataset).as_posix()
            rec["describe"] = describe(rec)
            if rec["describe"]["status"] == "no_face":
                # scale check: the same picture with a black margin of half its size on each side,
                # so a close-up face is smaller relative to the detector's canvas
                h, w = pixels.shape[:2]
                margin = ((h // 2, h // 2), (w // 2, w // 2), (0, 0))
                padded = look(session, input_name, np.pad(pixels, margin))
                rec["padded_kept_scores"] = [f["score"] for f in padded["kept"]]
            records.append(rec)
        statuses = Counter(r["describe"]["status"] for r in records)
        report["groups"][name] = {
            "photographs": len(records),
            "statuses": dict(statuses),
            "no_face_flags": dict(
                Counter(
                    f"below_floor={bool(r['describe']['below_floor_faces'])}, "
                    f"border_dropped={bool(r['describe']['border_dropped_faces'])}"
                    for r in records
                    if r["describe"]["status"] == "no_face"
                )
            ),
            "no_subject_second_face_touches_border": sum(
                r["describe"].get("second_touches_border", False) for r in records
            ),
            "no_subject_largest_is_most_central": sum(
                r["describe"].get("largest_is_most_central", False) for r in records
            ),
            "no_subject_buckets": dict(
                Counter(
                    r["describe"]["bucket"]
                    for r in records
                    if r["describe"]["status"] == "no_subject"
                )
            ),
            "no_subject_second_face_weak_lt_0_7": sum(
                r["describe"]["status"] == "no_subject" and r["describe"]["second_score"] < 0.7
                for r in records
            ),
            "no_subject_second_face_tiny_lt_1pct": sum(
                r["describe"]["status"] == "no_subject"
                and r["describe"]["second_area_fraction"] < 0.01
                for r in records
            ),
            "counterfactuals": counterfactuals(records),
            "records": records,
        }
        print(name, len(records), dict(statuses), flush=True)
        if args.sheets:
            out = guard(Path(args.sheets))
            bad = [r for r in records if r["describe"]["status"] != "ok"]
            for n in range(0, len(bad), 24):
                sheet(bad[n : n + 24], dataset, out / f"{name}-excluded-{n // 24}.png", name)
    path = guard(Path(args.report))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(f"report: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
