# Front end 06 Events and routing

## 1. What this is and why it exists

Two things move you around: the **event client** keeps screens fresh without reloading, and the **router** decides which screen an
address shows. The central idea for events is the same as on the backend: *an event is only a hint to refetch*, so nothing can show
wrong data for long even if events are lost.

## 2. Where it lives

| Thing | Where |
|---|---|
| WebSocket client, reconnect, gap detection | `frontend/src/api/events.ts` (`EventsClient`, `retryDelay`, `parseEnvelope`) |
| What an event makes stale | `frontend/src/api/invalidation.ts` (`staleBecauseOf`) |
| Wiring into the app | `frontend/src/app/EventsBridge.tsx` |
| Routes | `frontend/src/app/routes.tsx` (hash router) |
| Tests | `events.test.ts` (264 lines), `invalidation.test.ts`, `Layout.test.tsx` |

## 3. How it works

**The client** (`EventsClient`):

- Opens `events_url` with two sub-protocols, `faceidentify.v1` and `fi.<token>` (a browser cannot set a header on a WebSocket;
  [events, backend side](../03-backend/architecture/07-events.md)).
- Checks each message is a version-1 envelope (`parseEnvelope`); anything else is ignored.
- `system.hello` sets the baseline sequence. A **repeat** (`sequence <= last`) is ignored; a **gap** (`sequence > last + 1`) calls
  `onResync`. Opening (and reopening) also calls `onResync`, covering whatever changed before the connection existed.
- A lost connection retries with growing delay: `retryDelay(n) = min(500 ms * 2^n, 15 s)`, status "reconnecting".
- `start` and `stop` release the socket and its handlers so nothing late reaches a dead client.

**The bridge** (`EventsBridge`): for each event, `staleBecauseOf(event)` lists query keys and the cache **invalidates** them (the
visible ones refetch); `onResync` invalidates everything. Mapping, in words: `source.*` refreshes sources and that source and
people and search; `processing_run.*` refreshes that run, the runs list, the source, identities, people and search; `person.*`,
`occurrence.*` and `identity.*` refresh identities, people, every open person page, sources and search. **An unmapped type makes
nothing stale**: a new event needs a new mapping.

**Polling as a fallback**: while a run is active the source and processing screens refetch every 3 s (`ACTIVE_REFETCH_MS`), for
when the live connection is down.

**The router**: `createHashRouter`, addresses like `#/library/source/<id>`. Hash routing because the app is served from a custom
protocol where a reload on a deep path would ask for a file that does not exist. Routes: `/` redirects to `/library`;
`library`, `library/source/:sourceId`, `identities`, `identities/:identityId`, `search`, `processing/:runId`, all inside
`Layout`. `useParams` reads `:sourceId`; `useSearchParams` keeps the search word in the address (`#/search?q=...`) so reload and
Back work; `Link` and `NavLink` navigate; `state` on navigation carries a one-time notice ("this image was deleted").

## 4. Try it

**Works with no models and no shell. Verified 2026-10-12.**

```bash
npm run test --workspace frontend -- src/api/events.test.ts src/api/invalidation.test.ts
```

Expected: `Tests  20 passed (20)` (observed). The 14 names in `events.test.ts` include `delivers events after the greeting, in order, and ignores a repeat`,
`asks for a refetch when the numbering skips (an event was lost)`, `reconnects with a growing delay, restarts from a new greeting, and resets after success`
and `after stopping, nothing the old socket still delivers reaches the handlers`; `invalidation.test.ts` has six, among them
`an event it does not know makes nothing stale` and `the keys it names are prefixes of the keys the screens read`. With a real backend, the same behaviour is visible without the UI by running the Python listener in
[call the API](../03-backend/api/01-call-the-api.md) ("Listen to events") while you process a picture.

## 5. Change it

A new backend event type (`thing.updated`) means adding a prefix to `staleBecauseOf`, with a test in `invalidation.test.ts`
saying which keys it makes stale. A new screen means a route in `routes.tsx` and a link in `Layout.tsx`.

## 6. Break it on purpose

Remove the `identity.` prefix from the last condition in `staleBecauseOf` (scratch edit) and run `invalidation.test.ts`: observed
`1 failed | 5 passed`, the failing test being `a person, a corrected face or a changed identity makes every screen that shows a name stale`
(`expected [] to deeply equal [ Array(5) ]`). In the real app a changed identity in one window would not refresh the other until
the next resync. Restore with `git restore frontend/src/api/invalidation.ts`.

## 7. Exercises

1. What does the client do on a gap in sequence numbers?
2. Why hash routing?
3. What happens when a brand-new event type arrives that `staleBecauseOf` does not know?

**Answers**

1. Calls `onResync`, so everything on screen refetches.
2. A reload on a deep path would otherwise ask the protocol handler for a non-existent file.
3. Nothing becomes stale; the screen refreshes only on its next refetch trigger.

## 8. Related files

- Previous: [05](05-api-client-and-queries.md) · Next: [07 Library and source screens](07-library-and-source-screens.md)
- [`frontend/src/api/events.ts`](../../../../frontend/src/api/events.ts), [`invalidation.ts`](../../../../frontend/src/api/invalidation.ts)
