# Recognition 01 Vectors and NumPy

## 1. What this is and why it exists

To compare two faces a computer needs a number that says "how alike". The trick the whole product
rests on: turn each face into a **vector** (a list of numbers, a point in space) so that faces of the
same person land close together, then measure closeness with one cheap operation. This lesson builds
that operation, **cosine similarity**, from scratch, and introduces **NumPy**, the library that does
arithmetic on millions of numbers at once.

## 2. Where it lives

| Idea | Where |
|---|---|
| A face is a vector of 512 `float32`s | `representations.vector` in the database; `canonical_vector` in `backend/ml/perception/alignment.py` |
| Every stored vector is unit length | the same function: divides by the L2 norm; a zero or non-finite vector is refused |
| Comparison by dot product | `float(a[2] @ b[2])` in `evaluation/measure_operating_point.py`; the USearch index uses the `cos` metric |
| An image is an array | `backend/infrastructure/media/image.py` (decode with Pillow), `uint8` HWC arrays everywhere in `backend/ml/perception/` |

## 3. How it works

### Vectors

A **vector** is an ordered list of numbers: `[0.2, -1.5, 3.0]`. The number of entries is its
**dimension**. Two numbers make a point on a sheet of paper; three, a point in a room; 512 numbers, a
point in a space we cannot picture but whose maths works identically.

Two operations matter:

- **Length (norm).** For `[x, y]` it is `sqrt(x*x + y*y)` (Pythagoras). In general: add the squares of
  all entries, take the square root. A vector of length 1 is a **unit vector**.
- **Dot product.** Multiply matching entries and add: `[1, 2, 3] . [4, 5, 6] = 1*4 + 2*5 + 3*6 = 32`.

### Cosine similarity

```
cosine(a, b) = (a . b) / (length(a) * length(b))
```

It is `1` when the vectors point the same way, `0` at right angles (unrelated), `-1` when opposite. **If
both are unit vectors, the lengths are 1 and cosine similarity is just the dot product.** That is why
the project normalises every face vector to length 1 ("L2 normalisation") and then compares with a
plain dot product: it is fast, and one number between -1 and 1 results. This number is called the
**similarity** (or "Similarity score" on screen). It is **not a probability**: 0.62 does not mean 62%
sure.

### NumPy

**NumPy** works with **arrays** (`ndarray`): a grid of numbers of one **dtype** (`float32`, `uint8`) and a
**shape**.

```python
v = np.array([1.0, 2.0, 3.0], dtype=np.float32)     # shape (3,)  a vector
m = np.zeros((2, 3))                                # shape (2, 3) 2 rows, 3 columns
img = np.zeros((480, 640, 3), dtype=np.uint8)       # (height, width, channels): a colour image
```

- An **image** is an array: rows of pixels, each with three numbers (red, green, blue) from 0 to 255
  (`uint8` = unsigned 8-bit integer). "Decoding" a JPEG means turning its bytes into this array.
- Operations act on **whole arrays at once** (*vectorisation*, much faster than a Python loop):
  `a + b`, `a * 2`, `a @ b` (dot / matrix product), `a.T`, `np.linalg.norm(a)`.
- **Slicing** works in several dimensions: `img[10:20, 30:40]` is a rectangle of pixels (how a face is cropped).
- `matrix @ vector` scores one vector against a whole gallery in a single step.
- `np.percentile(values, 99.9)`: the value below which 99.9% of `values` fall.

## 4. Try it

**Works with no models. Verified 2026-10-12.** In `uv run python`:

1. Cosine similarity by hand, then with unit vectors:

   ```python
   >>> import numpy as np
   >>> a = np.array([1.0, 0.0]); b = np.array([1.0, 1.0])
   >>> round(float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b))), 4)
   0.7071
   >>> ua, ub = a / np.linalg.norm(a), b / np.linalg.norm(b)
   >>> round(float(ua @ ub), 4)          # unit vectors: the dot product alone
   0.7071
   ```

   `[1, 0]` and `[1, 1]` are 45 degrees apart and `cos(45 degrees)` is 0.7071.
2. Score a query against a whole gallery at once:

   ```python
   >>> gallery = np.array([[1, 0], [0, 1], [0.6, 0.8]]); query = np.array([0.6, 0.8])
   >>> gallery @ query
   array([0.6, 0.8, 1. ])
   ```

   The third row is identical to the query (similarity 1.0), the first is the least alike.
3. An image is an array, and a crop is a slice:

   ```python
   >>> img = np.zeros((480, 640, 3), dtype=np.uint8)
   >>> img.shape, img.dtype, img[10:20, 30:40].shape
   ((480, 640, 3), dtype('uint8'), (10, 10, 3))
   ```

4. The project's own normaliser. A raw model output is divided by its length; a zero vector is refused:

   ```python
   >>> from backend.ml.perception.alignment import canonical_vector
   >>> v = canonical_vector(np.arange(1, 513, dtype=np.float32), 512)
   >>> v.shape, v.dtype, round(float(np.linalg.norm(v)), 6)
   ((512,), dtype('float32'), 1.0)
   >>> canonical_vector(np.zeros(512), 512)
   ContractError: INFERENCE_FAILED: the embedder returned a zero vector
   ```

5. See it in the real run: after [lesson 07](../../00-start-here/07-run-it-and-see-it-work.md), the face search
   answer for the red picture showed `"similarity": 1.0` for its own identity and about `0.208` for the other.
   Those are exactly cosine similarities of unit vectors (64-dimensional in the development profile; 512 in the real one).

## 5. Change it

Change the numbers, not the code: in step 2 replace the query by `[0.0, 1.0]` and predict the three scores
before you look (`0.0, 1.0, 0.8`). The same arithmetic is pinned in
`tests/unit/test_perception_alignment.py` (the vector contract); run it:

```bash
uv run pytest tests/unit/test_perception_alignment.py -q
```

Expected: pass (it checks that outputs are finite, the right length, `float32`, unit norm). If
you edited `canonical_vector` to skip the division, those tests fail: the "every stored vector has norm
one" promise is what lets the rest of the system use a plain dot product.

## 6. Break it on purpose

Compare two vectors of different lengths: `np.array([1.0, 2.0]) @ np.array([1.0, 2.0, 3.0])` raises
`ValueError: matmul: Input operand 1 has a mismatch in its core dimension 0...`. The same refusal
protects the database: vectors from different models have different dimensions and live in different
**representation spaces**; they must never be compared with each other (see
[packages and the catalog](../../03-backend/runtime-and-worker/04-packages-and-catalog.md)).

## 7. Exercises

1. What is the dot product of `[1, 2, 3]` and `[4, 5, 6]`?
2. If two vectors are unit length, what is their cosine similarity?
3. A similarity of 0.3 between two faces: probability they are the same person?
4. What is the shape and dtype of a 480 by 640 colour photograph decoded into an array?

**Answers**

1. 32 (`1*4 + 2*5 + 3*6`).
2. Their dot product.
3. Unknown; it is a raw cosine, never a probability. Where a threshold puts it depends on measurement
   ([thresholds and errors](05-thresholds-and-errors.md)).
4. `(480, 640, 3)` and `uint8`.

## 8. Related files

- Next: [02 Models, ONNX and providers](02-models-onnx-and-providers.md) · [Recognition index](README.md)
- [`backend/ml/perception/alignment.py`](../../../../backend/ml/perception/alignment.py)
- Further reading: 3Blue1Brown's "Essence of linear algebra" series for the picture behind vectors
