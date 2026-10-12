# Topic map 02 Tracking, discovery, video, hardware, and the research questions answered

## 1. What this is and why it exists

The second half of the topic map: the groups that are mostly **not built** (tracking, unknown-person
discovery, video, hardware tuning), and then the questions the old research checklist asked, each with the
answer the project reached. It tells you what you can and cannot try today and where the decision is
recorded.

## 2. Where it lives

| Question | Home |
|---|---|
| The locked stack and the alternatives rejected | `docs/research/tech-stack.md` |
| Which model, by which criteria | `docs/research/reference-model-selection.md` |
| What video and cameras will need | `docs/specs/product-definition-and-requirements-v1.md` (tracking, clustering sections), `docs/specs/processing-architecture-v1.md` |
| Milestones M6 to M8 | `docs/plans/Roadmap-Plan.md`, `docs/plans/PROJECT_STATUS.md` |

## 3. How it works: the map

### Tracking (video) [designed]

Multi-object tracking, tracking-by-detection, re-identification, tracklets, track association, track stitching,
and the trackers **ByteTrack, DeepSORT, StrongSORT, BoT-SORT**: all [designed] for movies and cameras (M6, M7).
The distinction the checklist wanted: a *generic* tracker follows boxes by motion; a *face-aware* one also uses
the face embedding, so a person who leaves and returns is reconnected. Nothing of this is built.

### Unknown-person discovery [researched]

**Clustering** (DBSCAN, HDBSCAN, agglomerative, online or incremental clustering) groups faces that probably
belong to the same unknown person. [researched]. The built system takes a simpler route: the first face of an
empty library starts an identity; after that, a face that cannot be matched **abstains** and waits for you
("This is someone new", or confirm an existing identity), and you merge duplicates by hand (merge is atomic
and recorded in history).

### Video and hardware

- **FFmpeg/ffprobe and PyAV are the chosen video foundation** for M6; **OpenCV is not a dependency** (owner
  decision 2026-10-02: Pillow and NumPy handle still images). Nothing video-related is built.
- **ONNX Runtime is the chosen runtime; CUDA and cuDNN are verified** on the owner's GPU; DirectML is the
  documented Windows-GPU option; **TensorRT and OpenVINO are [researched]**. The worker uses spawned processes and
  shared memory; batching, pinned memory and zero-copy GPU transfers are future optimisations.
- CPU SIMD, multithreading, multiprocessing, asynchronous pipelines, heterogeneous CPU/GPU pipelines: general
  techniques named in the specs; see [the vocabulary](../recognition-ideas/06-nearest-neighbour-and-video-vocabulary.md).

### The research checklist, with its answers

| Question | Answer |
|---|---|
| Face detection: RetinaFace, SCRFD, YOLO-face, MTCNN? | **SCRFD** (from `buffalo_l`); the model is replaceable behind a contract |
| Face representation: ArcFace, FaceNet, AdaFace, MagFace, InsightFace? | **ArcFace** ResNet-50 from the InsightFace `buffalo_l` pack, chosen by documented criteria (`reference-model-selection.md`) |
| Tracking: ByteTrack, DeepSORT, StrongSORT, BoT-SORT? | open; M6 and M7 |
| Vector search: FAISS, HNSW, pgvector? Is an index even needed for thousands of identities? | **USearch (HNSW)**, kept rebuildable; FAISS and Voyager are documented alternatives. For thousands of vectors an exact scan would also work; the index is built so the design scales and the rebuildable-index discipline is exercised early |
| Video: FFmpeg, OpenCV, PyAV? | FFmpeg + PyAV; OpenCV not baseline |
| Local GPU inference: PyTorch, ONNX Runtime, TensorRT, CUDA? | **ONNX Runtime** with CUDA on the RTX 4070 and the CPU as the planned fallback; PyTorch is not a dependency of this repository (the stack decision allows it only for experimentation and export outside the shipped app) |
| Storage: PostgreSQL or SQLite? | **SQLite in WAL mode**; PostgreSQL only if measured write contention demands it |
| Desktop: web UI + local server, Electron, Tauri, native? | **Tauri** shell + React front end + a local FastAPI sidecar |
| Clustering for unknown identities? | not built |
| Face quality assessment? | the detector's score only, so far |
| Open-set recognition? | built as the core policy, measured conservatively ([thresholds](../recognition-ideas/05-thresholds-and-errors.md)) |
| Continual / incremental learning? | no network retraining; adding and correcting stored vectors and identities is the "learning" |
| Local natural-language querying? | deliberately later; deterministic structured search comes first, and name and history search plus face search are built |

The concepts the checklist said deserve the most study, in the order they matter for *reading this code*:
open-set recognition, embeddings and metric learning, threshold calibration, identity correction (merge and
split), clustering, re-identification, tracking, continual learning.

## 4. Try it

**Works with no models. Verified 2026-10-12.**

1. Check the answers against the stack file: `grep -n "SQLite\|USearch\|Tauri" docs/research/tech-stack.md | head`
   shows the locked decisions; `grep -n "OpenCV" docs/research/tech-stack.md` shows the 2026-10-02 decision note.
2. Confirm PyTorch is not a dependency: `grep -in torch pyproject.toml` prints nothing (and `uv tree` lists
   none; see [uv](../tools/02-uv-and-dependencies.md)).
3. Confirm no video code exists: `ls backend/infrastructure/media` shows `image.py` only (still images).
4. See "abstain, then resolve by hand" as an API: with the backend running, `GET /api/v1/sources/{id}/unresolved-faces`
   lists the faces recognition declined to place, and `POST /api/v1/representations/{id}/resolve` places one
   (`identity_id` to attach it, or `null` for "someone new"). See [the corrections routes](../../03-backend/api/routes/corrections.md).

## 5. Change it

Documentation-only: when a decision changes (say, the owner picks a tracker for M6), update the answers table
in the same pull request as the spec decision, using the project's `> **Decision YYYY-MM-DD:**` note style in
the spec and then correcting this table. Never edit a spec without the owner's approval; if this table and a
spec disagree, the spec wins.

## 6. Break it on purpose

Search for a feature that sounds built but is not: `grep -rn "def track\|class .*Tracker" backend` finds nothing.
If a future lesson or message claims "FaceIdentify tracks people across frames", this is the check that
disagrees.

## 7. Exercises

1. Which video library was chosen, and which popular one was explicitly not made a dependency?
2. How does the built system handle an unknown person, given clustering is not built?
3. Is PyTorch part of the shipped app?
4. Where would a tracker's design have to be recorded before it is built?

**Answers**

1. FFmpeg/ffprobe + PyAV; OpenCV is not a baseline dependency.
2. The face abstains; you confirm an existing identity or mark it "someone new"; duplicates are merged by hand.
3. No; at most allowed for experimentation and export outside the shipped app.
4. In the processing and product specs (`docs/specs/`), with the owner's decision as a dated note; then
   `docs/plans/` for the plan.

## 8. Related files

- Previous: [01 Vision, models and identity](01-vision-models-identity.md) · [Topic map index](README.md)
- [`docs/research/tech-stack.md`](../../../research/tech-stack.md), [`docs/plans/Roadmap-Plan.md`](../../../plans/Roadmap-Plan.md)
- [Unresolved faces and corrections](../../03-backend/api/routes/corrections.md)
