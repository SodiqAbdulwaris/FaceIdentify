import { useInfiniteQuery } from '@tanstack/react-query'
import { Link } from 'react-router'
import { keys } from '@/api/keys'
import { useBackend } from '@/app/useBackend'
import { Button } from '@/components/ui/button'
import { FaceCrop } from '../FaceCrop'
import { errorMessage } from '../library/messages'
import { personLabel } from './label'

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`

export function IdentitiesPage() {
  const { endpoints } = useBackend()
  const people = useInfiniteQuery({
    queryKey: keys.identities,
    queryFn: ({ pageParam }) => endpoints.listIdentities(pageParam),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (page) => page.page.next_cursor ?? undefined,
  })
  const items = people.data?.pages.flatMap((page) => page.items) ?? []

  return (
    <section className="flex flex-col gap-4">
      <h1 className="text-xl font-semibold">People</h1>
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
                      label={`${personLabel(person.id)}'s face`}
                    />
                  ) : (
                    <div className="size-24 shrink-0 rounded-md bg-muted" aria-hidden="true" />
                  )}
                  <span className="flex flex-col">
                    <span className="font-medium">{personLabel(person.id)}</span>
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
