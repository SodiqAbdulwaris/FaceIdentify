import { useQuery } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { Link, useSearchParams } from 'react-router'
import { keys } from '@/api/keys'
import type { OccurrenceSummary } from '@/api/types'
import { useBackend } from '@/app/useBackend'
import { Button } from '@/components/ui/button'
import { FaceCrop } from '../FaceCrop'
import { errorMessage } from '../library/messages'
import { personLabel } from '../identities/label'

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`
const PLACES = {
  include: 'Everywhere',
  exclude: 'Not in the Recycle bin',
  only: 'Only the Recycle bin',
} as const
type Recycled = keyof typeof PLACES
const PLACE_KEYS = Object.keys(PLACES) as Recycled[]

/**
 * Find people, images and appearances by name. The word is kept in the address (`#/search?q=`),
 * so a reload or the back button brings the same search back. The answer says how much of the
 * library it could see: an image that was never processed has no faces to find.
 */
export function SearchPage() {
  const { endpoints } = useBackend()
  const [params, setParams] = useSearchParams()
  const q = params.get('q') ?? ''
  const recycled = PLACE_KEYS.find((r) => r === params.get('recycled')) ?? 'include'
  const [typed, setTyped] = useState(q)
  // Back and forward change the address; the box follows it (adjusted while rendering).
  const [shown, setShown] = useState(q)
  if (shown !== q) {
    setShown(q)
    setTyped(q)
  }
  const found = useQuery({
    queryKey: keys.search(q, recycled),
    queryFn: () => endpoints.search(q, recycled),
    enabled: q.trim() !== '',
  })

  const go = (word: string, place: Recycled) =>
    setParams({ q: word, ...(place === 'include' ? {} : { recycled: place }) })
  const submit = (event: FormEvent) => {
    event.preventDefault()
    go(typed.trim(), recycled)
  }
  const results = found.data?.results
  const nothing =
    results &&
    !results.people.length &&
    !results.identities.length &&
    !results.sources.length &&
    !results.occurrences.length

  return (
    <section className="flex flex-col gap-4">
      <h1 className="text-xl font-semibold">Search</h1>
      <form role="search" onSubmit={submit} className="flex flex-wrap gap-2">
        <input
          type="search"
          aria-label="Search for"
          value={typed}
          onChange={(event) => setTyped(event.target.value)}
          placeholder="A name, or an image file name"
          className="min-w-0 flex-1 basis-48 rounded-md border bg-background px-3 py-1.5 text-sm"
        />
        <select
          aria-label="Where"
          value={recycled}
          onChange={(event) => go(q, event.target.value as Recycled)}
          className="rounded-md border bg-background px-2 py-1.5 text-sm"
        >
          {PLACE_KEYS.map((r) => (
            <option key={r} value={r}>
              {PLACES[r]}
            </option>
          ))}
        </select>
        <Button type="submit" disabled={typed.trim() === ''}>
          Search
        </Button>
      </form>

      {found.isFetching && !found.data ? <p className="text-muted-foreground">Searching…</p> : null}
      {found.isError ? (
        <p role="alert" className="text-destructive">
          The search could not run: {errorMessage(found.error)}
        </p>
      ) : null}
      {found.data ? (
        <p role="status" aria-label="Search coverage" className="text-sm text-muted-foreground">
          Looked through {plural(found.data.coverage.sources, 'image', 'images')}.
          {found.data.coverage.not_processed > 0
            ? ` ${plural(found.data.coverage.not_processed, 'image has', 'images have')} not been processed yet, so any faces in ${found.data.coverage.not_processed === 1 ? 'it' : 'them'} cannot be found.`
            : ''}
        </p>
      ) : null}
      {nothing ? (
        <div className="rounded-lg border border-dashed p-10 text-center text-muted-foreground">
          <p className="font-medium text-foreground">Nothing found for “{found.data?.query}”</p>
        </div>
      ) : null}

      {results?.people.length ? (
        <section aria-label="People found" className="flex flex-col gap-2">
          <h2 className="font-medium">People</h2>
          <ul className="flex flex-col gap-1">
            {results.people.map((person) => {
              const first = person.identity_ids[0]
              const label = (
                <>
                  <span className="font-medium">{person.display_name}</span>{' '}
                  <span className="text-sm text-muted-foreground">
                    {plural(person.occurrence_count, 'appearance', 'appearances')} in{' '}
                    {plural(person.source_count, 'image', 'images')}
                    {person.visual_support ? '' : ' · no remembered face, so not recognisable'}
                  </span>
                </>
              )
              return (
                <li key={person.id} className="rounded-md border px-3 py-2">
                  {first ? <Link to={`/identities/${first}`}>{label}</Link> : label}
                </li>
              )
            })}
          </ul>
        </section>
      ) : null}

      {results?.identities.length ? (
        <section aria-label="Unnamed people found" className="flex flex-col gap-2">
          <h2 className="font-medium">Not yet named</h2>
          <ul className="flex flex-col gap-1">
            {results.identities.map((identity) => (
              <li key={identity.id} className="rounded-md border px-3 py-2">
                <Link to={`/identities/${identity.id}`}>
                  <span className="font-medium">{identity.label}</span>{' '}
                  <span className="text-sm text-muted-foreground">
                    {plural(identity.occurrence_count, 'appearance', 'appearances')} in{' '}
                    {plural(identity.source_count, 'image', 'images')}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {results?.sources.length ? (
        <section aria-label="Images found" className="flex flex-col gap-2">
          <h2 className="font-medium">Images</h2>
          <ul className="flex flex-col gap-1">
            {results.sources.map((source) => (
              <li key={source.id} className="rounded-md border px-3 py-2">
                <Link to={`/library/source/${source.id}`}>
                  <span className="font-medium">{source.display_name}</span>{' '}
                  <span className="text-sm text-muted-foreground">
                    {[
                      source.source_recycled ? 'In the Recycle bin' : null,
                      source.processed ? null : 'Not processed yet',
                    ]
                      .filter(Boolean)
                      .join(' · ')}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {results?.occurrences.length ? (
        <section aria-label="Appearances found" className="flex flex-col gap-2">
          <h2 className="font-medium">Where they appear</h2>
          <ul className="grid grid-cols-[repeat(auto-fill,minmax(min(15rem,100%),1fr))] gap-3">
            {results.occurrences.map((occurrence) => (
              <Appearance key={occurrence.id} occurrence={occurrence} />
            ))}
          </ul>
        </section>
      ) : null}
    </section>
  )
}

function Appearance({ occurrence }: { occurrence: OccurrenceSummary }) {
  const face = occurrence.representative_observation
  const who = personLabel(occurrence.identity_id, occurrence.person)
  return (
    <li>
      <Link
        to={`/library/source/${occurrence.source_id}`}
        className="flex items-center gap-3 rounded-lg border bg-card p-3 hover:bg-accent/40"
      >
        {face ? (
          <FaceCrop sourceId={face.source_id} box={face.bounding_box} label={`${who}'s face`} />
        ) : (
          <div className="size-24 shrink-0 rounded-md bg-muted" aria-hidden="true" />
        )}
        <span className="flex min-w-0 flex-col break-words">
          <span className="font-medium">{who}</span>
          <span className="text-sm text-muted-foreground">
            in {occurrence.source_display_name}
            {occurrence.source_recycled ? ' (in the Recycle bin)' : ''}
          </span>
        </span>
      </Link>
    </li>
  )
}
