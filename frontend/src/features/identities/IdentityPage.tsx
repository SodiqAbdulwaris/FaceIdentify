import { useInfiniteQuery, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useParams } from 'react-router'
import { ApiError } from '@/api/client'
import { keys } from '@/api/keys'
import { useBackend } from '@/app/useBackend'
import { Button } from '@/components/ui/button'
import { FaceCrop } from '../FaceCrop'
import { FaceCorrection } from '../source/FaceCorrection'
import { errorMessage } from '../library/messages'
import { MergeControl } from './MergeControl'
import { NameForm } from './NameForm'
import { SplitControl } from './SplitControl'
import { personLabel } from './label'

export function IdentityPage() {
  const { identityId = '' } = useParams()
  const { endpoints } = useBackend()

  const [chosen, setChosen] = useState<string[]>([])
  const person = useQuery({
    queryKey: keys.identity(identityId),
    queryFn: () => endpoints.getIdentity(identityId),
    retry: false,
  })
  const appearances = useInfiniteQuery({
    queryKey: keys.identityOccurrences(identityId),
    queryFn: ({ pageParam }) => endpoints.identityOccurrences(identityId, pageParam),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (page) => page.page.next_cursor ?? undefined,
    enabled: person.isSuccess,
  })

  if (person.isError) {
    const notFound = person.error instanceof ApiError && person.error.code === 'IDENTITY_NOT_FOUND'
    return (
      <section className="flex flex-col gap-2">
        <h1 className="text-xl font-semibold">
          {notFound ? 'This person is not in your library' : 'This person could not be loaded'}
        </h1>
        {notFound ? null : <p role="alert">{errorMessage(person.error)}</p>}
        <Link to="/identities" className="text-primary underline">
          Back to people
        </Link>
      </section>
    )
  }
  if (person.isPending) return <p className="text-muted-foreground">Loading…</p>

  const label = personLabel(identityId, person.data.person)
  const items = appearances.data?.pages.flatMap((page) => page.items) ?? []
  const { occurrence_count: count, source_count: sources } = person.data

  return (
    <section className="flex flex-col gap-4">
      <div className="flex items-center gap-3">
        <Link to="/identities" className="text-sm text-muted-foreground hover:underline">
          ← People
        </Link>
        <h1 className="text-xl font-semibold">{label}</h1>
      </div>
      <p className="text-muted-foreground">
        Appears {count === 1 ? 'once' : `${count} times`} in {sources}{' '}
        {sources === 1 ? 'image' : 'images'}.
        {person.data.person ? '' : ' Nobody has named this person yet.'}
      </p>
      <NameForm identityId={identityId} person={person.data.person ?? null} />
      <MergeControl identity={person.data} />

      <h2 className="font-medium">Where this person appears</h2>
      {appearances.isPending ? <p className="text-sm text-muted-foreground">Loading…</p> : null}
      {appearances.isError ? (
        <p role="alert" className="text-sm text-destructive">
          The appearances could not be loaded: {errorMessage(appearances.error)}
        </p>
      ) : null}
      {appearances.isSuccess && items.length === 0 ? (
        <p className="text-sm text-muted-foreground">No appearances to show.</p>
      ) : null}

      <SplitControl
        identity={person.data}
        selected={chosen}
        onAdd={(ids) => setChosen((now) => [...new Set([...now, ...ids])])}
        onDone={() => setChosen([])}
      />

      {items.length > 0 ? (
        <ul className="grid grid-cols-[repeat(auto-fill,minmax(14rem,1fr))] gap-3">
          {items.map((occurrence) => {
            const face = occurrence.representative_observation
            return (
              <li key={occurrence.id}>
                <Link
                  to={`/library/source/${occurrence.source_id}`}
                  className="flex items-center gap-3 rounded-lg border bg-card p-3 hover:bg-accent/40"
                >
                  {face ? (
                    <FaceCrop
                      sourceId={face.source_id}
                      box={face.bounding_box}
                      label={`${label} in ${occurrence.source_display_name}`}
                    />
                  ) : (
                    <div className="size-24 shrink-0 rounded-md bg-muted" aria-hidden="true" />
                  )}
                  <span className="min-w-0 break-words text-sm font-medium">
                    {occurrence.source_display_name}
                  </span>
                </Link>
                <div className="mt-1 flex flex-col gap-1">
                  <label className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={chosen.includes(occurrence.id)}
                      onChange={(event) =>
                        setChosen((now) =>
                          event.target.checked
                            ? [...now, occurrence.id]
                            : now.filter((id) => id !== occurrence.id),
                        )
                      }
                    />
                    Not {label}: choose this face
                  </label>
                  <FaceCorrection face={{ occurrence, label }} />
                </div>
              </li>
            )
          })}
        </ul>
      ) : null}

      {appearances.hasNextPage ? (
        <Button
          variant="outline"
          className="self-center"
          disabled={appearances.isFetchingNextPage}
          onClick={() => void appearances.fetchNextPage()}
        >
          {appearances.isFetchingNextPage ? 'Loading…' : 'Load more'}
        </Button>
      ) : null}
    </section>
  )
}
