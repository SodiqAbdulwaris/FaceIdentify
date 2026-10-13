# Recognition 03 The face pipeline

## 1. What this is and why it exists

A photograph becomes a comparable vector in four steps, each its own piece of code with its own tests:

```
photograph --decode--> pixel array --DETECT--> boxes + landmarks --ALIGN--> 112x112 crop --EMBED--> 512 numbers
```

Knowing the four stages tells you where a failure can come from ("no face found" is detection; "same person
scored low" may be alignment or the embedding), and which parts are model-dependent (detect, embed) and
which are plain, testable maths (letterbox, decode the boxes, non-maximum suppression, alignment, normalise).

## 2. Where it lives

| Stage | Code | Contract version |
|---|---|---|
| Decode | `backend/infrastructure/media/image.py` (Pillow) | |
| Detect | model: SCRFD. Maths around it: `backend/ml/perception/detection.py` (`letterbox`, `decode`, `non_maximum_suppression`) | `scrfd-letterbox-v1` |
| Align | `backend/ml/perception/alignment.py` (`similarity_transform`, `align`) | `arcface-112-similarity-v1` |
| Embed | model: ArcFace ResNet-50. `preprocess`, `canonical_vector` in `alignment.py` | same |
| Run the models | `backend/ml/worker/perception_handlers.py` (handlers), `onnx_session.py` | |
| Tests | `tests/unit/test_perception_detection.py`, `tests/unit/test_perception_alignment.py` (67 tests together) | |

The released weights are the **`buffalo_l`** pack from InsightFace (SCRFD-10GF for detection, an ArcFace
ResNet-50 for recognition). Their licence allows **non-commercial research use only**, which the owner
accepted for personal use and the project records as a release blocker
(`docs/research/reference-model-selection.md`, `docs/research/licensing-and-commercialization.md`).

## 3. How it works

1. **Detection.** Find where faces are: for each, a **bounding box**, a confidence **score**, and five
   **landmarks** (left eye, right eye, nose, two mouth corners). **SCRFD** is a fast detector. Its
   postprocessing is plain code you can read: **letterbox** the image to a square of 640 pixels (keep the
   proportions, pad the rest with zeros), run the network on three strides (8, 16, 32), keep scores above a
   threshold (0.5), turn the outputs into boxes, then **non-maximum suppression (NMS)** removes duplicates:
   keep the best box and drop others that overlap it too much, measured by *intersection over union* (0.4).
2. **Alignment.** People tilt their heads. Using the landmarks, compute the **similarity transform**
   (rotation + uniform scale + shift, never a mirror image) that moves the eyes, nose and mouth to the standard
   places in a 112 by 112 crop (`TEMPLATE`), by least squares (Umeyama 1991), and resample bilinearly. The
   embedding network was trained on faces aligned this way, so skipping this ruins accuracy.
3. **Embedding.** The second model turns the aligned crop (RGB, `(pixel - 127.5) / 127.5`, channels first)
   into 512 numbers, called an **embedding**, and the project's word for it is **Representation**. It was
   trained with **metric learning**: a loss function (ArcFace's is an *angular margin* loss) pulls
   embeddings of the same person together and pushes different people apart, so that *distance in this
   space means difference of identity*. The output is then divided by its length (L2 norm).
4. **Comparison.** Two faces are compared by the cosine similarity of their embeddings
   ([lesson 01](01-vectors-and-numpy.md)).

Each contract is **versioned** (`VERSION = "arcface-112-similarity-v1"`). Changing the template, the crop
size, the pixel normalisation or the vector normalisation changes what a vector *means*, so it is a
compatibility change recorded in the representation space: old and new vectors are never compared.

## 4. Try it

**Works with no models** (the maths runs on synthetic arrays; the networks are not involved).
**Verified 2026-10-12.** In `uv run python`:

1. Letterbox a 480 by 640 image:

   ```python
   >>> import numpy as np
   >>> from backend.ml.perception.detection import letterbox, DetectorContract, non_maximum_suppression
   >>> lb = letterbox(np.zeros((480, 640, 3), dtype=np.uint8), DetectorContract())
   >>> lb.tensor.shape, lb.scale
   ((1, 3, 640, 640), 1.0)
   ```

   Any picture becomes a 640 by 640 tensor; `scale` says how much it was shrunk (1.0 here: the long side is already 640).
2. NMS keeps one of two overlapping boxes:

   ```python
   >>> boxes = np.array([[0,0,10,10],[1,1,11,11],[50,50,60,60]], dtype=np.float32)
   >>> scores = np.array([0.9, 0.8, 0.7], dtype=np.float32)
   >>> non_maximum_suppression(boxes, scores, 0.4)
   [0, 2]
   ```

   Box 1 overlaps box 0 too much and has a lower score, so it is dropped.
3. Align a face. Landmarks at the template's own positions, placed in the middle of a bigger random picture,
   come back as a 112 by 112 crop:

   ```python
   >>> from backend.ml.perception.alignment import align, EmbedderContract, TEMPLATE
   >>> face = np.random.default_rng(0).integers(0, 255, (240, 320, 3), dtype=np.uint8)
   >>> landmarks = tuple((float(x) / 112 * 0.5 + 0.25, float(y) / 112 * 0.5 + 0.25) for x, y in TEMPLATE)
   >>> crop = align(face, landmarks, EmbedderContract())
   >>> crop.shape, crop.dtype
   ((112, 112, 3), dtype('uint8'))
   ```

   (`landmarks` are five points normalised to the image, `(x, y)` between 0 and 1, in the order of
   `TEMPLATE`.)
4. Run the contract tests: `uv run pytest tests/unit/test_perception_detection.py tests/unit/test_perception_alignment.py -q`.
   Expected: `67 passed` in about a second. Skim their names: `test_a_rotated_face_is_turned_upright`,
   `test_a_mirror_image_is_aligned_by_a_rotation_never_a_reflection`, `test_the_parts_of_the_crop_beyond_the_image_are_black`.
   They are the specification in sentences.
5. *(Needs the local models; unverified here.)* [Lesson 02](02-models-onnx-and-providers.md) step 3 runs the
   real networks on your pictures, and `scripts/smoke_real_models.py` prints the cosine between every pair of faces found.

## 5. Change it

The safe change is to a **test-only constant**: in a scratch copy, call `DetectorContract(score_threshold=0.9)`
and see that `DetectorContract(score_threshold=1.5)` raises `ValueError: the thresholds are fractions`
(its `__post_init__` validates). The real contract values (`input_size=640`, `nms_iou=0.4`, ...) are part
of `scrfd-letterbox-v1`; changing one in the file changes what the detector sees, and the unit tests that
pin letterbox geometry and NMS (`tests/unit/test_perception_detection.py`) fail. The right route is a new
contract version with a documented reason, not an edit.

## 6. Break it on purpose

Give `align` the wrong number of landmarks: `align(face, landmarks[:3], EmbedderContract())`. Expected (observed
2026-10-12): `ContractError: INVALID_INPUT: alignment needs 5 landmarks, got 3` (the check is in `align`,
tested by `test_alignment_needs_five_landmarks`). A grey image instead of RGB (`face[:, :, 0]`) is refused with
`INVALID_INPUT: an image must be uint8 HWC, 3 channels`. The pipeline fails closed on bad input.

## 7. Exercises

1. Why is a face aligned before it is embedded?
2. What does NMS remove and what decides which box survives?
3. Which stage turns 112 by 112 pixels into 512 numbers, and what is that output called in this project?
4. Why is the alignment contract versioned?

**Answers**

1. The embedding network was trained on faces in a standard pose; a tilted face would produce a different
   vector for the same person.
2. Duplicate overlapping detections of one face; the highest score wins and boxes overlapping it by more than
   the IoU threshold are dropped.
3. Embedding; a Representation.
4. Any change to how crops or vectors are made changes what a vector means; the version in the space prevents
   comparing incompatible vectors.

## 8. Related files

- Previous: [02 Models, ONNX and providers](02-models-onnx-and-providers.md) · Next: [04 Kinds of recognition](04-kinds-of-recognition.md)
- [`backend/ml/perception/detection.py`](../../../../../backend/ml/perception/detection.py), [`alignment.py`](../../../../../backend/ml/perception/alignment.py)
- [Runtime and worker](../../03-backend/runtime-and-worker/README.md)
- ArcFace paper: "ArcFace: Additive Angular Margin Loss for Deep Face Recognition"
