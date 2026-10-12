# Lifecycle 03 Forget

## 1. What this is and why it exists

"Forget" removes **the application's memory of what a face looked like** while the photographs stay. It is the only operation that
erases biometric memory without deleting media. "Forget person" is the user-facing phrase for forgetting each identity of a person;
the person's name and notes stay (they are user-authored), without any visual support behind them.

## 2. Where it lives

| Thing | Where |
|---|---|
| `ForgetIdentity` use case | `backend/app/identities/forget.py` |
| The route | `POST /api/v1/identities/{id}/forget` with `{"expected_revision": N}` (204, or 202 with outstanding work) |
| Erasure of vectors | `RepresentationEraser` ([erasure](../../02-data-and-storage/07-erasure.md)) |
| Tests | `tests/integration/test_forget_identity.py`, `test_api_forget.py` (32 together) |

## 3. How it works

The owner's rule: *authoritative forgetting happens before physical cleanup; a cleanup failure must not leave the forgotten identity
recognisable.*

1. **Authoritative forget** (one transaction for the whole batch): each identity becomes `FORGOTTEN`; its person link ends (with a
   history entry); its occurrences stop being authoritative; **every representation it owns, and any still on an identity merged
   into it, is queued for erasure** (out of retrieval from this commit on); the face crops get their deletion intent;
   `IDENTITY_FORGOTTEN` evidence records it, with ids only.
2. **Erasure**: the eraser removes the vectors from the row, the index files and the write-ahead log (one rebuild per space), and the
   crops' bytes go. A crash or a locked file leaves the representations `ERASING` and the crops `DELETING`; startup recovery
   finishes both, and so does repeating the request.
- The faces themselves (observations, boxes, the media) stay as media-analysis data but **no longer resolve to anyone**. A later
  photograph of the same person cannot be matched to the forgotten identity, because nothing is remembered of what they looked like. What happens to the new face
  depends on the policy and on who else is in the library: with other candidates left, the current real-profile (abstain-only) policy answers `ABSTAIN`, so the face is
  *unresolved* and waits for you to place it; only with nothing to compare against does it start a new identity.

## 4. Try it

**Works with no models. Verified 2026-10-12.** On a **copy** of the practice library, after the merge and the name from the earlier
lessons, with the backend running: find the identity (`GET /api/v1/identities`), then
`curl -s -X POST -H "$H" -H "$J" -d '{"expected_revision": N}' $B/api/v1/identities/$ID/forget` (use its current revision). Observed
through a script: `204`; the identity list is then empty and the person list still shows `('Ada Example', 0)`: the name stays, with
no identity behind it; `/readiness` stayed `READY`. Stop the backend and read the database:

```bash
uv run python q.py <library> "select state, revision, forgotten_at is not null from identities" "select state, count(*), sum(vector is null), sum(ann_key is null) from representations group by 1" "select display_name, state from people" "select state from identity_person_associations" "select state, count(*) from occurrences group by 1" "select state, count(*) from observations group by 1"
```

Observed: identities `('MERGED', 5, 0)` and `('FORGOTTEN', 9, 1)`; representations `('ERASED', 2, 2, 2)`: **both vectors and keys gone**;
person `('Ada Example', 'ACTIVE')` with its association `REMOVED`; occurrences `('DELETED', 2)`; observations still `('ACTIVE', 2)`. Evidence now
includes `IDENTITY_FORGOTTEN` and `IDENTITY_REMOVED_FROM_PERSON`. Tests: `uv run pytest tests/integration/test_forget_identity.py tests/integration/test_api_forget.py -q`
(`32 passed`).

## 5. Change it

Extending what forget removes (say a new kind of derived biometric data) means adding it to step 1's queue, step 2's erasure, the
recovery that finishes it, and a test that a crash between the steps still ends clean. If any biometric copy is not covered by
forget, the product promise is broken, so the forget tests are the first place to look.

## 6. Break it on purpose

Forget with a stale `expected_revision`: a conflict and nothing is erased. In a scratch edit make step 1 skip the representations of a
merged identity: the tests that forget a merged survivor fail (the vectors on the absorbed identity must go too).

## 7. Exercises

1. What survives forgetting an identity? What does not?
2. Why is a later photograph of the person not recognised as them?
3. Why does authoritative forgetting come before physical erasure?
4. How does forget differ from permanent delete?

**Answers**

1. Survives: photographs, boxes, the person's name. Gone: the vectors and keys, the occurrences' authority, the person link.
2. Nothing remains to compare against. The face ends up unresolved (abstained) or, in an empty library, as a new identity.
3. If cleanup fails, the identity must already be unrecognisable; physical cleanup is retried.
4. Forget removes biometric memory and keeps the media; permanent delete removes the picture and its faces' vectors.

## 8. Related files

- Previous: [02](02-permanent-delete.md) · Up: [Lifecycle](README.md)
- [`backend/app/identities/forget.py`](../../../../backend/app/identities/forget.py), [erasure](../../02-data-and-storage/07-erasure.md)
