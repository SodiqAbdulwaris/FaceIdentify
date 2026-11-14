"""R5: a small local tool to review identity labels by eye and export a verified manifest.

    PYTHONPATH=. uv run python evaluation/label_review.py serve --dataset evaluation/datasets/commons-pd \
        --reviewer <your name>
    PYTHONPATH=. uv run python evaluation/label_review.py status --dataset evaluation/datasets/commons-pd
    PYTHONPATH=. uv run python evaluation/label_review.py export --dataset evaluation/datasets/commons-pd

The dataset's labels are Commons categories: a human-curated hint, not identity evidence. This tool
turns them into evidence only when a person looks and says so. It never approves anything itself and
never looks at embeddings.

* **Nothing is overwritten.** The original `manifest.json` and the photographs are never touched.
  Every decision is one line appended to `<dataset>/review/decisions.jsonl` (reviewer, UTC time,
  photograph, its SHA-256, the label it was reviewed under, the manifest's SHA-256, the decision, any
  correction, flags, a note, the selected face). The latest line for a photograph is its current
  decision; the older ones stay as the audit trail (each names the one it supersedes). Stopping and
  starting again resumes from the log (a half-written last line from a crash is ignored).
* **A decision belongs to what was looked at.** It counts only while the photograph still has the
  same bytes and the same proposed label, and, when the decision selected a detected face, only
  while a detection run of those bytes still has a face that corresponds to it; if one of these
  changed, it is listed as `stale` (with the reason) and the photograph needs a new review.
* **Decisions:** `VERIFIED` (the label is right), `INCORRECT` (it is wrong; give the right name if you
  know it, which then counts as a human-confirmed label), `UNCERTAIN` and `EXCLUDED` (neither ever
  counts). **Flags:** `AMBIGUOUS`, `LOW_QUALITY`, `MULTI_PERSON`; a flagged photograph is kept out of
  the verified set even if it was marked verified (conservative on purpose), except that
  `MULTI_PERSON` alone no longer matters once a face is selected. **Same picture:** if two
  photographs are the same picture (a copy, a crop, another encoding) say so with `same_picture_as`;
  such a group counts once and never crosses a split. Spotting them is the reviewer's job.
* **Which face (issue 181).** A photograph can show several people, and the label belongs to one.
  `review_detections.py` runs the installed detector over the photographs beforehand and stores
  every face it found, with its provenance, in `review/detections.jsonl` (append-only). The page
  draws those boxes, numbered. The model may *suggest* one for the label: it is drawn dashed and
  marked "Suggestion - not verified", and is never selected for you. To confirm a face you click
  it (or draw a box when the detector missed or mis-boxed it) and then press a decision button:
  that is the explicit confirmation. Choosing another face overrides the suggestion; "None / cannot
  determine" rejects it. The decision stores the selected face as a normalised box on the upright
  picture (with the picture's size and whether it is a detected box or a corrected one), the
  suggestion that was offered and what became of it (`CONFIRMED`, `OVERRIDDEN`, `REJECTED`,
  `NOT_ADDRESSED`, `NONE_OFFERED`), and the detection run it was made from. The box, never a detector index, is
  what the approval binds to, together with the photograph's digest.
* **The verified manifest** (`review/exports/verified-<UTC time>.json`, schema 2) lists only
  photographs that are verified, unflagged, unchanged since they were reviewed, and used once. It has
  the same `people` shape the gate script reads, plus provenance: the source manifest's and the
  decision log's digests, the reviewers, counts and the shortfall against the TST-057B targets. Each
  photograph reviewed with a face carries it (`face`) and the review that chose it (`review`). It is
  never padded: a shortfall is reported. Each export is a new file; none is ever replaced. Schema 1
  records and exports stay readable; a consumer that does not know schema 2 refuses it.

The server listens on 127.0.0.1 only and every request carries a per-run token, so another page in
the browser cannot post decisions. It serves only files the manifest lists, and the page draws
photograph names and labels as text, never as markup.
"""

# ruff: noqa: E501  (the page below is one string of HTML and JavaScript)

import argparse
import csv
import difflib
import hashlib
import http.server
import io
import json
import os
import secrets
import socketserver
import sys
import threading
import urllib.parse
import uuid
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from evaluation.face_boxes import BadBox, checked, iou, match_face

DATASETS_ROOT: Final = (Path(__file__).resolve().parent / "datasets").resolve()
DECISIONS: Final = ("VERIFIED", "INCORRECT", "UNCERTAIN", "EXCLUDED")
FLAGS: Final = ("AMBIGUOUS", "LOW_QUALITY", "MULTI_PERSON")
SCHEMA: Final = 2  # a decision record's schema (1: before the selected face existed)
READABLE_SCHEMAS: Final = (1, 2)
EXPORT_SCHEMA: Final = 2  # the verified manifest (1: no face geometry)
DETECTION_SCHEMA: Final = 1
FRAME: Final = (
    "upright picture, EXIF orientation applied as the application decodes it; "
    "box = [x1, y1, x2, y2], fractions of the width and the height"
)
SAME_BOX: Final = 0.95  # a selected box this close to a detected one is that detected box
NONE_CHOICE: Final = "NONE_OR_CANNOT_DETERMINE"
# TST-057B dataset targets (owner, 2026-10-12): initial targets, never a reason to force labels.
TARGETS: Final = {
    "verified_identities": 40,
    "images_per_identity": 5,
    "queries_per_identity": 2,
    "verified_queries": 80,
}


def guard(path: Path) -> Path:
    """Biometric data stays under the Git-ignored datasets folder."""
    resolved = path.resolve()
    if DATASETS_ROOT not in resolved.parents:
        raise SystemExit(f"{path} must be inside {DATASETS_ROOT} (it holds biometric data)")
    return resolved


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def upright_size(data: bytes) -> tuple[int, int]:
    """The width and height of a picture as it is shown upright (EXIF orientation applied)."""
    from PIL import Image, ImageOps  # (only a reviewer who draws a box on an undetected picture)

    try:
        with Image.open(io.BytesIO(data)) as image:
            width, height = ImageOps.exif_transpose(image).size
    except Exception:  # noqa: BLE001 - any decoder failure means the same thing here
        raise ReviewError(
            "that photograph cannot be decoded, so no face can be drawn on it"
        ) from None
    return int(width), int(height)


class ReviewError(ValueError):
    """A decision that is not allowed."""


class Review:
    """The photographs of a dataset, the decisions made about them and what they add up to."""

    def __init__(
        self,
        dataset: Path,
        reviewer: str = "",
        *,
        new_id: Callable[[], str] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.dataset = guard(dataset)
        self.reviewer = reviewer.strip()
        self._new_id = new_id or (lambda: uuid.uuid4().hex)
        self._clock = clock or (lambda: datetime.now(UTC))
        manifest_path = self.dataset / "manifest.json"
        manifest_bytes = manifest_path.read_bytes()
        self.manifest_sha256 = sha256_of(manifest_bytes)
        manifest = json.loads(manifest_bytes.decode("utf-8"))
        self.entries: dict[str, dict[str, Any]] = {}
        for identity, items in manifest.items():
            for item in items:
                path = (self.dataset / item["file"]).resolve()
                if self.dataset not in path.parents:
                    raise SystemExit(f"{item['file']} is outside the dataset folder")
                if path.is_file():
                    self.entries[item["file"]] = {
                        "file": item["file"],
                        "identity": identity,
                        "title": item.get("title", ""),
                    }
        self.shown: frozenset[str] | None = None  # people the page lists (None: everyone)
        self.review_dir = self.dataset / "review"
        self.log_path = self.review_dir / "decisions.jsonl"
        self.detections_path = self.review_dir / "detections.jsonl"
        self._lock = threading.Lock()
        self._hashes: dict[str, tuple[tuple[int, int], str]] = {}
        self._confine(self.review_dir)

    def focus(self, names: list[str]) -> None:
        """List only these people in the page. A name must be one the manifest has (case aside):
        a typo stops the tool rather than showing an empty page. Decisions, status and export are
        about the whole dataset and are not affected."""
        labels = {e["identity"] for e in self.entries.values()}
        known: dict[str, set[str]] = {}
        for identity in labels:  # (labels that differ only in case are all chosen together)
            known.setdefault(identity.lower(), set()).add(identity)
        chosen: set[str] = set()
        unknown: list[str] = []
        for name in names:
            found = known.get(name.strip().lower())
            if found is None:
                unknown.append(name)
            else:
                chosen |= found
        if unknown:
            hints = {
                n: difflib.get_close_matches(n, sorted(labels), n=2, cutoff=0.5) for n in unknown
            }
            raise SystemExit(f"not in the manifest: {unknown} (close: {hints})")
        if not chosen:
            raise SystemExit("--people names nobody")
        self.shown = frozenset(chosen)

    # --- the files ---------------------------------------------------------------------

    def _confine(self, path: Path) -> Path:
        """`path` as it really is on disk (links and junctions followed) must be inside the
        dataset, so a link cannot carry a write or a read out of the Git-ignored folder."""
        real = Path(os.path.realpath(path))
        if self.dataset != real and self.dataset not in real.parents:
            raise SystemExit(f"{path} leads outside the dataset folder")
        return real

    def read_photograph(self, file: str) -> tuple[bytes, str]:
        """The bytes of a listed photograph as they are now, and their SHA-256."""
        path = self._confine(self.dataset / file)
        data = path.read_bytes()
        return data, sha256_of(data)

    def digest(self, file: str) -> str:
        """The SHA-256 of a listed photograph as it is now (re-read only when its size or
        modification time changed, so the whole set is not read on every request)."""
        path = self._confine(self.dataset / file)
        stat = path.stat()
        stamp = (stat.st_size, stat.st_mtime_ns)
        cached = self._hashes.get(file)
        if cached is None or cached[0] != stamp:
            cached = (stamp, sha256_of(path.read_bytes()))
            self._hashes[file] = cached
        return cached[1]

    # --- the logs ----------------------------------------------------------------------

    def _read_jsonl(self, path: Path) -> tuple[bytes, list[dict[str, Any]]]:
        """A log's bytes and the complete records in them, from one read under the lock. A
        half-written last line (a crash while appending) is ignored; the rest stays usable. A
        record of a schema this version does not know is refused, never guessed at."""
        with self._lock:
            self._confine(path)
            data = path.read_bytes() if path.is_file() else b""
        records: list[dict[str, Any]] = []
        lines = data.decode("utf-8", errors="replace").split("\n")
        for position, line in enumerate(lines):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                if position != len(lines) - 1 and any(
                    rest.strip() for rest in lines[position + 1 :]
                ):
                    raise SystemExit(f"{path} is damaged before its end") from None
                continue
            known = READABLE_SCHEMAS if path == self.log_path else (DETECTION_SCHEMA,)
            if record.get("schema_version") not in known:
                raise SystemExit(
                    f"{path} holds a record of schema {record.get('schema_version')}: "
                    "it was written by a newer version of this tool"
                )
            records.append(record)
        return data, records

    def _read_log(self) -> tuple[bytes, list[dict[str, Any]]]:
        return self._read_jsonl(self.log_path)

    def history(self) -> list[dict[str, Any]]:
        return self._read_log()[1]

    def _append(self, path: Path, torn_name: str, record: dict[str, Any]) -> None:
        with self._lock:
            self._confine(self.review_dir)
            self.review_dir.mkdir(parents=True, exist_ok=True)
            self._confine(path)
            line = json.dumps(record, sort_keys=True) + "\n"
            self._set_aside_torn_tail(path, torn_name)
            with path.open("ab") as log:
                log.write(line.encode("utf-8"))
                log.flush()
                os.fsync(log.fileno())

    def _set_aside_torn_tail(self, path: Path, torn_name: str) -> None:
        """A crash can leave a last line without its newline: an incomplete record, never a
        decision. It is moved to a `.torn.jsonl` file (kept, not deleted) so the next record
        starts on a clean line and the log has no damage in its middle."""
        if not path.is_file():
            return
        data = path.read_bytes()
        if not data or data.endswith(b"\n"):
            return
        cut = data.rfind(b"\n") + 1
        try:
            json.loads(data[cut:])
        except ValueError:
            pass
        else:  # a complete record that only lacks its newline: keep it
            with path.open("ab") as log:
                log.write(b"\n")
            return
        with (self.review_dir / torn_name).open("ab") as torn:
            torn.write(data[cut:] + b"\n")
        with path.open("r+b") as log:
            log.truncate(cut)

    def _latest(self, records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        latest: dict[str, dict[str, Any]] = {}
        for record in records:
            if record["file"] in self.entries:
                latest[record["file"]] = record
        return latest

    # --- detections: the faces the installed detector found, and what it suggests -------------

    def detections(self) -> dict[str, dict[str, Any]]:
        """The newest detection run of each photograph's *current* bytes (a run of other bytes
        says nothing about this picture and is ignored)."""
        found: dict[str, dict[str, Any]] = {}
        for record in self._read_jsonl(self.detections_path)[1]:
            file = record.get("file")
            if file in self.entries and record.get("sha256") == self.digest(file):
                found[file] = record
        return found

    def append_detection(self, record: dict[str, Any]) -> dict[str, Any]:
        """Add one detection run: every face the detector found in a photograph, the suggestion
        (or none) for its label, and the provenance of both. Append-only; the newest run of the
        same bytes is the one the page shows."""
        file = record.get("file")
        if not isinstance(file, str) or file not in self.entries:
            raise ReviewError("that photograph is not in the manifest")
        entry = self.entries[file]
        if record.get("sha256") != self.digest(file):
            raise ReviewError("the photograph changed while it was being detected")
        size = record.get("image_size")
        if not (
            isinstance(size, list)
            and len(size) == 2
            and all(isinstance(n, int) and n > 0 for n in size)
        ):
            raise ReviewError("image_size is the upright width and height in pixels")
        try:
            faces = [
                {"box": checked(f["box"]), "score": float(f["score"])} for f in record["faces"]
            ]
            offered = record.get("suggestion")
            suggestion = (
                None
                if offered is None
                else {
                    "box": checked(offered["box"]),
                    "basis": str(offered["basis"]),
                    "score": None if offered.get("score") is None else float(offered["score"]),
                    "rationale": str(offered["rationale"]),
                }
            )
        except (BadBox, KeyError, TypeError, ValueError) as error:
            raise ReviewError(f"a detection is faces with boxes and scores: {error}") from None
        provenance = record.get("provenance")
        if not (
            isinstance(provenance, dict)
            and {"package_key", "package_version", "detector"} <= provenance.keys()
        ):
            raise ReviewError("a detection run records its provenance")
        stored = {
            "schema_version": DETECTION_SCHEMA,
            "id": self._new_id(),
            "at": self._clock().isoformat(),
            "file": file,
            "sha256": record["sha256"],
            "label": entry["identity"],
            "image_size": size,
            "frame": FRAME,
            "faces": faces,
            "suggestion": suggestion,
            "provenance": provenance,
        }
        self._append(self.detections_path, "detections.torn.jsonl", stored)
        return stored

    def face_view(self, file: str, detection: dict[str, Any] | None) -> dict[str, Any] | None:
        """What the page shows of a photograph's detections: its faces left to right and the
        suggestion, if it was made for the label the photograph has now."""
        if detection is None:
            return None
        suggestion = detection["suggestion"]
        if detection["label"] != self.entries[file]["identity"]:
            suggestion = None  # (made for another label: no basis for this one)
        return {
            "id": detection["id"],
            "image_size": detection["image_size"],
            "faces": sorted(detection["faces"], key=lambda f: (f["box"][0], f["box"][1])),
            "suggestion": suggestion,
            "provenance": detection["provenance"],
        }

    # --- validity ------------------------------------------------------------------------

    def _why(
        self, file: str, record: dict[str, Any], detection: dict[str, Any] | None
    ) -> str | None:
        """Why a decision no longer describes what is there (None: it still does).

        The photograph's bytes or label changed; its selected face is not a valid box; or the
        newest detection run of these bytes shows a different picture size, or, for a face that
        was a detected one, no longer has a face that corresponds to it (a detector or model
        change that moved the correspondence). A box the reviewer drew is theirs and is not
        tied to a detector."""
        if record["sha256"] != self.digest(file):
            return "photograph_changed"
        if record["original_identity"] != self.entries[file]["identity"]:
            return "label_changed"
        face = record.get("face")
        confirming = record["decision"] == "VERIFIED" or (
            record["decision"] == "INCORRECT" and record.get("corrected_identity")
        )
        if not face and confirming and detection is not None and record.get("face_choice") is None:
            return "face_not_reviewed"  # confirmed before the faces were known: which face?
        if face:
            try:
                box = checked(face["box"])
            except (BadBox, KeyError, TypeError):
                return "geometry_invalid"
            if detection is not None:
                if list(face.get("image_size") or []) != list(detection["image_size"]):
                    return "geometry_changed"
                same_run = (record.get("detection") or {}).get("record_id") == detection["id"]
                if (
                    face.get("source") == "DETECTED"
                    and not same_run
                    and match_face(box, [f["box"] for f in detection["faces"]]) is None
                ):
                    return "geometry_changed"
        return None

    def _split(
        self, records: list[dict[str, Any]]
    ) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, str]]:
        """The latest decision per photograph: those that still describe what is there, the stale
        ones, and why each stale one is (see `_why`)."""
        detections = self.detections()
        valid: dict[str, dict[str, Any]] = {}
        stale: dict[str, dict[str, Any]] = {}
        reasons: dict[str, str] = {}
        for file, record in self._latest(records).items():
            reason = self._why(file, record, detections.get(file))
            if reason is None:
                valid[file] = record
            else:
                stale[file] = record
                reasons[file] = reason
        return valid, stale, reasons

    def current(self) -> dict[str, dict[str, Any]]:
        return self._split(self._read_log()[1])[0]

    def decide(
        self,
        file: str,
        decision: str,
        *,
        corrected_identity: str | None = None,
        flags: tuple[str, ...] = (),
        note: str = "",
        same_picture_as: str | None = None,
        face: Sequence[float] | None = None,
        none_or_cannot_determine: bool = False,
    ) -> dict[str, Any]:
        """Append one decision. `face` is the box the reviewer selected (a detected face they
        clicked or one they drew); `none_or_cannot_determine` says no face can be named. Neither
        is ever filled in from the model's suggestion: that is the reviewer's act."""
        if not self.reviewer:
            raise ReviewError("a reviewer name is needed: decisions are attributed")
        entry = self.entries.get(file)
        if entry is None:
            raise ReviewError("that photograph is not in the manifest")
        if decision not in DECISIONS:
            raise ReviewError(f"a decision is one of {', '.join(DECISIONS)}")
        bad = [flag for flag in flags if flag not in FLAGS]
        if bad:
            raise ReviewError(f"unknown flags: {', '.join(bad)}")
        correction = (corrected_identity or "").strip()
        if correction and decision != "INCORRECT":
            raise ReviewError("a correction goes with an INCORRECT decision")
        twin = (same_picture_as or "").strip()
        if twin and (twin not in self.entries or twin == file):
            raise ReviewError("same_picture_as must be another photograph of the manifest")
        if face is not None and none_or_cannot_determine:
            raise ReviewError("a face is either selected or said to be undeterminable, not both")
        if none_or_cannot_determine and decision not in ("UNCERTAIN", "EXCLUDED"):
            raise ReviewError("'none / cannot determine' goes with UNCERTAIN or EXCLUDED")
        box: list[float] | None = None
        if face is not None:
            try:
                box = checked(face)
            except BadBox as error:
                raise ReviewError(str(error)) from None
        confirming = decision == "VERIFIED" or (decision == "INCORRECT" and bool(correction))
        data, digest = self.read_photograph(file)  # (the bytes as they are at this moment)
        detection = self.detections().get(file)
        if confirming and box is None and detection is not None:
            raise ReviewError(
                "choose the face this label belongs to (click it, or draw a box), "
                "or say none / cannot determine"
            )
        offered = (self.face_view(file, detection) or {}).get("suggestion")
        if offered is None:
            outcome = "NONE_OFFERED"
        elif box is None:
            # REJECTED only when the reviewer said no face can be determined; a decision made
            # without answering the suggestion at all is not a rejection
            outcome = "REJECTED" if none_or_cannot_determine else "NOT_ADDRESSED"
        else:
            outcome = "CONFIRMED" if iou(box, offered["box"]) >= SAME_BOX else "OVERRIDDEN"
        selected: dict[str, Any] | None = None
        if box is not None:
            width, height = detection["image_size"] if detection else upright_size(data)
            detected = detection is not None and any(
                iou(box, f["box"]) >= SAME_BOX for f in detection["faces"]
            )
            selected = {
                "box": box,
                "image_size": [width, height],
                "source": "DETECTED" if detected else "CORRECTED",
                "frame": FRAME,
            }
        previous = self._latest(self._read_log()[1]).get(file)
        record = {
            "schema_version": SCHEMA,
            "id": self._new_id(),
            "supersedes": previous.get("id") if previous else None,
            "at": self._clock().isoformat(),
            "reviewer": self.reviewer,
            "file": file,
            "sha256": digest,
            "manifest_sha256": self.manifest_sha256,
            "original_identity": entry["identity"],
            "decision": decision,
            "corrected_identity": correction or None,
            "flags": sorted(set(flags)),
            "note": note.strip(),
            "same_picture_as": twin or None,
            "face_choice": NONE_CHOICE
            if none_or_cannot_determine
            else ("SELECTED" if box is not None else None),
            "face": selected,
            "suggestion": {"outcome": outcome, "offered": offered},
            "detection": (
                None
                if detection is None
                else {"record_id": detection["id"], "provenance": detection["provenance"]}
            ),
        }
        self._append(self.log_path, "decisions.torn.jsonl", record)
        return record

    # --- what the decisions add up to ----------------------------------------------------

    def _counts(self, valid: dict[str, dict[str, Any]], stale: dict[str, Any]) -> dict[str, Any]:
        counts = dict.fromkeys(DECISIONS, 0)
        for record in valid.values():
            counts[record["decision"]] += 1
        reviewed = sum(counts.values())
        return {
            "photographs": len(self.entries),
            "reviewed": reviewed,
            "unreviewed": len(self.entries) - reviewed - len(stale),
            "stale_needs_review": len(stale),
            **counts,
        }

    def status(self) -> dict[str, Any]:
        valid, stale, _ = self._split(self._read_log()[1])
        return self._counts(valid, stale)

    def _verified(
        self, valid: dict[str, dict[str, Any]], stale: dict[str, Any]
    ) -> tuple[dict[str, list[dict[str, Any]]], dict[str, list[str]]]:
        people: dict[str, list[dict[str, Any]]] = {}
        left_out: dict[str, list[str]] = {
            "not_verified": [],
            "flagged": [],
            "stale_needs_review": sorted(stale),
            "duplicates_dropped": [],
        }
        # photographs declared to be the same picture form one group; the first one counts
        group = {file: file for file in self.entries}

        def root(file: str) -> str:
            while group[file] != file:
                file = group[file]
            return file

        for file, record in valid.items():
            twin = record.get("same_picture_as")
            if twin in group:
                a, b = sorted((root(file), root(twin)))
                group[b] = a
        counted: set[str] = set()
        for file, record in sorted(valid.items()):
            confirmed = (
                record["decision"] == "VERIFIED"
                or (record["decision"] == "INCORRECT" and record["corrected_identity"])
            ) and record.get("face_choice") != NONE_CHOICE
            if not confirmed:
                left_out["not_verified"].append(file)
            elif record["flags"] and (
                record["flags"] != ["MULTI_PERSON"] or not record.get("face")
            ):  # (several people is no doubt once the reviewer selected which face)
                left_out["flagged"].append(file)
            elif root(file) in counted or self.digest(file) in counted:
                left_out["duplicates_dropped"].append(file)
            else:
                counted.add(root(file))
                counted.add(self.digest(file))
                identity = record["corrected_identity"] or self.entries[file]["identity"]
                item: dict[str, Any] = {
                    "file": file,
                    "title": self.entries[file]["title"],
                    "sha256": record["sha256"],
                    "corrected": record["decision"] == "INCORRECT",
                }
                if record.get("face"):
                    item["face"] = record["face"]
                    item["review"] = {
                        "decision_id": record.get("id"),
                        "reviewer": record["reviewer"],
                        "at": record["at"],
                        "suggestion_outcome": (record.get("suggestion") or {}).get("outcome"),
                        "detection": record.get("detection"),
                    }
                people.setdefault(identity, []).append(item)
        left_out["not_verified"] += sorted(set(self.entries) - set(valid) - set(stale))
        return people, left_out

    def verified(self) -> tuple[dict[str, list[dict[str, Any]]], dict[str, list[str]]]:
        """The photographs that may enter the verified set, by identity, and what was left out."""
        valid, stale, _ = self._split(self._read_log()[1])
        return self._verified(valid, stale)

    def export(self) -> dict[str, Any]:
        data, records = self._read_log()  # one snapshot of the log for the whole document
        valid, stale, reasons = self._split(records)
        people, left_out = self._verified(valid, stale)
        counts = {name: len(items) for name, items in people.items()}
        usable = {name: n for name, n in counts.items() if n >= TARGETS["images_per_identity"]}
        queries = {name: max(1, n // 4) for name, n in usable.items()}  # as the gate holds out
        shortfall = {
            "verified_identities": max(0, TARGETS["verified_identities"] - len(usable)),
            "identities_with_two_queries": sum(1 for q in queries.values() if q < 2),
            "verified_queries": max(0, TARGETS["verified_queries"] - sum(queries.values())),
        }
        stale_reasons: dict[str, list[str]] = {}
        for file, reason in sorted(reasons.items()):
            stale_reasons.setdefault(reason, []).append(file)
        provenance = {
            json.dumps(item["review"]["detection"]["provenance"], sort_keys=True)
            for items in people.values()
            for item in items
            if (item.get("review") or {}).get("detection")
        }
        return {
            "schema_version": EXPORT_SCHEMA,
            "kind": "verified-manifest",
            "exported_at": self._clock().isoformat(),
            "source_manifest_sha256": self.manifest_sha256,
            "decisions_sha256": sha256_of(data),
            "reviewers": sorted({record["reviewer"] for record in records}),
            "geometry_frame": FRAME,
            "detection_provenance": sorted(json.loads(p) for p in provenance),
            "counts": {
                "status": self._counts(valid, stale),
                "verified_photographs": sum(counts.values()),
                "verified_with_a_selected_face": sum(
                    1 for items in people.values() for item in items if "face" in item
                ),
                "identities": len(people),
                "identities_with_enough_images": len(usable),
                "held_out_queries": sum(queries.values()),
                "left_out": {key: len(value) for key, value in left_out.items()},
            },
            "targets": TARGETS,
            "shortfall": shortfall,
            "left_out": left_out,
            "stale_reasons": stale_reasons,
            "people": people,
        }

    def write_export(self) -> Path:
        """A new file every time: an earlier export is never replaced."""
        document = self.export()
        folder = self.review_dir / "exports"
        self._confine(folder)
        folder.mkdir(parents=True, exist_ok=True)
        self._confine(folder)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        for attempt in range(1000):
            suffix = "" if attempt == 0 else f"-{attempt}"
            path = folder / f"verified-{stamp}{suffix}.json"
            try:
                with path.open("x", encoding="utf-8") as out:
                    out.write(json.dumps(document, indent=1))
            except FileExistsError:
                continue
            return path
        raise SystemExit("could not find a free name for the export")


# --- the page ----------------------------------------------------------------------------

PAGE = """<!doctype html><meta charset="utf-8"><title>Label review</title>
<style>
body{font:15px system-ui;margin:1rem;background:#fff;color:#111}
header{display:flex;gap:1rem;align-items:center;flex-wrap:wrap;margin-bottom:1rem}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:1rem}
.card{border:1px solid #bbb;border-radius:8px;padding:.5rem}
.pic{position:relative;height:260px;background:#eee;touch-action:none}.pic.big{height:680px}
.pic img{width:100%;height:100%;object-fit:contain;display:block;user-select:none;-webkit-user-drag:none}
.layer{position:absolute;inset:0}.layer.drawing{cursor:crosshair}.layer.drawing .face{pointer-events:none}
.face{position:absolute;box-sizing:border-box;border:2px solid #1769e0;cursor:pointer;background:rgba(23,105,224,.06)}
.face.sug{border:3px dashed #d97700}.face.picked{border:4px solid #0a8f3c;background:rgba(10,143,60,.12)}
.face:focus-visible{outline:3px solid #000}
.tag{position:absolute;left:0;top:0;background:#111;color:#fff;font-size:12px;padding:0 4px;white-space:nowrap}
.face.sug .tag{background:#b35f00;top:100%}.face.picked .tag{background:#0a6b2d}
.badge{font-weight:600}.VERIFIED{color:#0a6b2d}.INCORRECT{color:#a00}.UNCERTAIN{color:#8a6000}
.EXCLUDED{color:#555}button{margin:.15rem;padding:.35rem .6rem}.note{color:#444}
</style>
<header><h1>Label review</h1><label>Person <select id=who></select></label>
<span id=status role=status></span></header>
<p>The label comes from a Commons category and is not evidence. Say VERIFIED only if you can
tell it is the same person as in the other photographs of this person. Every face the detector found has
a numbered box. An orange dashed box is the model's suggestion for this label: it is not verified and
nothing is selected for you. Click the face the label belongs to (or draw a box if the detector missed or
mis-boxed it), then decide. If you cannot tell which face it is, press None / cannot determine.</p>
<div id=grid class=grid></div>
<script>
const T=new URLSearchParams(location.search).get('t');let state=null;
const FLAGS=['AMBIGUOUS','LOW_QUALITY','MULTI_PERSON'],DEC=['VERIFIED','INCORRECT','UNCERTAIN','EXCLUDED'];
const api=(p,o)=>fetch(p+(p.includes('?')?'&':'?')+'t='+encodeURIComponent(T),o).then(r=>r.json());
const el=(tag,props,...kids)=>{const e=document.createElement(tag);Object.assign(e,props||{});
 for(const k of kids)e.append(k);return e};
async function load(focus){state=await api('/api/state');const sel=document.getElementById('who');
 const keep=sel.value;sel.replaceChildren();for(const n of Object.keys(state.people)){
 sel.append(el('option',{value:n,textContent:n}))}
 if(keep)sel.value=keep;document.getElementById('status').textContent=
 Object.entries(state.status).map(([k,v])=>k+': '+v).join(' | ');draw(focus)}
function draw(focus){const g=document.getElementById('grid');g.replaceChildren();
 const who=document.getElementById('who').value;
 for(const e of state.people[who]||[]){
  const c=state.decisions[e.file]||{};const det=e.detection;
  const card=el('div',{className:'card',role:'group'});card.setAttribute('aria-label',e.file);
  const img=el('img');img.alt=e.file;img.src='/image?f='+encodeURIComponent(e.file)+'&t='+encodeURIComponent(T);
  const layer=el('div',{className:'layer'});const pic=el('div',{className:'pic'},img,layer);
  const faces=det?det.faces:[];const sug=det&&det.suggestion?det.suggestion.box:null;
  let sel=null;const saved=c.face?c.face.box:null;let drawing=false;
  const same=(a,b)=>a&&b&&a.every((v,i)=>Math.abs(v-b[i])<1e-6);
  const rect=()=>{const s=Math.min(img.clientWidth/img.naturalWidth,img.clientHeight/img.naturalHeight);
   const w=img.naturalWidth*s,h=img.naturalHeight*s;return{l:(img.clientWidth-w)/2,t:(img.clientHeight-h)/2,w,h}};
  const place=(d,b)=>{const r=rect();d.style.left=(r.l+b[0]*r.w)+'px';d.style.top=(r.t+b[1]*r.h)+'px';
   d.style.width=((b[2]-b[0])*r.w)+'px';d.style.height=((b[3]-b[1])*r.h)+'px'};
  const info=el('div',{className:'note'});
  const paint=()=>{if(!img.naturalWidth)return;layer.replaceChildren();
   faces.forEach((f,i)=>{const isSug=same(f.box,sug);const picked=sel&&sel.n===i;
    const d=el('div',{className:'face'+(isSug?' sug':'')+(picked?' picked':''),tabIndex:0,role:'button'});
    d.setAttribute('aria-label','Face '+(i+1)+' of '+faces.length+(isSug?', suggested by the model, not verified':'')+(picked?', selected':'')+'. Select this face');
    d.append(el('span',{className:'tag',textContent:(i+1)+(isSug?' Suggestion - not verified':'')}));place(d,f.box);
    const pick=()=>{sel={box:f.box,n:i};paint()};d.onclick=pick;
    d.onkeydown=ev=>{if(ev.key==='Enter'||ev.key===' '){ev.preventDefault();pick()}};layer.append(d)});
   if(saved&&!sel){const d=el('div',{className:'face'});d.style.borderStyle='dotted';d.style.pointerEvents='none';
    d.append(el('span',{className:'tag',textContent:'saved earlier; select again to save'}));place(d,saved);layer.append(d)}
   if(sel&&sel.n===null){const d=el('div',{className:'face picked'});
    d.append(el('span',{className:'tag',textContent:'selected box'}));place(d,sel.box);layer.append(d)}
   info.textContent=(faces.length?faces.length+' face(s) detected. ':det?'The detector found no face. ':'No detection run for this photograph. ')+
    (sel?(sel.n===null?'A drawn box is selected.':'Face '+(sel.n+1)+' is selected.'):'No face selected.')+
    (det&&det.suggestion?' Model suggestion (not verified): '+det.suggestion.rationale:'')};
  img.onload=paint;if(img.complete)paint();
  const startDraw=ev=>{if(!drawing)return;const b=pic.getBoundingClientRect(),r=rect();
   const at=ev=>[Math.min(1,Math.max(0,(ev.clientX-b.left-r.l)/r.w)),Math.min(1,Math.max(0,(ev.clientY-b.top-r.t)/r.h))];
   const a=at(ev);layer.setPointerCapture(ev.pointerId);
   const move=m=>{const p=at(m);sel={box:[Math.min(a[0],p[0]),Math.min(a[1],p[1]),Math.max(a[0],p[0]),Math.max(a[1],p[1])],n:null};paint()};
   const up=()=>{layer.removeEventListener('pointermove',move);layer.removeEventListener('pointerup',up);
    drawing=false;layer.classList.remove('drawing');draw_btn.setAttribute('aria-pressed','false')};
   layer.addEventListener('pointermove',move);layer.addEventListener('pointerup',up)};
  layer.addEventListener('pointerdown',startDraw);
  const draw_btn=el('button',{type:'button',textContent:'Draw a box'});draw_btn.setAttribute('aria-pressed','false');
  draw_btn.onclick=()=>{drawing=!drawing;layer.classList.toggle('drawing',drawing);draw_btn.setAttribute('aria-pressed',String(drawing))};
  const clear=el('button',{type:'button',textContent:'Clear selection'});clear.onclick=()=>{sel=null;paint()};
  const big=el('button',{type:'button',textContent:'Enlarge'});big.onclick=()=>{pic.classList.toggle('big');requestAnimationFrame(paint)};
  const badge=el('div',{className:'badge'});
  if(c.decision){badge.append(el('span',{className:c.decision,textContent:c.decision}));
   if(c.corrected_identity)badge.append(' as '+c.corrected_identity);
   if(c.face_choice==='NONE_OR_CANNOT_DETERMINE')badge.append(' (no face could be determined)');
   if(c.suggestion)badge.append(' [suggestion: '+c.suggestion.outcome+']');
   if(c.flags&&c.flags.length)badge.append(' ['+c.flags.join(', ')+']')}else badge.append('not reviewed');
  const note=el('input',{placeholder:'note',value:c.note||''});note.setAttribute('aria-label','Note for '+e.file);
  const twin=el('input',{placeholder:'same picture as (file)',value:c.same_picture_as||''});
  twin.setAttribute('aria-label','Same picture as, for '+e.file);
  const flags=FLAGS.map(f=>{const box=el('input',{type:'checkbox',checked:!!(c.flags&&c.flags.includes(f))});
   box.dataset.f=f;return el('label',{},box,f)});
  const decide=async(x,none)=>{let corrected=null;
    if(x==='INCORRECT')corrected=prompt('Who is it, if you know? (leave empty if not)','');
    const r=await api('/api/decision',{method:'POST',headers:{'Content-Type':'application/json'},
     body:JSON.stringify({file:e.file,decision:x,corrected_identity:corrected,
      flags:flags.map(l=>l.firstChild).filter(b=>b.checked).map(b=>b.dataset.f),
      note:note.value,same_picture_as:twin.value||null,face:none?null:(sel?sel.box:null),
      none_or_cannot_determine:!!none})});
    if(r.error)alert(r.error);await load({file:e.file,d:none?'NONE':x})};
  const buttons=DEC.map(x=>{const b=el('button',{type:'button',textContent:x});b.dataset.d=x;
   b.setAttribute('aria-label',x+' '+e.file);b.onclick=()=>decide(x,false);return b});
  const none=el('button',{type:'button',textContent:'None / cannot determine'});none.dataset.d='NONE';
  none.setAttribute('aria-label','None / cannot determine, '+e.file);none.onclick=()=>decide('UNCERTAIN',true);
  buttons.push(none);
  card.append(pic,el('div',{},el('b',{textContent:e.file}),el('br'),el('small',{textContent:e.title})),
   badge,info,el('div',{},draw_btn,clear,big),el('div',{},...flags),note,twin,el('div',{},...buttons));g.append(card)}
 if(focus){for(const b of g.querySelectorAll('button')){
  if(b.dataset.d===focus.d&&(b.getAttribute('aria-label')||'').endsWith(focus.file)){b.focus()}}}}
document.getElementById('who').onchange=()=>draw();load();
</script>"""


def make_handler(review: Review, token: str) -> type[http.server.BaseHTTPRequestHandler]:
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            return  # quiet

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, value: Any) -> None:
            self._send(status, json.dumps(value).encode(), "application/json")

        def _allowed(self, query: dict[str, list[str]]) -> bool:
            return secrets.compare_digest(query.get("t", [""])[0], token)

        def do_GET(self) -> None:  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            query = urllib.parse.parse_qs(parsed.query)
            if not self._allowed(query):
                self._json(403, {"error": "not allowed"})
            elif parsed.path == "/":
                self._send(200, PAGE.encode(), "text/html; charset=utf-8")
            elif parsed.path == "/api/state":
                people: dict[str, list[dict[str, Any]]] = {}
                detections = review.detections()
                for entry in review.entries.values():
                    if review.shown is not None and entry["identity"] not in review.shown:
                        continue
                    people.setdefault(entry["identity"], []).append(
                        {
                            "file": entry["file"],
                            "title": entry["title"],
                            "detection": review.face_view(
                                entry["file"], detections.get(entry["file"])
                            ),
                        }
                    )
                self._json(
                    200,
                    {
                        "people": people,
                        "decisions": review.current(),
                        "status": review.status(),
                    },
                )
            elif parsed.path == "/image":
                listed = review.entries.get(query.get("f", [""])[0])
                if listed is None:  # only photographs the manifest lists are ever served
                    self._json(404, {"error": "unknown photograph"})
                else:
                    try:
                        data, _ = review.read_photograph(listed["file"])
                    except SystemExit:  # a link that leads outside the dataset
                        self._json(404, {"error": "unknown photograph"})
                    else:
                        self._send(200, data, "image/jpeg")
            else:
                self._json(404, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            allowed = self._allowed(urllib.parse.parse_qs(parsed.query))
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(min(length, 65536))  # (read before any answer: an unread body
            # can make the connection abort under the client, which then never sees the 403)
            if not allowed or parsed.path != "/api/decision":
                self._json(403, {"error": "not allowed"})
                return
            try:
                body = json.loads(raw)
                record = review.decide(
                    body["file"],
                    body["decision"],
                    corrected_identity=body.get("corrected_identity"),
                    flags=tuple(body.get("flags", [])),
                    note=str(body.get("note", "")),
                    same_picture_as=body.get("same_picture_as"),
                    face=body.get("face"),
                    none_or_cannot_determine=bool(body.get("none_or_cannot_determine", False)),
                )
            except (ReviewError, KeyError, ValueError, TypeError) as error:
                self._json(400, {"error": str(error) or "that is not a valid decision"})
                return
            except SystemExit:  # a link that leads outside the dataset
                self._json(400, {"error": "that photograph cannot be read"})
                return
            self._json(200, record)

    return Handler


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True


def serve(review: Review, port: int = 0) -> tuple[Server, str]:
    token = secrets.token_urlsafe(24)
    server = Server(("127.0.0.1", port), make_handler(review, token))
    return server, token


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("serve", "status", "export"))
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--reviewer", default="")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument(
        "--people",
        help="serve only these people: comma separated, names as the manifest has them; quote a "
        'name that contains a comma ("Doe, Jane",Ada)',
    )
    args = parser.parse_args(argv)
    review = Review(Path(args.dataset), args.reviewer)
    if args.people is not None:  # (an empty value is refused by `focus`, never "everyone")
        review.focus([n for row in csv.reader([args.people]) for n in row if n.strip()])
    if args.command == "status":
        print(json.dumps(review.status(), indent=1))
    elif args.command == "export":
        path = review.write_export()
        document = json.loads(path.read_text(encoding="utf-8"))
        summary = {
            "written": str(path),
            "counts": document["counts"],
            "shortfall": document["shortfall"],
        }
        print(json.dumps(summary, indent=1))
    else:
        if not review.reviewer:
            raise SystemExit("--reviewer is required to serve: decisions are attributed")
        server, token = serve(review, args.port)
        url = f"http://127.0.0.1:{server.server_address[1]}/?t={token}"
        print(f"Review at {url}\nCtrl+C to stop; decisions are saved as you make them.", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
