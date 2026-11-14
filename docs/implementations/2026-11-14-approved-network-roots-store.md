# Approved network roots: the store and its API (issue #174, PR A)

- **Date:** 2026-11-14
- **Milestone / tracker IDs:** issue #174 (second part, step A of [the plan](../plans/NETWORK_ROOTS_PLAN.md)); TST-056
- **Status:** partial: the approvals can be listed, added and revoked; nothing reads them yet (PR B)
- **Commits:** PR (number recorded when merged): `feat(search): store and serve approved network roots`

## Audit of the code before this change

Built (PR 212, [entry](2026-10-16-face-search-network-paths.md)): `local_target`/`open_local` in
`backend/infrastructure/storage/local_path.py` walk a path one component at a time without contacting
anything and refuse every UNC, device, non-local drive, unknown reparse point and link to a share;
`face_search._read_query` answers `400 QUERY_PATH_NOT_LOCAL`. Missing, and all named by the issue:

1. no way to approve a network root (this PR);
2. no policy that lets an approved target through: the walk refuses it (PR B);
3. a residual race between the walk and the open, and no check that the opened thing is a regular file
   (PR B);
4. no bounded read: a slow or hung share would block a thread and could not be abandoned (PR C);
5. no screen (PR D).

Existing mechanisms looked at for the store: the `app_state` table and the singleton settings rows
live in the library database; the recognition policy is a machine-local file written atomically.

## What changed

- `backend/app/runtime/network_roots.py`: `NetworkRoots` (the list, `add`, `revoke`, `approves`) and
  `unc_parts`, the one place a UNC text becomes components. Accepts `\\server\share[\folder...]`,
  `//server/share` and the `\\?\UNC\` form as the same root; refuses device namespaces
  (`\\.\`, `\\?\GLOBALROOT`, a volume), a drive path, a missing share, `..`, empty parts, a trailing
  dot or space, wildcards, streams, reserved device names, control characters and a WebDAV host
  (`server@SSL`, `server@8080`). A root is compared upper-cased component by component: `share2` is
  not inside `share`. Text only; nothing is opened or resolved.
- Storage: `<local state root>/network-roots.json`, replaced atomically. A file that cannot be read,
  or an entry that would be refused if it were added, approves nothing (default deny).
  Ids are a digest of the root's key, so approving the same root twice keeps one entry and the first
  approval time.
- `backend/api/routes/network_roots.py`: `GET`, `POST` (`201`), `DELETE /{id}` (`204`) on
  `/api/v1/settings/network-roots`; `400 NETWORK_ROOT_INVALID` (the message never echoes the text),
  `404 NETWORK_ROOT_NOT_FOUND`. API spec section 5.10 and the generated OpenAPI and TypeScript types.
- Tests: `tests/unit/test_network_roots.py` and `tests/integration/test_api_network_roots.py`, with a
  guard that fails any socket or name lookup and any `stat` of a network path while approving and
  comparing. Both new modules have 100% line and branch coverage.

## Review (independent read-only subagent, Codex being out of usage until 21:45) and answers

All ten points were addressed in the second round of commits:

1. *Lock per request, shared temp name (high):* one process-wide lock; each write uses a unique
   `mkstemp` file, `fsync`, then `os.replace`; a failed write removes its partial. Test with 24
   approvals through separate instances on 8 threads. Two processes are not covered (one backend
   owns a local state root; recorded as a `ponytail:` comment).
2. *Unreadable file turned into an overwrite (medium):* a missing file is empty; an unreadable or
   untrusted one raises `NetworkRootsUnreadableError`, `add`/`revoke` write nothing, the API answers
   `503 NETWORK_ROOTS_UNREADABLE`, `approves` still denies.
3. *`approved_at` not validated, duplicates (low):* validated as text; duplicates collapse by id.
4. *Lone surrogate (low):* refused as an unsafe character.
5. *Leading separators and extended forms that hide a device (medium):* a third separator, `.` or
   `?` right after the two leading ones is refused; callers must open the canonical rebuilt path,
   never the text they were given.
6. *`DavWWWRoot` (medium):* refused, with the `server@SSL` forms.
7. *Administrative shares (medium to low):* a share name ending in `$` is refused (`C$` through the
   network redirector would sidestep the local walk's reparse refusals; `IPC$` reaches pipes).
8. *Case folding wider than NTFS (low):* ASCII-only fold; non-ASCII names compare exactly.
9. *For PR B:* 8.3 short names, server-side links inside an approved share, and a server name that
   resolves to an unexpected address cannot be seen by text comparison; PR B decides on the resolved
   target and the opened handle's final path.
10. Spec gaps (`422`, `DavWWWRoot`) and the weak "does not echo" assertion are fixed; the guard now
    also covers `lstat` and `scandir` on network paths.

## Decisions

- Machine-local file, not the library database (see the plan), delegated to the agent by the owner's
  brief of 2026-11-14 ("do not invent a new store if one fits"): none of the database stores is
  machine-local, and the policy file is the existing machine-local precedent.
- No IP-literal or hostname policy: approving `\\127.0.0.1\share` is allowed (the loopback test
  route); the user names what they trust.
- No credentials anywhere: the entry holds the name and the approval time only.

## Verification

- `uv run pytest -q tests/unit/test_network_roots.py tests/integration/test_api_network_roots.py
  tests/contracts`: all pass; ruff, ruff format and mypy clean; `npm run generate:api` leaves the
  committed contract in sync. Full gate: see the PR.

## Open issues / follow-ups

- PRs B, C and D. #174 stays open; this entry does not close it.
