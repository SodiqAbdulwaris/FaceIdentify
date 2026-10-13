# Routes: identity changes (`backend/api/routes/identity_changes.py`)

## 1. What this is and why it exists

Sometimes the memory itself needs reshaping: two identities turn out to be the same person (**merge**), one identity
turns out to hold two people (**split**), or someone's face memory must go (**forget**). These are the heaviest
writes in the product; each is **one atomic transaction** that moves rows, writes Evidence and bumps revisions, so a
failure halfway leaves nothing changed. This module is their HTTP face.

## 2. Where it lives

| Route | Use case |
|---|---|
| `POST /api/v1/identities/merge` (200) | `merge_identities` in `backend/app/identities/use_cases.py`, once per losing identity |
| `POST /api/v1/identities/{id}/split` (201) | `split_identity` (same file), after `occurrence_support` |
| `POST /api/v1/identities/{id}/forget` (204/202) | `ForgetIdentityUseCase.forget` (`backend/app/identities/forget.py`) |

Tests: `tests/integration/test_api_identity_changes.py`, `test_identity_merge_split.py`, `test_api_forget.py`,
`test_forget_identity.py`, `tests/property/test_identity_lifecycle_invariants.py` (hypothesis checks the invariants over
random sequences of merges and splits).

## 3. How it works

### Merge

Body `{"identities": [{"id": "<uuid>", "revision": N}, ...], "preferred_identity_id": "<uuid>"}`: every identity involved,
the survivor included, each with the revision you saw; at least two, all different, the survivor among them
(`422 INVALID_MERGE` otherwise). The survivor keeps its row; every other member becomes `MERGED` with
`merged_into_identity_id` set and a `MERGED_INTO` **lineage** edge: **never deleted**. Their ACTIVE representations and
occurrences move to the survivor (ownership only; the vector index is untouched); a Person link carries over if only the
loser had one, and the survivor's own naming always wins. `IDENTITY_MERGED` Evidence is written. A stale revision is `409
IDENTITY_CHANGED`. The answer is the survivor's `IdentitySummary`. A three-way merge is simply one call per loser inside
the same transaction, so it is atomic as a whole.

### Split

Body `{"occurrence_ids": [...], "expected_revision": N}` (the revision of the identity you are splitting). The faces
(occurrences) you choose, with the vectors they rest on, form a **new, already-`ACTIVE`** identity (a human decision needs
no run to accept it). The source keeps everything else and stays `ACTIVE`. Refusals: `422 INVALID_SPLIT` (nothing chosen, or
a chosen face has nothing to split off), `404 OCCURRENCE_NOT_FOUND` (not one of this identity's faces), `409 IDENTITY_CHANGED`
(stale), and **`409 SPLIT_CONFLICT`**: an occurrence supported by vectors on both sides (some you chose, some you did not)
is a conflict you must resolve, never kept automatically. Answer `201` with the new `IdentitySummary`. Both identities get
an `identity.updated` event.

### Forget

Body `{"expected_revision": N}`. The only operation that removes an identity's biometric vectors ([erasure](../../../02-data-and-storage/07-erasure.md)),
irreversibly. `204` when everything is gone, `202 {"outstanding": [...]}` when cleanup is owed (and `/readiness` turns
`DEGRADED`). A repeat is harmless; the identity is `404` afterwards. The media and any linked Person (with the name) stay.

## 4. Try it

**Works with no models. Verified 2026-10-12** on a scratch library with at least three identities (import and process
three different pictures; variables as in [call the API](../01-call-the-api.md)). Use revisions you read, never guessed.

```bash
REV2=$(curl -s -H "$H" $B/api/v1/identities/$ID2 | j "d['revision']"); REV3=$(curl -s -H "$H" $B/api/v1/identities/$ID3 | j "d['revision']")
# merge ID3 into ID2
curl -s -X POST -H "$H" -H "$J" \
  -d "{\"identities\":[{\"id\":\"$ID2\",\"revision\":$REV2},{\"id\":\"$ID3\",\"revision\":$REV3}],\"preferred_identity_id\":\"$ID2\"}" \
  $B/api/v1/identities/merge | j "(d['id'][:8], d['state'], d['revision'], d['occurrence_count'], d['source_count'])"
curl -s -H "$H" $B/api/v1/identities/$ID3          # the loser: IDENTITY_NOT_FOUND
# split one of the survivor's faces off again
REV2=$(curl -s -H "$H" $B/api/v1/identities/$ID2 | j "d['revision']")
curl -s -X POST -H "$H" -H "$J" -d "{\"occurrence_ids\":[\"$OCC3\"],\"expected_revision\":$REV2}" \
  $B/api/v1/identities/$ID2/split | j "(d['id'][:8], d['state'], d['revision'], d['occurrence_count'])"
```

Observed: merge `('cf485fde', 'ACTIVE', 4, 2, 2)` (the survivor now has 2 faces from 2 pictures and revision 4); the loser
is `IDENTITY_NOT_FOUND`; split `('232c33bc', 'ACTIVE', 1, 1)` (a **new** identity with one face). A malformed merge
(`"identities"` with one member) is `422 INVALID_MERGE`: "Choose at least two different identities, the survivor among
them." Forget (scratch data only): `POST $B/api/v1/identities/$ID/forget` with `{"expected_revision": N}` returned `204`,
a repeat `204` again, and `GET /identities/$ID` is then `404`. The database after a merge holds an `IDENTITY_MERGED`
Evidence row and the loser as `MERGED` (`select state, count(*) from identities group by state`); after the split an
`IDENTITY_SPLIT` row. A `SPLIT_CONFLICT` needs an occurrence supported on both sides of the split; it is pinned by
`test_api_identity_changes.py` (fixtures build it), not reproducible with the development profile's one-face pictures.

## 5. Change it

Run on 2026-10-12: change `or len(members) < 2` in `merge` to `or len(members) < 1` and run
`tests/integration/test_api_identity_changes.py`: it fails at
`test_a_merge_is_refused_when_it_is_malformed_stale_or_names_nobody` (a one-member "merge" is no longer refused).
Restore with `git restore`. The rules behind a merge/split change (atomicity, Evidence, lineage, who wins the Person link,
what a split conflict is) are owner decisions recorded in `.agents/CONTEXT.md` (2026-10-07, "merge and split also move
`Occurrence.identity_id`") and the identity model spec; a behaviour change needs the owner first.

## 6. Break it on purpose

Merge with a stale revision (read it, change the identity in another call, then merge): `409 IDENTITY_CHANGED` ("One of the
people changed since you looked. Reload."). Merge an identity into itself or list the same id twice: `422 INVALID_MERGE`.
Split a face that belongs to another identity: `404 OCCURRENCE_NOT_FOUND`. Nothing is partly applied in any of these.

## 7. Exercises

1. After a merge, what happens to the losing identity's row?
2. What makes a split return `SPLIT_CONFLICT`?
3. Why does a merge not queue any index operations?
4. Which of the three routes is irreversible?

**Answers**

1. It stays as a `MERGED` row pointing at the survivor, with a `MERGED_INTO` lineage edge; it is no longer shown.
2. An occurrence whose supporting vectors are partly in the chosen set and partly not.
3. Merge only changes ownership; the vectors and their index keys are unchanged.
4. Forget (the vectors are erased); merge and split are recorded in lineage and Evidence.

## 8. Related files

- Previous: [corrections](corrections.md) · Next: [search](search.md) · [Routes index](README.md)
- [Identities and lineage](../../domain/04-identities-and-lineage.md), [forget](../../lifecycle/03-forget.md)
- [`backend/api/routes/identity_changes.py`](../../../../../../backend/api/routes/identity_changes.py), [`backend/app/identities/use_cases.py`](../../../../../../backend/app/identities/use_cases.py)
