# Recognition 01 Retrieval

## 1. What this is and why it exists

Retrieval answers one question: **which stored faces are nearest to this vector?** It returns a short, bounded list and
nothing more. A similarity from the index is a *hint*, not an identity and not a decision. The part of retrieval worth
understanding is how carefully it refuses to trust the index: every candidate the index names is **re-checked against SQLite**,
and the report says how many were refused, so a short list is never mistaken for a complete one.

## 2. Where it lives

| Thing | Where |
|---|---|
| `retrieve`, `Retrieval`, `RetrievedCandidate`, `Pool`, `IncompatibleSpaceError` | `backend/app/recognition/retrieval.py` |
| The index it queries | `backend/infrastructure/indexing/` ([vector index lesson](../../02-data-and-storage/06-vector-index-and-outbox.md)) |
| Tests | `tests/integration/test_recognition_retrieval.py` (28) |

## 3. How it works

- **One space, two pools.** The query vector, the **global** index (the space's persisted index of `ACTIVE` representations)
  and the **run-local** pool (this run's own `PENDING` representations, held in memory) must all belong to the same
  representation space, dimension and cosine metric, or `IncompatibleSpaceError` is raised and *nothing is searched*.
- **Why a run-local pool?** Two faces in the same photograph are not in the global index yet (nothing is accepted), but the
  second face may match the first. The run-local pool lets them see each other.
- **`exclude`**: the query's own representation exists (as `PENDING`) before it is recognised and would be its own nearest
  neighbour at similarity 1.0, so the caller excludes it, and the other faces of the same image. Each pool is asked for that
  many extra candidates, so excluding does not shorten the list.
- **Revalidation.** A stale index can name a representation that was erased, merged away or discarded. SQLite is asked about
  every candidate: a global one must still be in the space and `ACTIVE` with an `ACTIVE` identity (or no identity at all, an
  accepted abstention); a run-local one must still be `PENDING` in this run. Refused candidates are counted in `dropped`.
- **`converged`**: whether the index has caught up with the database (no `ADD` or `REMOVE` waiting or failed). An index that
  is behind looks exactly like "never seen this person", so an unconverged retrieval is flagged, not trusted.
- **Distance versus similarity**: USearch returns a distance (`1 - cosine similarity`); retrieval turns it into a similarity.
  Only the cosine metric is accepted.
- **No index is an error, not an empty answer**: "no candidates" and "could not look" are different, and retrieval never
  confuses them.

## 4. Try it

**Works with no models. Verified 2026-10-12.**

```bash
uv run pytest tests/integration/test_recognition_retrieval.py -q
```

Expected: `38 passed` (observed: 28 test functions, some parametrised). Read these names: the tests are
grouped as compatibility refusals, revalidation (`dropped`), exclusion and `converged`. See a real shortlist in the practice
library's evidence: `select payload_json from evidence where kind = 'IDENTITY_MATCHED'` ([evidence lesson](../domain/06-occurrences-and-evidence.md))
shows `"retrieval": {"requested_k": 5, "returned": 2, "dropped": 0, "converged": true}`: five were asked for, two exist.

## 5. Change it

The shortlist size `k` is the caller's measured choice and has no default (`RecognitionService` requires at least 2, so a margin
can be measured). To change how retrieval filters, write the test in `test_recognition_retrieval.py` first, using a stale index
fake (the existing tests show how), then change `retrieve`. Never add a path that returns candidates without revalidation.

## 6. Break it on purpose

In a scratch edit skip the SQLite revalidation and run the retrieval tests: the revalidation tests fail, because a planted stale
candidate now appears. Restore with `git restore`. That test is what keeps an erased face from being matched.

## 7. Exercises

1. Why does retrieval re-check candidates in SQLite?
2. What is `dropped` and why report it?
3. Why is the query's own vector excluded?
4. Why a run-local pool?

**Answers**

1. The index is derived and may be stale; the database is the truth.
2. The number of index answers SQLite refused. A short list with drops may hide a nearer candidate.
3. It would be its own nearest neighbour at similarity 1.0 and every face would "match" itself.
4. Faces in one photograph are not in the global index yet but may belong together.

## 8. Related files

- Next: [02 Assessment](02-assessment.md)
- [`backend/app/recognition/retrieval.py`](../../../../../backend/app/recognition/retrieval.py), [nearest neighbour](../../01-basics/recognition-ideas/06-nearest-neighbour-and-video-vocabulary.md)
