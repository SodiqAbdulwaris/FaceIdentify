# Routes: search by name and history (`backend/api/routes/search.py`)

## 1. What this is and why it exists

"Where is Ada?" and "which picture was called beach?" are questions the library should answer without anyone
running a model. `GET /search?q=` looks a word up in four places at once (people, unnamed identities, pictures,
and the appearances of the people and identities found) and returns each kind in its own list. It reads only what is
authoritative and active, writes nothing, and needs no vector index: these are plain SQLite lookups. Searching by a
*picture* is a different route ([face search](face-search.md)).

## 2. Where it lives

- Route: `GET /api/v1/search` in `backend/api/routes/search.py`.
- Specs: `docs/specs/API and Contracts.md` section 12.1, `docs/specs/universal-search-and-retrieval-architecture-v1.md`.
- Tests: `tests/integration/test_api_search.py`; the screen: `frontend/src/features/search/SearchPage.tsx`.
- Plan step: M5 step 5a (`docs/implementations/2026-10-09-m5-search-people-and-history.md`).

## 3. How it works

Query parameters:

| Parameter | Meaning |
|---|---|
| `q` | required, 1 to 200 characters; trimmed, whitespace collapsed, matched case-insensitively **as a whole** |
| `recycled` | `exclude` (**the default**), `include`, or `only`: pictures in the recycle bin |
| `types` | comma list of `people,identities,sources,occurrences` (default all four); anything else is `422 INVALID_SEARCH` |
| `limit` | 1 to 50, default 20 |

The answer:

```json
{"query": "ada",
 "results": {"people": [{"id": "...", "display_name": "Ada Example", "match": "PREFIX", "identity_ids": ["..."],
                          "occurrence_count": 2, "source_count": 2, "visual_support": true,
                          "biometric_memory_forgotten": false}],
             "identities": [], "sources": [], "occurrences": [ ...OccurrenceSummary... ]},
 "coverage": {"sources": 3, "processed": 3, "not_processed": 0},
 "ranking": {"plan": "NAME_LOOKUP", "ranker": "rule-v1", "recycled": "exclude",
             "types": ["people", "identities", "sources", "occurrences"]}}
```

- **Ranking is a plain rule within each type**: exact name, then prefix, then contains (`match`: `EXACT`, `PREFIX`,
  `CONTAINS`); the types are *never fused* into one score (spec section 5).
- **Unnamed identities** are found by their label `Person ABC123` (the display label of the first six hex characters).
- **`coverage`** says how much the search could see: unprocessed pictures have no faces to find.
- **Forgotten people** stay findable by name, labelled `biometric_memory_forgotten: true` with `visual_support: false`
  (owner decision 2026-10-09): the name is kept, the faces are gone.
- Pictures being or already permanently deleted never appear. Nothing is written; a search is not an ingest.

Note: the module docstring says "`include`, the default"; the **code** default is `exclude` (and the screen's
"Include recycled images" checkbox sends `include`). The code is what the lesson reports; the docstring is stale.

## 4. Try it

**Works with no models. Verified 2026-10-12** (variables as in [call the API](../01-call-the-api.md); a named person "Ada Example"
and a few pictures).

```bash
curl -s -H "$H" "$B/api/v1/search?q=ada" | j "[(p['display_name'], p['match'], p['occurrence_count'], p['source_count']) for p in d['results']['people']]"
curl -s -H "$H" "$B/api/v1/search?q=RED&types=sources" | j "([(s['display_name'], s['match']) for s in d['results']['sources']], d['ranking']['types'])"
curl -s -H "$H" -G --data-urlencode "q=Person 1BF5E2" "$B/api/v1/search" | j "[(i['label'], i['match'], i['occurrence_count']) for i in d['results']['identities']]"
for r in exclude include only; do curl -s -H "$H" "$B/api/v1/search?q=blue&types=sources&recycled=$r" | j "[(s['display_name'], s['source_recycled']) for s in d['results']['sources']]"; done
```

Observed: `[('Ada Example', 'PREFIX', 2, 2)]` with `coverage {'sources': 3, 'processed': 3, 'not_processed': 0}`;
`[('red', 'EXACT'), ('red again', 'PREFIX'), ('red-copy', 'PREFIX')]` and `['sources']` (best match first, then the others
by name order); `[('Person 1BF5E2', 'EXACT', 1)]` (an unnamed identity found by its label; use your own identity's six
characters); and, for a picture named `blue` that was recycled, `exclude: []`, `include: [('blue', True)]`,
`only: [('blue', True)]`. Errors: `types=nope` gives `422 INVALID_SEARCH` with `"details": {"types": [...]}`; an empty `q` gives
`422 VALIDATION_ERROR` (`string_too_short`).

## 5. Change it

Run on 2026-10-12: change the default `recycled: Recycled = "exclude"` to `"include"` and run
`tests/integration/test_api_search.py`: it fails at `test_people_are_found_by_name_best_match_first_with_their_appearances`.
That test pins the default, and the stale docstring above is exactly the kind of drift such a pin catches in the other
direction (a future change to the docstring alone would not be noticed by any test). Restore the file. To add a new
searchable field you also decide its rank rule and add it to `coverage`/`ranking` honestly; the spec (section 7: say how
the query was planned and how much of the library could be seen) says what a result must report.

## 6. Break it on purpose

Search for a picture you recycled without `recycled=include`: empty list, no error (a hard constraint on where the
picture lives). Search for something in an unprocessed library: `coverage.not_processed` is greater than zero, which is
the route's way of saying "no result does not mean no such person". Pass `limit=100`: `422` (maximum 50).

## 7. Exercises

1. Which `recycled` value is the default and where does the screen change it?
2. In what order are people ranked, and are people and pictures ranked against each other?
3. How is an unnamed identity found?
4. What does a forgotten person look like in the results?

**Answers**

1. `exclude`; the "Include recycled images" checkbox sends `include`.
2. Exact, then prefix, then contains, within each type; no, the types are separate lists and are never fused.
3. By its label `Person` plus the first six hex characters of its id.
4. Still listed by name, with `biometric_memory_forgotten: true` and `visual_support: false`.

## 8. Related files

- Previous: [identity changes](identity-changes.md) · Next: [face search](face-search.md) · [Routes index](README.md)
- [`docs/specs/universal-search-and-retrieval-architecture-v1.md`](../../../../../specs/universal-search-and-retrieval-architecture-v1.md)
- [Library and search screens](../../../04-frontend/08-people-and-search-screens.md)
- [`backend/api/routes/search.py`](../../../../../../backend/api/routes/search.py)
