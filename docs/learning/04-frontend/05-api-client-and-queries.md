# Front end 05 The API client and queries

## 1. What this is and why it exists

Every screen needs server data, and every request needs the token and the same error handling. So there are **three thin layers**:
`ApiClient` (HTTP plus the token and one error type), `endpoints` (one named function per backend operation, typed by the
generated schema), and **TanStack Query** (caching, loading flags and refetching, keyed by `keys`). A screen never calls `fetch`.

## 2. Where it lives

| Layer | File |
|---|---|
| HTTP client, `ApiError`, `get`/`post`/`patch`/`upload`/`command`/`delete`/`blob` | `frontend/src/api/client.ts` |
| One function per operation (about 30) | `frontend/src/api/endpoints.ts` |
| Query keys | `frontend/src/api/keys.ts` |
| Types | `types.ts`, `schema.d.ts` |
| Tests | `client.test.ts` (6) and each screen's test |

## 3. How it works

- **`ApiClient`** adds `Authorization: Bearer <token>` to every request. A network failure becomes
  `ApiError(0, 'NETWORK_ERROR', retryable)`. A failed response becomes an `ApiError` carrying the backend's own `code`, `message`,
  `details` and `retryable` from the one error envelope ([API conventions](../03-backend/api/README.md)); a body that is not that
  envelope becomes `HTTP_ERROR`. Screens show `error.message` (`errorMessage()` in `library/messages.ts`) and never a stack.
- **Kinds of call**: `get` (JSON), `post`/`patch` (JSON body), `upload` (a file's own bytes, for face search),
  `command` (returns `{status, body}` so a `204` and a `202` can be told apart: delete, forget), `delete` (204), `blob`
  (a file, for pictures).
- **Why pictures use `blob`**: `<img src>` cannot send the token, so `useSourceImage` fetches the bytes with `api.blob`, wraps them
  in an object URL and revokes it on cleanup. Original bytes never change, so the query is kept (`staleTime: Infinity`).
- **`endpoints(api)`** returns an object of arrow functions: `listSources(cursor, state)`, `processSource(id)`, `mergeIdentities(loser, survivor)`...
  Revisions are passed *from the objects the screen holds* (`identity.revision`), which is how optimistic concurrency reaches the UI.
- **Cursor pagination**: `useInfiniteQuery` with `getNextPageParam: page => page.page.next_cursor ?? undefined` and a "Load more" button.
- **Query keys** (`keys.ts`) are the single list of names for cached data: `keys.source(id)`, `keys.identities`... Events invalidate
  by key, so **what a screen reads and what an event refreshes cannot drift apart** (a comment in the file says so). Keys nest:
  `['source', id, 'runs']` is under `['source', id]`, so invalidating the parent refreshes the children.
- **Mutations** (`useMutation`) run an action then `invalidateQueries` for what they changed (`useRunActions.ts`), without waiting
  for the event.
- **Defaults**: `staleTime` 5 s, no refetch on window focus (`App.tsx`).

## 4. Try it

**Works with no models. Verified 2026-10-12.**

```bash
npm run test --workspace frontend -- src/api/client.test.ts
```

Observed: `Tests  6 passed (6)`. Read them: the token on every request, the error envelope becoming `ApiError`, a network
failure, a non-envelope error. Then list the operations: `grep -c "api\." frontend/src/api/endpoints.ts`, and match any three
to their backend routes in the [route map](../03-backend/api/README.md).

## 5. Change it

To use a new backend route: add a function to `endpoints.ts` returning `api.get<Type>(...)`, add a key to `keys.ts`, use `useQuery`
in the screen, and add a handler to the screen's test ([add a screen](10-add-a-screen.md)). The type comes from the regenerated schema.

## 6. Break it on purpose

Remove the `Authorization` header line in `client.ts` (scratch edit): `client.test.ts` fails on the first test, and a real backend
would answer `401` to everything. Restore with `git restore`.

## 7. Exercises

1. What is the difference between `command` and `post`?
2. Why are query keys in one file?
3. Why does `mergeIdentities` take whole identity objects?

**Answers**

1. `command` returns the status with the body so `204` (no body) and `202` (work still owed) can be distinguished.
2. So events and screens refer to cached data by the same names.
3. It sends each identity's current revision, so a changed identity is refused as stale.

## 8. Related files

- Previous: [04](04-app-structure-and-gate.md) · Next: [06 Events and routing](06-events-and-routing.md)
- [`frontend/src/api/client.ts`](../../../frontend/src/api/client.ts), [`endpoints.ts`](../../../frontend/src/api/endpoints.ts)
