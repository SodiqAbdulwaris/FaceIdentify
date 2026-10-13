# Recognition 06 Nearest-neighbour search and the video vocabulary

## 1. What this is and why it exists

With ten thousand stored face vectors, comparing a new face against all of them is instant. With ten
million it is slow. An **approximate nearest-neighbour (ANN)** index finds the *almost certainly* closest
vectors without checking all of them. This project uses one (**USearch**, an HNSW index) and treats it
with suspicion: it is derived data, it can be wrong or stale, and it never decides who someone is. The second
half of this lesson is a glossary for the parts of the specs that are **not built yet** (movies, cameras,
tracking, hardware tuning), so the words do not stop you when you meet them.

## 2. Where it lives

| Idea | Where |
|---|---|
| One index per representation space | `backend/infrastructure/indexing/representation_index.py` (manifest, generations, quarantine, rebuild) |
| The run-local index (this run's own faces) | `backend/infrastructure/indexing/run_local_index.py` |
| Applying queued index changes | `backend/app/memory/index_coordinator.py` |
| Searching and revalidating | `backend/app/recognition/retrieval.py` |
| The distance convention | `distance = 1 - cosine similarity` (the cosine metric of USearch) |

## 3. How it works

**HNSW** (hierarchical navigable small world) is the standard method: a layered graph where you hop
towards the target through ever-closer neighbours, like zooming a map from country to street. It is
approximate: it may miss the true nearest neighbour, rarely and slightly. **USearch** is the library
(alternatives considered: FAISS, Voyager, pgvector).

Because the answer is approximate and the file may be stale, the project **never trusts the index alone**:

1. The index returns only candidate **keys** (`ann_key`, an integer unique inside its space) and distances.
2. Retrieval re-reads each candidate from SQLite and **revalidates** it: is the representation still
   `ACTIVE`? is its identity still alive? is its space the right one? Dropped candidates are counted, and a
   shortlist that lost any is flagged incomplete (the reasoner then abstains, `RETRIEVAL_INCOMPLETE`).
3. The index only knows keys and vectors; SQLite maps keys back to rows and decides truth.

The index is **derived** data ([authoritative versus derived](../../00-start-here/03-authoritative-and-derived.md)):
if it is lost, damaged or stale, it is rebuilt from SQLite by streaming the eligible vectors.

### The video and hardware vocabulary [designed / researched]

None of this is built (movies are M6, cameras M7), but the specs use these words:

- **FFmpeg** (video swiss-army knife), **PyAV** (Python bindings), **OpenCV** (vision library). The project's
  decision: FFmpeg/ffprobe + PyAV for video in M6; **OpenCV is not a dependency** (Pillow and NumPy handle still
  images; owner decision 2026-10-02).
- **Decoding** turns compressed video into frames; **NVDEC** is the NVIDIA chip block that decodes in hardware.
  **Frame sampling** (look at every Nth frame), **keyframes** (full frames a video can seek to), **scene-change
  detection** (skip near-identical frames).
- **Multi-object tracking** (ByteTrack, DeepSORT, StrongSORT, BoT-SORT): link detections across frames into
  **tracklets**; **track association** and **stitching** join broken ones.
- **Hardware tuning**: **SIMD** (one CPU instruction on many numbers), multithreading, multiprocessing,
  asynchronous pipelines (decode the next frame while the GPU works), **pinned memory** and **zero-copy**
  transfers, **GPU batching** (many faces in one call), heterogeneous CPU/GPU pipelines. Today the worker uses a
  spawned process and shared memory; batching and pinned memory are future optimisations.
- **Face quality assessment** (blur, pose, occlusion, resolution) to pick the best face from a track. Only the
  detector's score gates a face today.
- **Continual learning**: the project does *not* retrain networks to learn new people; it adds stored vectors,
  which is cheaper and reversible.

## 4. Try it

**Works with no models. Verified 2026-10-12.**

1. Build a real USearch index and ask it for the nearest vectors (paste as one block):

   ```python
   import numpy as np
   from usearch.index import Index

   rng = np.random.default_rng(1)
   vecs = rng.normal(size=(1000, 64)).astype(np.float32)
   vecs /= np.linalg.norm(vecs, axis=1, keepdims=True)         # unit vectors
   index = Index(ndim=64, metric="cos")
   index.add(np.arange(1000), vecs)                            # key i is vector i

   query = vecs[42] + 0.05 * rng.normal(size=64).astype(np.float32)
   query /= np.linalg.norm(query)
   matches = index.search(query, 3)
   print([int(k) for k in matches.keys], [round(float(d), 3) for d in matches.distances])
   exact = np.argsort(-(vecs @ query))[:3]                     # the exact scan, for comparison
   print([int(k) for k in exact], len(index))
   ```

   Expected: `[42, 827, 976] [0.072, 0.637, 0.646]`, then `[42, 827, 976] 1000`. The index found the same three as
   the exact scan, and key 42 comes first at distance 0.072 (similarity 1 - 0.072 = 0.928). The first number is
   a *distance*; the project converts with `similarity = 1 - distance`.
2. Run the project's index tests that work on any platform:

   ```bash
   uv run pytest tests/integration/test_representation_index.py -q -k "not locked and not link"
   ```

   Expected on Linux: `76 passed, 10 deselected` (observed). The deselected ones depend on Windows file locking
   and links and pass in CI on Windows. Skim the test names: they read as the guarantees of the index
   (a missing, corrupt, mismatched or unsupported index is quarantined and rebuilt).
3. Look at a real index you made in [lesson 07](../../00-start-here/07-run-it-and-see-it-work.md):
   `cat ~/faceidentify-play/state/indexes/*/manifest.json` shows `ndim`, `metric: "cos"`, `count`, the file's
   `sha256` and `built_at`. Compare `count` with the number of faces processed.

## 5. Change it

Make the search wrong on purpose and see why revalidation exists: in step 1, `index.remove(42)` and search
again. The nearest keys become `[827, 976, 61]` (observed): the index has forgotten key 42. In the real system a *forgotten* face
is removed from the index **and the index is rebuilt** (a saved USearch generation keeps a removed key's
bytes), then verified: see [erasure](../../02-data-and-storage/07-erasure.md). The tests behind that are
`tests/integration/test_representation_erasure.py` and `tests/integration/test_index_coordinator.py`.

## 6. Break it on purpose

Add a vector of the wrong size: `index.add(1001, np.ones(32, dtype=np.float32))`. Expected (observed):
`ValueError: The number of vector dimensions doesn't match!` (the index has `ndim=64`). The project's wrapper checks the manifest's dimension
and metric against the file's header on open because `Index.load` adopts whatever the file says; a mismatch is
quarantined and rebuilt, never searched.

## 7. Exercises

1. In `matches.distances` the first value is 0.072. What is the cosine similarity?
2. Why does the project re-read each candidate from SQLite after the index answers?
3. What happens to a recognition decision when the index has not caught up with the database?
4. Is OpenCV a dependency?

**Answers**

1. About 0.928 (`1 - 0.072`).
2. The index is approximate and possibly stale; SQLite is the truth about whether the representation and its
   identity are still active.
3. The shortlist is flagged incomplete and the reasoner abstains (`RETRIEVAL_INCOMPLETE`), because "nobody
   found" might only mean "not indexed yet".
4. No (owner decision 2026-10-02).

## 8. Related files

- Previous: [05 Thresholds and errors](05-thresholds-and-errors.md) · [Recognition index](README.md)
- [The vector index and the outbox](../../02-data-and-storage/06-vector-index-and-outbox.md), [retrieval](../../03-backend/recognition/01-retrieval.md)
- [`backend/infrastructure/indexing/representation_index.py`](../../../../../backend/infrastructure/indexing/representation_index.py)
