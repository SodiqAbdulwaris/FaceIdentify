"""Boxes in the upright, normalised frame, and the rule that ties a selected face to a detected one.

A box is `[x1, y1, x2, y2]`, each from 0 to 1 across the upright picture (EXIF orientation applied,
the way the application decodes it). The label-review tool stores the face a reviewer selected in
this form; the evaluation scripts find the detected face that *corresponds* to it by geometry.
Nothing here ever looks at a detector's array index: the order of the detected faces cannot change
which face is meant.

The rule (`match_face`): a detected face corresponds to the selection when their intersection over
union is at least `MATCH_IOU` (0.5), and it is the only one that does. The detector's own
suppression keeps two of its faces from overlapping by more than 0.4, so for a face the detector
sees at all, 0.5 admits the small shifts of another run or another detector version and cannot
confuse two neighbours. No face at or above the threshold, or two of them, means no
correspondence: the caller leaves the photograph out under a named rule and never takes another
face instead.
"""

import math
from collections.abc import Sequence
from typing import Final

MATCH_IOU: Final = 0.5
MINIMUM_SIDE: Final = 0.005  # a box narrower than 0.5% of the picture is not a face selection


class BadBox(ValueError):
    """A box that is not a usable selection."""


def checked(value: object) -> list[float]:
    """`value` as four finite floats with 0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1, or `BadBox`."""
    # an explicit list or tuple of real numbers: not a string ("01"), not booleans, nothing coerced
    if (
        not isinstance(value, list | tuple)
        or len(value) != 4
        or not all(isinstance(v, int | float) and not isinstance(v, bool) for v in value)
    ):
        raise BadBox("a face box is a list of four numbers: x1, y1, x2, y2")
    x1, y1, x2, y2 = (float(v) for v in value)
    if not all(math.isfinite(v) and 0.0 <= v <= 1.0 for v in (x1, y1, x2, y2)):
        raise BadBox("a face box lies inside the picture (0 to 1)")
    if x2 - x1 < MINIMUM_SIDE or y2 - y1 < MINIMUM_SIDE:
        raise BadBox("a face box has width and height")
    return [x1, y1, x2, y2]


def iou(a: Sequence[float], b: Sequence[float]) -> float:
    """Intersection over union of two boxes."""
    inter = max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(
        0.0, min(a[3], b[3]) - max(a[1], b[1])
    )
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def match_face(selected: Sequence[float], faces: Sequence[Sequence[float]]) -> int | None:
    """The position in `faces` of the one face that corresponds to `selected`, else None.

    The position is only an answer to this call: it is never stored, and permuting `faces`
    permutes the answer with it."""
    near = [i for i, face in enumerate(faces) if iou(selected, face) >= MATCH_IOU]
    return near[0] if len(near) == 1 else None
