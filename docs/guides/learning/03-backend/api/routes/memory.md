# Routes: memory (`backend/api/routes/memory.py`)

## 1. What this is and why it exists

After processing, the library "remembers" people. This module is the **read-only window** on that memory:
the list of **identities** (one visual subject each), one identity, and the **occurrences** (appearances: "this
identity is in this picture") of a source or of an identity. It never changes anything. Its most important property is
what it leaves out: it shows only **authoritative** data (`ACTIVE`), so the private output of a run still in
progress, merged-away identities and forgotten ones never appear.

## 2. Where it lives

| Route | Notes |
|---|---|
| `GET /api/v1/identities` | active identities, newest first, with counts |
| `GET /api/v1/identities/{id}` | one active identity; `404 IDENTITY_NOT_FOUND` otherwise |
| `GET /api/v1/sources/{id}/occurrences` | the faces found in one picture |
| `GET /api/v1/identities/{id}/occurrences` | where one identity appears |

The shaping helpers (`occurrence_summaries`, `identity_summaries`, `person_references`) are imported by other
route modules (`corrections.py`, `search.py`, `face_search.py`), so changing them changes several routes. Tables:
`identities`, `occurrences`, `observations`, `people` (`backend/app/identities/models.py`, `memory/models.py`,
`people/models.py`). Tests: `tests/integration/test_api_memory.py`, `test_api_source_lifecycle.py`.

## 3. How it works

### `IdentitySummary`

```json
{"id": "fb95a2d4-...", "state": "ACTIVE", "revision": 3, "person": null,
 "representative_observation": {"id": "66029483-...", "source_id": "bbc132a7-...",
   "bounding_box": {"x": 0.2, "y": 0.2, "width": 0.6, "height": 0.6}, "face_crop": null},
 "occurrence_count": 1, "source_count": 1, "created_at": "...", "activated_at": "..."}
```

- `person` is `{id, display_name, revision}` once someone named it, else `null`; an unnamed identity is displayed as
  `Person {SHORT_ID}` (the uppercase first six hex characters of its id: presentation only, never stored).
- `revision` is what you send back as `expected_revision` in merge, split and forget.
- `bounding_box` is **normalised** (fractions of the picture, 0 to 1). `face_crop` is `null`: no crops are generated yet;
  the screen draws a face by cropping the original with the box.
- `occurrence_count` counts active occurrences; `source_count` the distinct pictures.

### `OccurrenceSummary`

`id, source_id, source_display_name, identity_id, kind ("IMAGE"), representative_observation, person, source_recycled,
created_at`. `source_recycled` is true when the picture is in the recycle bin: its faces **stay** in memory and counts,
marked (owner decision 2026-10-07).

Both lists page with `limit`/`cursor` like every collection (identities newest first; the screen asks occurrences
with `limit=200`).

## 4. Try it

**Works with no models. Verified 2026-10-12** (variables as in [call the API](../01-call-the-api.md)).

```bash
curl -s -H "$H" $B/api/v1/identities | j "[(i['id'][:6], i['state'], i['occurrence_count'], i['source_count']) for i in d['items']]"
ID=$(curl -s -H "$H" $B/api/v1/identities | j "d['items'][0]['id']")
curl -s -H "$H" "$B/api/v1/identities/$ID/occurrences?limit=2" | j "([(o['source_display_name'], o['source_recycled']) for o in d['items']], d['page']['has_more'])"
OCC=$(curl -s -H "$H" "$B/api/v1/identities/$ID/occurrences?limit=1" | j "d['items'][0]['id']")
SRC=$(curl -s -H "$H" "$B/api/v1/identities/$ID/occurrences?limit=1" | j "d['items'][0]['source_id']")
curl -s -H "$H" $B/api/v1/sources/$SRC/occurrences | j "len(d['items'])"
```

Observed shapes: a list of `(short id, 'ACTIVE', occurrences, sources)` tuples; `([('red', False), ('red', False)], True)`
(two items on this page, more to come, none of the pictures recycled); `1` face in that picture. A forgotten, merged or
deleted identity is `404 IDENTITY_NOT_FOUND` (observed after a forget).

## 5. Change it

The guarantee to protect is "only authoritative data is shown". Run on 2026-10-12: in `list_identities` remove the
state filter (`query = select(Identity).where(Identity.state == IdentityState.ACTIVE)` to `select(Identity)`) and run
`tests/integration/test_api_memory.py`: `test_private_output_is_never_shown` fails. Separately, change
`source_recycled=source.state == SourceState.RECYCLED` to `source_recycled=False` and run
`test_api_source_lifecycle.py`: `test_its_faces_stay_in_memory_counts_and_views_marked_as_recycled` fails (note that
`test_api_memory.py` alone does *not* catch this one: the recycled marker is pinned in the lifecycle tests). Restore
both files with `git restore`.

## 6. Break it on purpose

Ask for an identity id that is `MERGED` (the loser of a merge): `404 IDENTITY_NOT_FOUND`, the same as an id that never
existed. Look at a picture that was processed but whose run is still `RUNNING`: its occurrences list is empty until
acceptance, because everything before acceptance is `PENDING` and private.

## 7. Exercises

1. Why is `bounding_box` a fraction of the picture and not pixels?
2. What is shown for the name of an identity nobody has named?
3. What does `source_recycled: true` change about the face's presence in memory?
4. Which states of identity does this module never return?

**Answers**

1. A fraction works for any size of display or crop of the same picture; the screen multiplies by what it draws.
2. `person` is `null`; the screen builds `Person ABC123` from the id.
3. Nothing is removed: the face still counts and appears, only marked as coming from a recycled picture.
4. Everything but `ACTIVE`: `PENDING`, `MERGED`, `FORGOTTEN`, `DELETED`.

## 8. Related files

- Previous: [jobs](jobs.md) · Next: [people](people.md) · [Routes index](README.md)
- [Identities and lineage](../../domain/04-identities-and-lineage.md), [occurrences and evidence](../../domain/06-occurrences-and-evidence.md)
- [`backend/api/routes/memory.py`](../../../../../../backend/api/routes/memory.py)
