# Domain 05 People and naming

## 1. What this is and why it exists

A **person** is a name a human gave. It is separate from an identity on purpose: naming should never alter recognition, and
recognition should never invent names. The link between them is an **association** that can end and be replaced, so a wrong
naming is corrected without losing why the first link existed.

## 2. Where it lives

| Thing | Where |
|---|---|
| `Person`, `PersonState`, `IdentityPersonAssociation`, `AssociationState` | `backend/app/people/models.py` |
| `name_identity`, `assign_identity_to_person`, `remove_identity_from_person`, `rename_person` | `backend/app/people/use_cases.py` |
| Routes | [people](../api/routes/people.md) |
| Tests | `tests/integration/test_person_use_cases.py` |

## 3. How it works

- **A person is created only by naming an identity** (owner decision 2026-10-07): `name_identity` makes the person and the
  association in one transaction. There is never a placeholder person for an unknown identity, and an empty name is refused.
- **Only an `ACTIVE` identity can be named**, and one that already has a person is refused ("rename that person instead").
- **Names are not unique** (two people may be called Sam). The table stores `display_name` and `normalized_name`
  (`name.casefold()`), used for search.
- **One active person per identity; many identities per person**: a partial unique index `uq_identity_person_active`
  (`... WHERE state = 'ACTIVE'`) enforces it. A check says `ended_at` is set exactly when the association is not `ACTIVE`.
- **Reassigning** ends the old association (`REMOVED` or `SUPERSEDED`) and creates a new one, each with evidence
  (`IDENTITY_ASSIGNED_TO_PERSON`, `IDENTITY_REMOVED_FROM_PERSON`). **Renaming** changes only the person's name and revision (`PERSON_RENAMED`
  evidence); no identity is touched.

## 4. Try it

**Works with no models. Verified 2026-10-12.** Name an identity ([people routes](../api/routes/people.md): `POST /api/v1/people` with
`display_name` and `identity_id`), stop the backend, and query the practice library:

```bash
uv run python q.py ~/faceidentify-play/lib "select display_name, normalized_name, state, revision from people" "select state, revision, ended_at is null from identity_person_associations" "select kind, count(*) from evidence group by 1"
```

Observed: `('Ada Example', 'ada example', 'ACTIVE', 1)`, one association `('ACTIVE', 1, 1)`, and a new evidence kind
`('IDENTITY_ASSIGNED_TO_PERSON', 1)`. Naming an already-named identity again returns the refusal described above (tests:
`uv run pytest tests/integration/test_person_use_cases.py -q`).

## 5. Change it

A new check on names (for example a maximum length) belongs in `name_identity` and `rename_person`, with its test in
`test_person_use_cases.py` first; it is a behaviour and API change, so also update the OpenAPI contract ([contract lesson](../api/03-openapi-and-contract.md)).

## 6. Break it on purpose

In a copy of the database, insert a second `ACTIVE` association for the same identity: the partial unique index refuses it.
Rename with a wrong `expected_revision`: the route returns a conflict and the name is unchanged.

## 7. Exercises

1. How does a person come to exist?
2. Why is `normalized_name` stored?
3. What happens to the old link when an identity is reassigned?
4. Does renaming a person change any identity row?

**Answers**

1. By naming an identity (`name_identity`).
2. Case-insensitive search and sorting.
3. It ends (`ended_at` set) and a new association is created; both keep their evidence.
4. No.

## 8. Related files

- Previous: [04](04-identities-and-lineage.md) · Next: [06 Occurrences and evidence](06-occurrences-and-evidence.md)
- [`backend/app/people/use_cases.py`](../../../../../backend/app/people/use_cases.py)
