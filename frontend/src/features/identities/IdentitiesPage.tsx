import { useInfiniteQuery } from '@tanstack/react-query'
import { useEffect } from 'react'
import { Link, useLocation } from 'react-router'
import { keys } from '@/api/keys'
import { useBackend } from '@/app/useBackend'
import { Button } from '@/components/ui/button'
import { FaceCrop } from '../FaceCrop'
import { errorMessage } from '../library/messages'
import { personLabel } from './label'

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`

export function IdentitiesPage() {
  const { endpoints } = useBackend()
  // A screen that sent us here (a forgotten person's page) may have something to tell.
  const notice = (useLocation().state as { notice?: string | null } | null)?.notice ?? null
  const people = useInfiniteQuery({
    queryKey: keys.identities,
    queryFn: ({ pageParam }) => endpoints.listIdentities(pageParam),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (page) => page.page.next_cursor ?? undefined,
  })
  const items = people.data?.pages.flatMap((page) => page.items) ?? []
  // A named person who has no face remembered (all were forgotten, or their images were deleted).
  const named = useInfiniteQuery({
    queryKey: keys.people,
    queryFn: ({ pageParam }) => endpoints.listPeople(pageParam),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (page) => page.page.next_cursor ?? undefined,
  })
  const { hasNextPage, isFetchingNextPage, fetchNextPage } = named
  useEffect(() => {
    // The list of people is short and shown whole: the rest of its pages follow the first.
    if (hasNextPage && !isFetchingNextPage) void fetchNextPage()
  }, [hasNextPage, isFetchingNextPage, fetchNextPage])
  const withoutFace = (named.data?.pages.flatMap((page) => page.items) ?? []).filter(
    (person) => person.identity_count === 0,
  )

  return (
    <section className="flex flex-col gap-4">
      <h1 className="text-xl font-semibold">People</h1>
      {notice ? (
        <p role="status" aria-label="People notice" className="rounded-md border px-3 py-2 text-sm">
          {notice}
        </p>
      ) : null}
      {people.isPending ? <p className="text-muted-foreground">Loading…</p> : null}
      {people.isError ? (
        <p role="alert" className="text-destructive">
          People could not be loaded: {errorMessage(people.error)}
        </p>
      ) : null}
      {people.isSuccess && items.length === 0 ? (
        <div className="rounded-lg border border-dashed p-10 text-center text-muted-foreground">
          <p className="font-medium text-foreground">Nobody yet</p>
          <p>People appear here once images have been processed.</p>
        </div>
      ) : null}

      {items.length > 0 ? (
        <ul className="grid grid-cols-[repeat(auto-fill,minmax(15rem,1fr))] gap-3">
          {items.map((person) => {
            const face = person.representative_observation
            return (
              <li key={person.id}>
                <Link
                  to={`/identities/${person.id}`}
                  className="flex items-center gap-3 rounded-lg border bg-card p-3 hover:bg-accent/40"
                >
                  {face ? (
                    <FaceCrop
                      sourceId={face.source_id}
                      box={face.bounding_box}
                      label={`${personLabel(person.id, person.person)}'s face`}
                    />
                  ) : (
                    <div className="size-24 shrink-0 rounded-md bg-muted" aria-hidden="true" />
                  )}
                  <span className="flex flex-col">
                    <span className="font-medium">{personLabel(person.id, person.person)}</span>
                    <span className="text-sm text-muted-foreground">
                      {plural(person.occurrence_count, 'appearance', 'appearances')} in{' '}
                      {plural(person.source_count, 'image', 'images')}
                    </span>
                  </span>
                </Link>
              </li>
            )
          })}
        </ul>
      ) : null}

      {withoutFace.length > 0 ? (
        <section className="flex flex-col gap-2" aria-label="People without a remembered face">
          <h2 className="font-medium">Known by name only</h2>
          <p className="text-sm text-muted-foreground">
            The app remembers no face for these people, so it cannot recognise them. Their names stay.
          </p>
          <ul className="flex flex-col gap-1">
            {withoutFace.map((person) => (
              <li key={person.id} className="rounded-md border px-3 py-2 text-sm">
                {person.display_name}
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {people.hasNextPage ? (
        <Button
          variant="outline"
          className="self-center"
          disabled={people.isFetchingNextPage}
          onClick={() => void people.fetchNextPage()}
        >
          {people.isFetchingNextPage ? 'Loading…' : 'Load more'}
        </Button>
      ) : null}
    </section>
  )
}
