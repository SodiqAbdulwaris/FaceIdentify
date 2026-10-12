# Front end 10 Add a screen

## 1. What this is and why it exists

A worked recipe: add a small "Status" screen that shows what `/readiness` says. It touches every layer of the front end once (an
endpoint, a query key, a component, a route, a link, a test), so doing it once teaches the whole structure. It was **dry-run on
2026-10-12 and discarded** (documentation-only task); everything below was built, tested and removed with `git checkout`.

## 2. Where it lives

| Step | File |
|---|---|
| 1. The data | `endpoints.readiness` and `keys.readiness` already exist (`frontend/src/api/endpoints.ts`, `keys.ts`) |
| 2. The screen | new `frontend/src/features/status/StatusPage.tsx` |
| 3. The route | `frontend/src/app/routes.tsx` |
| 4. The link | `frontend/src/app/Layout.tsx` |
| 5. The test | new `frontend/src/features/status/StatusPage.test.tsx` |
| (A new backend route instead) | add the route, run `npm run generate:api`, then a function in `endpoints.ts` ([the contract lesson](../03-backend/api/03-openapi-and-contract.md)) |

## 3. How it works

**Step 2: the screen** (shape taken from `IdentitiesPage` and `SourcePage`: query, then loading, error and success blocks):

```tsx
import { useQuery } from '@tanstack/react-query'
import { keys } from '@/api/keys'
import { useBackend } from '@/app/useBackend'
import { errorMessage } from '../library/messages'

/** What the backend says about itself: its state and each capability. */
export function StatusPage() {
  const { endpoints } = useBackend()
  const readiness = useQuery({ queryKey: keys.readiness, queryFn: endpoints.readiness })

  return (
    <section className="flex flex-col gap-4">
      <h1 className="text-xl font-semibold">Status</h1>
      {readiness.isPending ? <p className="text-muted-foreground">Loading…</p> : null}
      {readiness.isError ? (
        <p role="alert" className="text-destructive">
          The status could not be loaded: {errorMessage(readiness.error)}
        </p>
      ) : null}
      {readiness.isSuccess ? (
        <>
          <p>
            The backend is <strong>{readiness.data.state}</strong>.
          </p>
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
            {Object.entries(readiness.data.capabilities ?? {}).map(([name, state]) => (
              <div key={name} className="contents">
                <dt className="text-muted-foreground">{name}</dt>
                <dd>{state}</dd>
              </div>
            ))}
          </dl>
        </>
      ) : null}
    </section>
  )
}
```

**Step 3: the route**, inside the `Layout` children of `routes.tsx`: add
`import { StatusPage } from '@/features/status/StatusPage'` and `{ path: 'status', element: <StatusPage /> },`.

**Step 4: the link**, in `Layout.tsx` after the Search link:

```tsx
<NavLink to="/status" className={link}>
  Status
</NavLink>
```

**Step 5: the test**, in the house style (the harness answers `/readiness`; any other request would be `unexpected`):

```tsx
import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { renderApp } from '@/test/harness'

describe('StatusPage', () => {
  it('shows the backend state and each capability', async () => {
    const { unexpected } = renderApp('/status', [
      {
        path: '/readiness',
        respond: { state: 'DEGRADED', capabilities: { database: 'READY', scheduler: 'DEGRADED' } },
      },
    ])

    expect(await screen.findByText('DEGRADED', { selector: 'strong' })).toBeInTheDocument()
    expect(screen.getByText('scheduler')).toBeInTheDocument()
    expect(unexpected).toEqual([])
  })
})
```

## 4. Try it

**Works with no models and no shell. Verified 2026-10-12** (then discarded). With the five steps in place:

```bash
npm run test --workspace frontend -- src/features/status
npm run typecheck
npm run lint -- --deny-warnings
npm test
```

Observed: the new test file and the existing `StatusBadge` tests (the path filter matches both) `15 passed`; typecheck clean; lint clean;
the full suite `195 passed` (193 plus two new). **A real mistake the first run caught:** the first version of the test used
`findByText('DEGRADED')` and failed with `Found multiple elements with the text: DEGRADED`, because the word appears twice on the
screen (the state and the `scheduler` capability). Narrowing the query (`{ selector: 'strong' }`) fixed it. Expect to meet this: queries
must match one thing.

To keep your own screen, commit it on a branch ([branches and commits](../01-basics/tools/05-git-and-pull-requests.md)); to discard a
practice one: `git checkout frontend/src/app` and delete the new folder.

## 5. Change it

A screen that needs a new backend route: the order is **backend route and its tests → `npm run generate:api` → endpoint function →
key → screen → route and link → tests**. A screen that changes after an event needs a line in `staleBecauseOf`
([events](06-events-and-routing.md)). A screen that deletes or changes something must send the revision it saw and show a message for
the conflict code ([people and search](08-people-and-search-screens.md)).

## 6. Break it on purpose

Leave out the route in step 3 but keep the link: the link goes to a blank content area (the router has no match) and the test using
`renderApp('/status', ...)` cannot find the heading. A route and its link are two edits; the test of the route catches a missing one.

## 7. Exercises

1. Why does the test pass `selector: 'strong'`?
2. Which two files must change for a new top-level screen to be reachable?
3. When must you run `npm run generate:api`?

**Answers**

1. The state word also appears as a capability value; the query must match exactly one element.
2. `routes.tsx` (the route) and `Layout.tsx` (the link; other screens are reached by links in the screens).
3. Whenever a backend route or response model changed, before using it from the front end.

## 8. Related files

- Previous: [09](09-styling-and-frontend-tests.md) · Up: [Front end](README.md)
- [`frontend/src/app/routes.tsx`](../../../frontend/src/app/routes.tsx), [`frontend/src/features/identities/IdentitiesPage.tsx`](../../../frontend/src/features/identities/IdentitiesPage.tsx)
