# M5 step 4c (part 2): forget an identity and forget a person

- **Date:** 2026-10-09
- **Milestone / tracker IDs:** M5 step 4c; TST-059, SEC-006
- **Status:** done; historical and name search (5a) follows
- **Commits:** PR to be recorded when merged

## What changed

- **Use case** `backend/app/identities/forget.py` (`ForgetIdentityUseCase`), the only operation that
  removes biometric memory while the media stays (identity model section 46-49; API section 8.3 and
  116). Authoritative forgetting first, physical cleanup second:
  1. *One transaction*: the identity becomes `FORGOTTEN` (`forgotten_at`, no representative face), its
     Person link ends (the existing `IDENTITY_REMOVED_FROM_PERSON` entry), its occurrences stop being
     authoritative (`DELETED`), every representation it owns (including a `DELETED`-state one, which
     keeps its vector) is queued for erasure and so is out of retrieval from that commit on, and an
     `IDENTITY_FORGOTTEN` Evidence entry records the ids (no names, no vectors).
  2. *Erasure* through `RepresentationEraser`: the row, every index file and the log. A crash or a
     locked file leaves the representations `ERASING`; startup recovery and a repeat of the request
     finish them, and an owed log truncation is settled by a repeat too.
- **Forget person** = the same use case on each identity of a Person. The Person, their name and their
  notes stay, without visual support.
- **Routes.** `POST /api/v1/identities/{id}/forget` (body `{expected_revision}`; a changed identity is
  `409 IDENTITY_CHANGED`, an unknown or not-active one `404 IDENTITY_NOT_FOUND`) and
  `POST /api/v1/people/{id}/forget` (`404 PERSON_NOT_FOUND`). Both answer `204` when every vector is
  gone, or `202` with `{outstanding: [...]}`, in which case recovery is marked degraded in
  `/readiness`; the identity is already forgotten either way. A repeat is harmless and announces
  nothing; a change is announced as `identity.updated`.
- `RepresentationEraser.queue_in` (new; it also takes `DELETED`-state representations, whose old ordinary
  `REMOVE` is forgotten so erasure applies its own by a rebuild) is shared with permanent Source
  deletion, which lost its own copy of that logic.
- **Front end.** The person page has "Forget how X looks" and, for a named person, "Forget every face
  of X", each with an in-place confirmation that says what goes and what stays; focus goes to the safe
  answer, Escape returns it; a refusal is shown; on success the page's cache is dropped and the people
  list opens with a warning if cleanup is still owed. The shared real-library story for the tests moved
  to `tests/fixtures/story.py`.

## Changes after the independent review

The review found real defects; all were fixed:

- **Merged-away identities.** A merge moves only the active vectors, so superseded, pending and deleted
  ones stayed on the predecessors. A forget now covers the identity and every identity merged into it,
  directly or through others (their lineage tombstones stay).
- **One transaction, one erasure for a Person.** "Forget person" validates the Person (active) and the
  links, forgets every identity and queues all their vectors in a single write, then drives one
  consolidated erasure (one rebuild per space). An identity reassigned to someone else is left alone. A
  retry finds the owed work through the forgotten identities (the links are gone by then) and never
  reports `204` while cleanup is owed.
- **Face crops.** Their deletion intent is part of the forget transaction and their bytes go afterwards
  (reported as outstanding, retried by a repeat and by startup recovery of artifacts).
- **Revisions.** Accepting a face into an identity, and assigning or removing its Person, now bump the
  identity's revision, so a stale forget (or merge or split) is refused with `409 IDENTITY_CHANGED`.
- **Front end.** A whole-person forget scrubs every cached identity and face list; the warning no
  longer promises suppression (the app treats the person as someone new if seen again) and says other
  remembered faces of a named person are kept for the narrower scope; focus goes back to the button
  that opened the question; and the People screen lists a named person without any remembered face
  ("Known by name only").

A second round of review found more, also fixed: a crop whose write was still `PENDING` or already
`DELETING` is finished too, and a leftover half-written copy is removed (and reported if locked); a crop
that a face of another identity still shows is kept; every query and update over an identity's family
is bounded (a test lowers SQLite's variable limit); the identity list is dropped from the cache with
the identities; the People screen fetches every page of named people and refreshes with every
person or identity change; and the narrow forget no longer promises that a later appearance counts as
new (the retained faces can still recognise the person).

Not changed: the People screen decides "no remembered face" from the Person's identity count. A named
identity kept after its last image was deleted (permanent delete keeps named people) still counts as one,
and shows its page without appearances; marking such a person as "recognition unavailable" needs a
visual-support figure the API does not carry yet (a follow-up with search, step 5a).

## Agent designs awaiting the owner (recorded, not blocking)

- The route for "forget person" (`POST /people/{id}/forget`) is not in the API spec; section 8.3 names
  only the identity route. Its answers follow the identity route.
- Occurrences of a forgotten identity become `DELETED` (they "no longer resolve to the forgotten Person",
  section 46) while the observations and the media stay. The faces therefore vanish from the image's
  face list; they are not offered as unplaced faces, because their vectors are gone.
- A Person with no identity left appears on the People screen under "Known by name only"; a page
  for them, and name search (step 5a), come later.

## Tests

- `tests/integration/test_forget_identity.py` (32), on a real library (SQLite, USearch, files,
  restarts): the vector's bytes are found in no database file, log or index file afterwards, the other
  identity's still are; the media and the face boxes stay; a named person keeps their name and loses
  the link; forgetting a person forgets each identity and nothing else; stale views, unknown ids and
  not-active identities are refused without erasing anything; a repeat changes nothing; a later image of
  the same face is not matched to the forgotten identity, also after the index is deleted and rebuilt
  and after a restart; a crash after the forget leaves nothing recognizable and the next start (or a
  repeat) finishes it; an owed log truncation is reported and settled by a repeat; a `DELETED`-state
  representation with an old applied `REMOVE` still loses its vector.
- `tests/integration/test_api_forget.py` (4): the routes, their answers, the events, the views, `202`
  with degraded readiness.
- Backend mutations: 17 guards and statements broken one at a time; the only survivors were a redundant
  guard (removed) and one closed by a new assertion. Front end (11 new, 172 total): ask first,
  cancel, focus and Escape, both scopes, the unnamed case, the warning carried to the people list, a
  refusal, dropping the cache; 10 mutations, one equivalent.

## Verification

- Backend gate and front-end checks: see the PR.

## Open issues / follow-ups

- Historical and name search (5a) must treat forgotten identities as gone and find a Person without
  any identity by name.
