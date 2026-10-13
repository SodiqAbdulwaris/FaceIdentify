# Recognition: how a face becomes a decision

Recognition is a pipeline of three small, separate steps, each with its own file and tests, so each can be understood and changed
alone:

```text
vector ──▶ retrieval ──▶ assessment ──▶ decision (reasoner + policy)
         "who is near?"   "what does the    "match, create or
                           neighbourhood      abstain, and why"
                           look like?"
```

| Lesson | Teaches |
|---|---|
| [01 Retrieval](01-retrieval.md) | the shortlist: two pools, revalidation, `dropped` and `converged` |
| [02 Assessment](02-assessment.md) | grouping candidates by identity and measuring the margin |
| [03 The decision policy](03-decision-policy.md) | the reasoner's rules, with a table you can run |
| [04 Decisions in memory](04-decisions-in-memory.md) | how a decision becomes identities, occurrences and evidence |
| [05 The face query](05-face-query.md) | the same pipeline, read-only, for "who is this?" |

**Works with no models. Verified 2026-10-12.** The tests for the whole folder:

```bash
uv run pytest tests/integration/test_recognition_retrieval.py tests/integration/test_recognition_service.py tests/unit/test_recognition_reasoner.py tests/integration/test_query_only_recognition.py -q
```

Observed: `119 passed` (28 + 9 + 37 + 13 tests in the four files, plus parametrised cases).

The numbers that judge a face are *measured*, not chosen: see [thresholds](../../01-basics/recognition-ideas/05-thresholds-and-errors.md)
and the [evaluation lessons](../../06-evaluation-and-operations/README.md). Back to [the backend](../README.md).
