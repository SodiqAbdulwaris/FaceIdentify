# Topic map 01 Vision, models and identity representation

## 1. What this is and why it exists

Reading the specs and research notes you will meet dozens of technical terms. This lesson is the dictionary
for the first three groups (computer vision, model architectures, identity representation): one sentence each,
and an honest status for what the project actually did. It is a map, not a tutorial; follow the links for the
explained versions.

## 2. Where it lives

The topics' homes in the repository (checked 2026-10-12):

| Topic | Home |
|---|---|
| Detection (SCRFD) | `backend/ml/perception/detection.py`, `backend/ml/worker/perception_handlers.py`, `backend/app/runtime/reference_package.py` |
| Alignment, embedding (ArcFace) | `backend/ml/perception/alignment.py`, `backend/app/runtime/registration.py` |
| Open-set decision | `backend/app/recognition/reasoner.py` |
| Multiple templates | `backend/app/recognition/assessment.py` (groups by identity) |
| Locked stack choices | `docs/research/tech-stack.md`; model choice: `docs/research/reference-model-selection.md` |

## 3. How it works: the map

### Computer vision

| Topic | What it is | Status |
|---|---|---|
| Computer vision | Getting meaning out of images and video | the whole product |
| Face detection | Finding faces and their boxes | [built] SCRFD |
| Face alignment | Warping a face to a standard pose using landmarks | [built] similarity transform to 112 by 112 |
| Face recognition | Deciding who a face is | [built] embeddings + the reasoner |
| Face verification | Same person or not (1:1) | the base operation, used inside identification |
| Open-set recognition | Known people recognised, strangers rejected | [built] the core design ([kinds of recognition](../recognition-ideas/04-kinds-of-recognition.md)) |
| Closed-set recognition | Everyone is known | not the goal |
| Face re-identification | Matching a person across cameras and frames | [designed] for video (M6, M7) |
| Metric learning | Training so distance means identity | how ArcFace was trained; only its result is used |
| Contrastive learning | Pull similar pairs together, push others apart | background to metric learning |
| Triplet loss | A loss using (anchor, same, different) triples | background (FaceNet-style); ArcFace uses an angular margin instead |
| Self-supervised visual learning | Learning from unlabelled images | [researched]; no training here |
| Face quality assessment | Scoring blur, pose, occlusion, resolution | [partly built] only the detector's score gates a face; fuller quality is [designed] |
| Occlusion handling | Faces partly hidden (masks, hands, glasses) | [researched]; shows up as low scores and abstentions |

### Model architectures

| Topic | What it is | Status |
|---|---|---|
| CNNs | Convolutional networks ([models and ONNX](../recognition-ideas/02-models-onnx-and-providers.md)) | SCRFD and ArcFace-ResNet50 are CNNs |
| Vision Transformers | Attention-based image models | [researched] |
| Hybrid CNN/Transformer | Mixtures of both | [researched] |
| Siamese networks | Two identical networks comparing a pair | background to verification |
| Triplet networks | Networks trained on triples | background |
| Metric-learning architectures | Networks built to output comparable embeddings | what ArcFace is |

### Identity representation

| Topic | What it is | Status |
|---|---|---|
| Feature descriptors | Hand-made image features (older methods) | superseded by embeddings |
| Embeddings | A face as a 512-number vector | [built] the "Representation" |
| Identity prototypes | One summary vector per person | not used; all vectors are kept |
| Multiple-template recognition | Many vectors per person, best match wins | [built] |
| Template aggregation | Combining vectors (average, etc.) | not used |
| Prototype learning | Learning a representative vector | [researched] |

## 4. Try it

**Works with no models. Verified 2026-10-12.** Check the status column against the code yourself:

1. Is detection built? `grep -rli scrfd backend --include=*.py` lists `reference_package.py`,
   `perception_handlers.py` and `detection.py`. Is ArcFace? `grep -rli arcface backend --include=*.py` lists
   `registration.py`, `reference_package.py`, `perception_handlers.py` and `alignment.py`.
2. Is any tracker built? `grep -rli "bytetrack\|deepsort\|tracklet" backend` prints nothing. Where are they
   described? `grep -n "tracklets" docs/specs/product-definition-and-requirements-v1.md`.
3. Is training code present? `grep -rli "optimizer\|loss\.backward" backend` prints nothing: the project runs
   models, it does not train them.
4. Are the "multiple templates" real? Open `tests/unit/test_recognition_reasoner.py` and read
   `test_an_identity_with_many_representations_is_not_favoured_by_their_number`.
5. Find the project's statement on OpenCV in `docs/research/tech-stack.md` (search for "Decision 2026-10-02").

## 5. Change it

When you meet a topic that is not in the map, add it. That is a documentation change in a branch: add a row to
the right table with a status, prefer a link to a spec or a source over an opinion, and mark it [researched] if
nothing was decided. Check links afterwards ([keeping the guide true](../../07-walkthrough-and-glossary/05-further-reading-and-keeping-true.md)).
Do not mark something [built] unless you ran it.

## 6. Break it on purpose

Claim a topic is built without evidence: pretend "face clustering" is [built]. Then run
`grep -rli "hdbscan\|dbscan" backend` (nothing) to see how the claim fails the check. The status column is
only worth anything if every [built] can be pointed at a file.

## 7. Exercises

1. Which topic from the table is the *method* behind the model that turns a face into 512 numbers?
2. Is one summary vector per person used? What is used instead?
3. Name two topics that are [researched] and one that is [designed].
4. Which groups of topics from this lesson involve training, and does the project train?

**Answers**

1. Metric learning (ArcFace's angular-margin loss).
2. No (identity prototypes / template aggregation are not used); every representation is kept and the best
   match per identity scores (multiple templates).
3. For example Vision Transformers and self-supervised learning are [researched]; re-identification is
   [designed].
4. Metric learning, contrastive learning, triplet loss and self-supervised learning involve training; the
   project does not train, it only runs ready-made models.

## 8. Related files

- Next: [02 Tracking, video, hardware and the research questions](02-tracking-video-hardware-and-answers.md) · [Topic map index](README.md)
- [`docs/research/tech-stack.md`](../../../research/tech-stack.md), [`docs/research/reference-model-selection.md`](../../../research/reference-model-selection.md)
- [Recognition ideas](../recognition-ideas/README.md)
