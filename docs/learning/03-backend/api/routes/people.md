# Routes: people (`backend/api/routes/people.py`)

## 1. What this is and why it exists

An **Identity** is a visual subject ("these faces are all one subject"); a **Person** is a *named human*. They are
separate on purpose: one real person may appear as two identities (a beard, a decade apart) until you merge them, and
names are not unique. A Person exists **because someone named an Identity**: `POST /people` takes the name *and* the
identity and creates both the Person and the link in one transaction. There is no placeholder Person for an unknown
identity and no Person created alone (owner decision 2026-10-07). This module is naming, renaming, linking and
unlinking, and forgetting a person.

## 2. Where it lives

| Route | Use case (`backend/app/people/use_cases.py` unless noted) |
|---|---|
| `POST /api/v1/people` (201) | `name_identity` |
| `GET /api/v1/people`, `GET /api/v1/people/{id}` | queries over `people` (state `ACTIVE`) |
| `PATCH /api/v1/people/{id}` | `rename_person` (writes `PERSON_RENAMED` Evidence) |
| `POST /api/v1/people/{id}/assign-identity` | `assign_identity_to_person` |
| `POST /api/v1/people/{id}/remove-identity` | `remove_identity_from_person` |
| `POST /api/v1/people/{id}/forget` (204/202) | `ForgetIdentityUseCase.forget_person` (`backend/app/identities/forget.py`) |

Tests: `tests/integration/test_api_people.py`, `test_person_use_cases.py`, `test_api_forget.py`.

## 3. How it works

`PersonSummary`: `{"id", "display_name", "revision", "identity_count", "created_at", "updated_at"}`.

- **`POST /people`** body `{"display_name": "Ada Example", "identity_id": "<uuid>"}` (the name is trimmed, 1 to 200
  characters). It checks the identity is `ACTIVE`, then creates the Person, links it, and writes Evidence, atomically.
  `409 IDENTITY_ALREADY_NAMED` if the identity already has a person ("rename that person instead").
- **`PATCH /people/{id}`** body `{"display_name": "...", "expected_revision": N}`. A stale `expected_revision` is
  `409 PERSON_REVISION_CONFLICT`. Renaming changes **only** the Person row and writes `PERSON_RENAMED` Evidence (carrying
  revisions, not names); it never touches an Identity.
- **`assign-identity` / `remove-identity`** body `{"identity_id": "<uuid>"}`: link another identity to this person, or
  unlink one. `409 IDENTITY_NOT_ASSIGNABLE` when it is already linked; `409 IDENTITY_NOT_LINKED` when removing one that
  is not this person's. Reassigning is the way to correct a naming mistake.
- **`forget`**: runs [forget](../../lifecycle/03-forget.md) on each of the person's identities. The Person and the **name**
  stay, now without visual support. `204` when all is gone, `202 {"outstanding": [...]}` when cleanup is owed.
- Every successful change publishes `person.updated` with the id and new revision, **never the name** (REST stays
  authoritative; owner decision 2026-10-08).

## 4. Try it

**Works with no models. Verified 2026-10-12** (variables as in [call the API](../01-call-the-api.md); `$ID` an unnamed
identity, `$ID2` another).

```bash
curl -s -X POST -H "$H" -H "$J" -d "{\"display_name\":\"Ada Example\",\"identity_id\":\"$ID\"}" $B/api/v1/people
P=$(curl -s -H "$H" $B/api/v1/people | j "d['items'][0]['id']")
curl -s -X PATCH -H "$H" -H "$J" -d '{"display_name":"Ada Lovelace","expected_revision":5}' $B/api/v1/people/$P   # 409 stale
curl -s -X PATCH -H "$H" -H "$J" -d '{"display_name":"Ada Lovelace","expected_revision":1}' $B/api/v1/people/$P  # 200, revision 2
curl -s -X POST -H "$H" -H "$J" -d "{\"identity_id\":\"$ID2\"}" $B/api/v1/people/$P/assign-identity | j "(d['display_name'], d['identity_count'])"
curl -s -X POST -H "$H" -H "$J" -d "{\"identity_id\":\"$ID2\"}" $B/api/v1/people/$P/remove-identity | j "(d['display_name'], d['identity_count'])"
```

Observed: `{"display_name":"Ada Example","revision":1,"identity_count":1,...}`; the stale rename `409
PERSON_REVISION_CONFLICT` with `"reason": "person ... is at revision 1, expected 5"`; the good one `revision: 2`; assign
`('Ada Example', 2)` then remove `('Ada Example', 1)`. Errors: naming an already-named identity `409
IDENTITY_ALREADY_NAMED`; assigning an already-linked identity `409 IDENTITY_NOT_ASSIGNABLE` ("is already linked to person
..."); removing one that is not linked `409 IDENTITY_NOT_LINKED`; a blank name `422 VALIDATION_ERROR`
(`string_too_short` on `body.display_name`); an unknown person `404 PERSON_NOT_FOUND`. Then
`POST /people/$P/forget`: `204`; afterwards `GET /people/$P` still returns the person with `identity_count: 0`, and
`GET /search?q=ada` shows the person with `visual_support: false` and `biometric_memory_forgotten: true` while
`GET /identities` no longer lists that identity. **Forgetting is irreversible; do it on scratch data only.**

## 5. Change it

Run on 2026-10-12: change the name length cap, `max_length=200` in the `Name` type at the top of `people.py`, to `5`,
and run `tests/integration/test_api_people.py`: it fails at
`test_naming_an_identity_creates_the_person_and_shows_on_the_identity` (the name used there is longer than 5).
Restore with `git restore`. A change that affects meaning, not just a cap (for example allowing a Person to be created
without an identity) conflicts with an owner decision and the spec: stop and ask
([rules](../../../06-evaluation-and-operations/06-rules-branches-reviews.md)).

## 6. Break it on purpose

Rename with the revision you saw *before* someone else renamed (two browser windows): `PERSON_REVISION_CONFLICT`; the
fix is to refetch and retry, which the screen does. Name an identity that was merged away in the meantime: `404
IDENTITY_NOT_FOUND`.

## 7. Exercises

1. Why can a Person not exist without an identity that prompted it?
2. What does a rename change, and what does it not touch?
3. How do you move an identity from one person to another?
4. After `forget` on a person, what is left of them?

**Answers**

1. An unknown identity never gets a placeholder name; a name always belongs to a face someone actually named.
2. Only the Person row (and a `PERSON_RENAMED` Evidence row); never an Identity's id or state.
3. `remove-identity` from the first person, then `assign-identity` to the second (reassigning is the correction).
4. The Person and the name, with no visual memory; their pictures stay.

## 8. Related files

- Previous: [memory](memory.md) · Next: [corrections](corrections.md) · [Routes index](README.md)
- [People and naming](../../domain/05-people-and-naming.md), [forget](../../lifecycle/03-forget.md)
- [`backend/api/routes/people.py`](../../../../../backend/api/routes/people.py), [`backend/app/people/use_cases.py`](../../../../../backend/app/people/use_cases.py)
