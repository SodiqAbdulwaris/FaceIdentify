# M5 step 5a: historical and name search

- **Date:** 2026-10-09
- **Milestone / tracker IDs:** M5 step 5a; TST-055
- **Status:** done; face search (5b) follows
- **Commits:** PR to be recorded when merged

## What changed

- **Route** `GET /api/v1/search` (`backend/api/routes/search.py`), read-only, over authoritative data
  (SQLite) only. No index is used and nothing is written: a query is not an ingest. Parameters: `q` (1 to
  200 characters, case- and spacing-insensitive), `recycled` (`exclude` the default, `include`, `only`),
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

- **Decided by the owner, 2026-10-09:** recycled images are excluded from search by default
  (`recycled=exclude`); `include` (the screen's "Include recycled images" box) adds them, marked as
  recycled, and `only` shows just those. A restored image is back in normal results at once. A person's
  page keeps showing the retained appearances from recycled images, marked: search and identity history are
  different views of the same data. Images being or already permanently deleted never appear.
- No fused "top result" list and no aliases (none exist). Lower-casing for file names is the database's,
  so it is ASCII-only for them; names use full case folding.
- **Decided by the owner, 2026-10-09:** a forgotten person stays findable by name and is labelled
  "Biometric memory forgotten" (`PersonHit.biometric_memory_forgotten`: one of their identities was
  forgotten and none remain). They take no part in recognition or face matching (the forget guarantees
  of step 4c: vectors erased, no match after a restart or an index rebuild). Deleting the Person record is
  a separate operation. The flag is read from durable rows only, so it survives a restart. A person whose
  images were all deleted is not labelled forgotten: they just have no visual support.
- Face search (5b) is a separate route (`POST /search/face`), not part of this one.

## Tests

- `tests/integration/test_api_search.py` (13), on a real library with planted perception: ranking
  exact, prefix, contains; kinds and limit; label and file-name lookup; a named person is not listed as
  unnamed; merge then rename; recycled marked, excluded, only, and restored; permanent delete and forget
  (the person stays findable, without visual support); coverage; searching writes nothing; states
  the API cannot reach; occurrences asked for alone; a limit cut in SQL; file names with repeated
  spaces and non-ASCII letters.
- `frontend/src/features/search/SearchPage.test.tsx` (6) and the invalidation test.

## Changes after the independent review

- A search no longer stays in the cache after a forget or a permanent delete (both scrub it); the box
  follows the address on Back; the layout reflows at narrow widths and large text.
- `types=occurrences` alone now works (the people and identities are looked up first, then only the asked-for groups
  are returned); people are ranked and limited in SQL; file names are matched with the query's own folding.
- The generated contract now lands in the same commit as the route.
- Not changed: see the open question above (forgotten people stay findable by name).

## Owner decisions applied (2026-10-09)

The two open questions were answered and built: recycled images are left out of search by default, and
forgotten people are found and labelled. Tests: `test_a_recycled_image_is_marked_and_can_be_filtered_out_or_asked_for`
(now checks the default), `test_a_forgotten_person_stays_findable_and_says_so`, and the Search screen tests for
the checkbox and the label.
