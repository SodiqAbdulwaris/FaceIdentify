import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router'
import { keys } from '@/api/keys'
import type { OccurrenceSummary, UnresolvedFace } from '@/api/types'
import { useBackend } from '@/app/useBackend'
import { Button } from '@/components/ui/button'
import { personLabel } from '../identities/label'
import { errorMessage } from '../library/messages'
import { useObjectUrl } from '../useSourceImage'
import { ConfirmButton } from './ConfirmButton'
import { dayLabel, dayRange, timeLabel } from './session'

interface Day {
  start: number
  visits: OccurrenceSummary[]
  unknown: UnresolvedFace[]
}

/** Who a camera saw, by day (M7 step 5), and deleting it for good: one visit, a selection, a day
 * or everything. There is no Recycle bin for camera history (plan C9). */
export function CameraHistoryPage() {
  const { cameraId = '' } = useParams()
  const { endpoints } = useBackend()
  const queryClient = useQueryClient()
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [notice, setNotice] = useState<string | null>(null)
  const cameras = useQuery({ queryKey: keys.cameras, queryFn: endpoints.listCameras })
  const camera = cameras.data?.find((c) => c.id === cameraId)
  const visits = useInfiniteQuery({
    queryKey: keys.sourceOccurrences(cameraId),
    queryFn: ({ pageParam }) => endpoints.sourceOccurrences(cameraId, pageParam),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (page) => page.page.next_cursor ?? undefined,
  })
  const { hasNextPage, isFetchingNextPage, fetchNextPage } = visits
  useEffect(() => {
    if (hasNextPage && !isFetchingNextPage) void fetchNextPage()
  }, [hasNextPage, isFetchingNextPage, fetchNextPage])
  const unknown = useQuery({
    queryKey: keys.sourceUnresolved(cameraId),
    queryFn: () => endpoints.unresolvedFaces(cameraId),
  })
  const remove = useMutation({
    mutationFn: (selection: { occurrence_ids?: string[]; start_ms?: number; end_ms?: number }) =>
      endpoints.deleteCameraHistory(cameraId, selection),
    onSuccess: (result) => {
      setSelected(new Set())
      setNotice(
        result.complete
          ? 'Deleted for good.'
          : 'Deleted. Part of the clean-up could not finish yet; it is tried again later.',
      )
    },
    onError: (error) => setNotice(errorMessage(error)),
    onSettled: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: keys.source(cameraId) }),
        queryClient.invalidateQueries({ queryKey: keys.identities }),
        queryClient.invalidateQueries({ queryKey: ['identity'] }),
      ]),
  })

  const days = byDay(
    visits.data?.pages.flatMap((page) => page.items) ?? [],
    unknown.data?.items ?? [],
  )
  const name = camera?.display_name ?? 'Camera'

  return (
    <section className="flex flex-col gap-4">
      <Link to="/cameras" className="text-sm text-muted-foreground">
        ← Cameras
      </Link>
      <h1 className="text-xl font-semibold">{name}: history</h1>
      {notice ? (
        <p
          role="status"
          aria-label="History notice"
          className="rounded-md border px-3 py-2 text-sm"
        >
          {notice}
        </p>
      ) : null}
      {visits.isError ? (
        <p role="alert" className="text-destructive">
          The history could not be loaded: {errorMessage(visits.error)}
        </p>
      ) : null}
      {visits.isSuccess && unknown.isSuccess && days.length === 0 ? (
        <p className="text-muted-foreground">Nothing recorded.</p>
      ) : null}
      {days.length > 0 ? (
        <div className="flex flex-wrap gap-2">
          <Button
            size="sm"
            variant="outline"
            disabled={selected.size === 0 || remove.isPending}
            onClick={() => remove.mutate({ occurrence_ids: [...selected] })}
          >
            Delete selected ({selected.size})
          </Button>
          <ConfirmButton
            label="Delete all history"
            question={`Delete everything ${name} recorded, for good? This cannot be undone.`}
            confirm="Delete for good"
            disabled={remove.isPending}
            onConfirm={() => remove.mutate({})}
          />
        </div>
      ) : null}
      {days.map((day) => (
        <section key={day.start} aria-label={dayLabel(day.start)} className="flex flex-col gap-2">
          <div className="flex flex-wrap items-center gap-3">
            <h2 className="font-medium">{dayLabel(day.start)}</h2>
            <ConfirmButton
              label="Delete this day"
              question={`Delete everything ${name} recorded on ${dayLabel(day.start)}, for good?`}
              confirm="Delete for good"
              disabled={remove.isPending}
              onConfirm={() => remove.mutate(dayRange(day.start))}
            />
          </div>
          <ul className="flex flex-col gap-2">
            {day.visits.map((visit) => (
              <li key={visit.id} className="flex items-center gap-3 rounded-md border p-2">
                <input
                  type="checkbox"
                  aria-label={`Select ${personLabel(visit.identity_id, visit.person)} at ${timeLabel(visit.start_ms ?? 0)}`}
                  checked={selected.has(visit.id)}
                  onChange={(event) => {
                    const next = new Set(selected)
                    if (event.target.checked) next.add(visit.id)
                    else next.delete(visit.id)
                    setSelected(next)
                  }}
                />
                {visit.representative_observation ? (
                  <CameraFace
                    cameraId={cameraId}
                    observationId={visit.representative_observation.id}
                    label={`${personLabel(visit.identity_id, visit.person)}'s face`}
                  />
                ) : null}
                <Link to={`/identities/${visit.identity_id}`} className="font-medium">
                  {personLabel(visit.identity_id, visit.person)}
                </Link>
                <span className="text-sm text-muted-foreground">
                  {timeLabel(visit.start_ms ?? 0)} to {timeLabel(visit.end_ms ?? 0)}
                </span>
              </li>
            ))}
          </ul>
          {day.unknown.length > 0 ? (
            <div className="flex flex-col gap-1">
              <h3 className="text-sm text-muted-foreground">Not recognised</h3>
              <ul className="flex flex-wrap gap-2">
                {day.unknown.map((face) => (
                  <li key={face.observation_id} className="flex flex-col items-center text-xs">
                    <CameraFace
                      cameraId={cameraId}
                      observationId={face.observation_id}
                      label={`An unrecognised face at ${timeLabel(face.seen_at_ms ?? 0)}`}
                    />
                    {timeLabel(face.seen_at_ms ?? 0)}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </section>
      ))}
    </section>
  )
}

function byDay(visits: OccurrenceSummary[], unknown: UnresolvedFace[]): Day[] {
  const days = new Map<number, Day>()
  const dayOf = (ms: number) => {
    const start = dayRange(ms).start_ms
    let day = days.get(start)
    if (!day) {
      day = { start, visits: [], unknown: [] }
      days.set(start, day)
    }
    return day
  }
  for (const visit of visits) dayOf(visit.start_ms ?? 0).visits.push(visit)
  for (const face of unknown) dayOf(face.seen_at_ms ?? 0).unknown.push(face)
  for (const day of days.values()) {
    day.visits.sort((a, b) => (a.start_ms ?? 0) - (b.start_ms ?? 0))
    day.unknown.sort((a, b) => (a.seen_at_ms ?? 0) - (b.seen_at_ms ?? 0))
  }
  return [...days.values()].sort((a, b) => b.start - a.start) // newest day first
}

/** A camera face as it was kept (its stored crop). */
function CameraFace({
  cameraId,
  observationId,
  label,
}: {
  cameraId: string
  observationId: string
  label: string
}) {
  const { endpoints } = useBackend()
  const picture = useQuery({
    queryKey: keys.cameraFace(cameraId, observationId),
    queryFn: () => endpoints.cameraFace(cameraId, observationId),
    staleTime: Infinity,
    retry: false,
  })
  const url = useObjectUrl(picture.data)
  return (
    <div className="size-16 shrink-0 overflow-hidden rounded-md bg-muted">
      {url ? <img src={url} alt={label} className="size-full object-cover" /> : null}
    </div>
  )
}
