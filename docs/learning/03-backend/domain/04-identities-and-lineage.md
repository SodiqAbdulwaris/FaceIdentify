# Domain 04 Identities and lineage

## 1. What this is and why it exists

An **identity** is the application's answer to "is this the same face as that one?", remembered. It is not a vector (it
*has* representations), not a name (a **person** is that), and not an index entry. Identities exist so that a hundred
photographs of the same face are one thing you can name once. Because recognition can be wrong, identities can be **merged**
(two were really one) and **split** (one was really two), and the history of that is kept as **lineage**.

## 2. Where it lives

| Thing | Where |
|---|---|
| `Identity`, `IdentityState`, `IdentityLineage` | `backend/app/identities/models.py` |
| Creating and matching (during acceptance) | `backend/app/processing/accept_run.py` |
| Merge, split, move a face | `backend/app/identities/use_cases.py`, `corrections.py` |
| Forgetting | `backend/app/identities/forget.py` ([forget lesson](../lifecycle/03-forget.md)) |
| Routes | [identity-changes](../api/routes/identity-changes.md), [corrections](../api/routes/corrections.md) |
| Tests | `tests/integration/test_identity_manager.py`, `test_corrections.py` (20), `test_forget_identity.py` |

## 3. How it works

- **States**: `PENDING` (made by an unaccepted run), `ACTIVE`, `MERGED` (kept as a row that says where it went),
  `FORGOTTEN`, `DELETED`. A check requires a `MERGED` identity to name `merged_into_identity_id`, and forbids merging into itself.
- **`revision`** counts changes; every change request carries the revision the caller saw, and a changed identity is refused
  as stale instead of silently overwritten ([states and revisions](07-states-revisions-provenance.md)).
- **Merge** keeps the surviving identity, marks the other `MERGED`, moves its occurrences and `ACTIVE` representations to the
  survivor, adds an `identity_lineage` row (`MERGED_INTO`) and one `IDENTITY_MERGED` evidence row. Ownership moves; the
  **index is untouched** (an index entry knows only a key, not an owner), so no index operation is written.
- **Split** takes chosen occurrences out into a new unknown identity (`SPLIT_FROM`).
- **Recognition never edits history**: a later automatic decision does not undo a correction, and there is deliberately no
  "cannot link" constraint (owner decision 2026-10-07): the same similar face may be matched again.

## 4. Try it

**Works with no models. Verified 2026-10-12.** The practice library has two identities (the red picture and its copy share
one, so ids differ from the numbers below). Merge them with the API as in the [identity-changes lesson](../api/routes/identity-changes.md)
(send both ids with their current revisions and the survivor in `preferred_identity_id`), stop the backend, and query:

```bash
uv run python q.py ~/faceidentify-play/lib "select state, revision, substr(merged_into_identity_id,1,8) from identities" "select substr(from_identity_id,1,8), substr(to_identity_id,1,8), kind from identity_lineage" "select substr(identity_id,1,8), count(*) from representations group by 1" "select kind, count(*) from evidence group by 1"
```

Observed: `('MERGED', 5, '535af944')` and `('ACTIVE', 5, None)`; one lineage row `('39d21787', '535af944', 'MERGED_INTO')`; **all three
representations now belong to the survivor** (`('535af944', 3)`); evidence gained `('IDENTITY_MERGED', 1)`. The merged row is not
deleted: it points to its successor. Tests: `uv run pytest tests/integration/test_identity_manager.py tests/integration/test_corrections.py -q`
(`test_corrections.py` alone has 20 tests).

## 5. Change it

A safe read-only change: write a query that follows `merged_into_identity_id` to the final survivor of a chain
(`with recursive`). That is what the code does whenever a client holds an old id.

## 6. Break it on purpose

Call merge with a stale revision: the API answers a conflict (409) and nothing changes ([routes lesson](../api/routes/identity-changes.md)).
In a copy of the database, try `update identities set state='MERGED' where id=...` without a target: the `merged_target` check refuses it.

## 7. Exercises

1. After a merge, where do the loser's representations point?
2. Why is the index not changed by a merge?
3. What row proves a merge happened and why?
4. Can an identity be both named and `MERGED`?

**Answers**

1. To the survivor (`identity_id` was updated).
2. The index holds keys only; ownership is in the database.
3. `identity_lineage` (the edge) and an `IDENTITY_MERGED` evidence row (the reason).
4. Its person association ends/moves with the merge; the loser keeps its row for history, not as a live subject.

## 8. Related files

- Previous: [03](03-observations-and-representations.md) · Next: [05 People and naming](05-people-and-naming.md)
- [`backend/app/identities/models.py`](../../../../backend/app/identities/models.py)
