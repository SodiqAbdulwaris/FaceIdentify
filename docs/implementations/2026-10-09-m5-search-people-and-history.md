# M5 step 5a: historical and name search

- **Date:** 2026-10-09
- **Milestone / tracker IDs:** M5 step 5a; TST-055
- **Status:** done; face search (5b) follows
- **Commits:** PR to be recorded when merged

## What changed

- **Route** `GET /api/v1/search` (`backend/api/routes/search.py`), read-only, over authoritative data
  (SQLite) only. No index is used and nothing is written: a query is not an ingest. Parameters: `q` (1 to
  200 characters, case- and spacing-insensitive), `recycled` (`include` the default, `exclude`, `only`),
  `types` (comma list of `people`, `identities`, `sources`, `occurrences`) and `limit` (1 to 50, default
  20). A bad `types` or an empty word is `422 INVALID_SEARCH`.
- **What is found.** People by name (exact, then prefix, then contains); unnamed identities by their
  label (`Person A1B2C3`) or the start of their id; images by file name; and the appearances
  (occurrences) of the people and identities found. Results are ranked inside each kind by that plain
  rule and never fused into one score (search spec section 5).
- **Each answer says how it was made:** `ranking` (`plan: NAME_LOOKUP`, `ranker: rule-v1`, the filters)
  and `coverage` (how many images were looked through and how many were never processed, so have no
  faces to find; spec section 7).
- **Relationships stay authoritative.** A named person's count follows the faces their identities
  currently hold, so a merge, a rename, a split, a recycle, a restore, a permanent delete and a forget
  all change what is found. A person with no visible face is still found by name with
  `visual_support: false` (their faces were forgotten or their images deleted); the screen says they
  cannot be recognised.
- **Front end.** A Search screen (`#/search?q=`, kept in the address so reload and back work): a word,
  a place (everywhere, not in the Recycle bin, only the Recycle bin), results grouped as People, Not yet
  named, Images and Where they appear, each linking to its page, with the coverage line. Any event that
  changes a name, a face or an image refreshes an open search.

## Agent designs awaiting the owner (recorded, not blocking)

The search spec leaves these open (its section 11), so they were chosen here:

- `recycled=include` is the default and marks recycled images (the owner's M5 plan, step 5:
  "recycled-source Occurrences stay in historical views and search"); the identity model section 39 says
  a normal search excludes recycled media, which the `exclude` filter gives on request. Images being or
  already permanently deleted never appear, tombstone included.
- No fused "top result" list and no aliases (none exist). Lower-casing for file names is the database's,
  so it is ASCII-only for them; names use full case folding.
- Face search (5b) is a separate route (`POST /search/face`), not part of this one.

## Tests

- `tests/integration/test_api_search.py` (11), on a real library with planted perception: ranking
  exact, prefix, contains; kinds and limit; label and file-name lookup; a named person is not listed as
  unnamed; merge then rename; recycled marked, excluded, only, and restored; permanent delete and forget
  (the person stays findable, without visual support); coverage; searching writes nothing.
- `frontend/src/features/search/SearchPage.test.tsx` (5) and the invalidation test.
