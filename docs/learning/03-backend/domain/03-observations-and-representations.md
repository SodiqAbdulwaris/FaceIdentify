# Domain 03 Observations and representations

## 1. What this is and why it exists

When a picture is processed the application keeps two separate things for each face: an **observation** (a box: "there is a
face here, found by this detector") and a **representation** (the vector the embedder computed for that box, in one
**representation space**). They are separated because the box is a fact about the picture while the vector depends on a
particular model: a new embedder gives new representations for the same observations.

## 2. Where it lives

| Thing | Where |
|---|---|
| `Observation`, `Representation`, `RepresentationSpace`, `AnnKeySequence` and their state enums | `backend/app/memory/models.py` |
| Writing pending output | `backend/app/processing/pending_output.py`; acceptance in `accept_run.py` |
| The vector index keyed by `ann_key` | [vector index lesson](../../02-data-and-storage/06-vector-index-and-outbox.md) |
| Tests | `tests/integration/test_memory_models.py`, `test_pending_output.py` |

## 3. How it works

- **Observation**: `source_id`, the run and segment that produced it, a normalized box (`bbox_x`, `bbox_y`, `bbox_width`,
  `bbox_height`, all within 0..1, enforced by a check), `sequence_in_run` (unique per run), an optional `face_crop_artifact_id`,
  and the detector's `detector_component_version_id` and `runtime_variant_id` (provenance). Images carry no frame or
  time; video observations carry both (a check pairs them). States: `PENDING`, `ACTIVE`, `SUPERSEDED`, `REJECTED`, `DELETED` (`SUPERSEDED` is designed for re-runs and not set by any code yet).
- **Representation**: `observation_id`, `representation_space_id`, `identity_id` (empty on a `PENDING` representation, and on an `ACTIVE` one only for an accepted *abstention*),
  `ann_key` (a number unique inside its space), `vector` (little-endian float32 bytes, so `4 x dimension` bytes, enforced), and
  `state`: `PENDING`, `ACTIVE`, `SUPERSEDED`, `ERASING`, `ERASED`, `DELETED`. A check
  says an `ACTIVE` representation must have an `ann_key`; another says only an `ERASED` one may lack its vector, and an
  `ERASED` one has neither vector nor key ([erasure](../../02-data-and-storage/07-erasure.md)).
- **Representation space**: one embedder's vector world: `dimension`, `metric` (`COSINE`), `state` (`ACTIVE`, `DEPRECATED`).
  Vectors from different spaces are never compared; each space has its own index and its own `ann_key` sequence.
- **Pending first**: a run writes its observations and representations as `PENDING` (private). Only **acceptance** turns them
  `ACTIVE`, in one transaction ([checkpoints and acceptance](../processing/04-checkpoints-and-acceptance.md)).

## 4. Try it

**Works with no models. Verified 2026-10-12.** On the practice library ([README](README.md)):

```bash
uv run python q.py ~/faceidentify-play/lib "select sequence_in_run, state, round(bbox_x,2), round(bbox_width,2), face_crop_artifact_id is not null from observations" "select state, ann_key, vector_dimension, length(vector), identity_id is not null from representations" "select state, metric, dimension from representation_spaces"
```

Observed: three observations (`0, 'ACTIVE', 0.2, 0.6, 0`: the development perception's fixed box, no face crop), three
representations (`'ACTIVE', 1..3, 64, 256, 1`: dimension 64, `256 = 4 x 64` bytes, each with an identity), one space
(`'ACTIVE', 'COSINE', 64`). Decode a vector yourself:

```bash
uv run python -c "
import sqlite3, struct, pathlib
db = pathlib.Path.home() / 'faceidentify-play/lib/database/library.db'
con = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
blob = con.execute('select vector from representations order by ann_key limit 1').fetchone()[0]
values = struct.unpack('<64f', blob)
print(len(values), round(sum(v*v for v in values) ** 0.5, 3))
"
```

Observed: `64 1.0` (the vectors are unit length, so a dot product is a cosine).

## 5. Change it

Nothing here changes by editing a row: output is created only by the pipeline. The safe change is a read-only one: add a query
of your own in `q.py`, for example how many observations each source has.

## 6. Break it on purpose

In a **copy** of the database (the backup API makes a safe copy, [database lesson](../../02-data-and-storage/09-read-a-database-and-a-log.md)),
try `update representations set vector = x'00' where ann_key = 1;`: it fails with `IntegrityError: CHECK constraint failed: ck_representations_vector_length` (observed). That is the database
defending the invariant.

## 7. Exercises

1. Why are observation and representation different tables?
2. How many bytes is a 64-dimension vector, and why?
3. Which state may a representation without a vector be in?
4. Why is a vector from space A never compared with one from space B?

**Answers**

1. The box is a fact about the picture; the vector depends on the embedder, which can change.
2. 256: 64 values of 4 bytes (float32).
3. `ERASED` only.
4. Different models place faces in unrelated coordinate systems; the distances would be meaningless.

## 8. Related files

- Previous: [02 Sources and artifacts](02-sources-and-artifacts.md) · Next: [04 Identities and lineage](04-identities-and-lineage.md)
- [`backend/app/memory/models.py`](../../../../backend/app/memory/models.py), [vectors](../../01-basics/recognition-ideas/01-vectors-and-numpy.md)
