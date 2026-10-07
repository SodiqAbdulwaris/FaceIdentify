import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useParams } from 'react-router'
import { ApiError } from '@/api/client'
import { keys } from '@/api/keys'
import { useBackend } from '@/app/useBackend'
import { Button } from '@/components/ui/button'
import { StatusBadge } from '../StatusBadge'
import { ACTIVE_REFETCH_MS, canCancel, canProcess, canRetry, isActive } from '../status'
import { useSourceImage } from '../useSourceImage'
import { errorMessage } from '../library/messages'
import { useRunActions } from '../processing/useRunActions'
import { FaceCorrection } from './FaceCorrection'
import { FaceOverlay } from './FaceOverlay'
import { UnresolvedFaces } from './UnresolvedFaces'
import { labelFaces } from './faces'

const kilobytes = (bytes: number | null) => (bytes === null ? '' : `${Math.ceil(bytes / 1024)} KB`)

export function SourcePage() {
  const { sourceId = '' } = useParams()
  const { endpoints } = useBackend()
  const [notice, setNotice] = useState<string | null>(null)
  const actions = useRunActions(setNotice)

  const source = useQuery({
    queryKey: keys.source(sourceId),
    queryFn: () => endpoints.getSource(sourceId),
    retry: false,
  })
  const missing = source.data?.availability !== 'AVAILABLE'
  const image = useSourceImage(sourceId, source.isSuccess && !missing)
  const occurrences = useQuery({
    queryKey: keys.sourceOccurrences(sourceId),
    queryFn: () => endpoints.sourceOccurrences(sourceId),
    enabled: source.isSuccess,
  })
  const runs = useQuery({
    queryKey: keys.sourceRuns(sourceId),
    queryFn: () => endpoints.sourceRuns(sourceId),
    enabled: source.isSuccess,
    refetchInterval: (query) =>
      query.state.data?.items[0] && isActive(query.state.data.items[0].state)
        ? ACTIVE_REFETCH_MS
        : false,
  })

  if (source.isError) {
    const notFound = source.error instanceof ApiError && source.error.code === 'SOURCE_NOT_FOUND'
    return (
      <section className="flex flex-col gap-2">
        <h1 className="text-xl font-semibold">
          {notFound ? 'This image is not in your library' : 'This image could not be loaded'}
        </h1>
        {notFound ? null : <p role="alert">{errorMessage(source.error)}</p>}
        <Link to="/library" className="text-primary underline">
          Back to the library
        </Link>
      </section>
    )
  }
  if (source.isPending) return <p className="text-muted-foreground">Loading…</p>

  const detail = source.data
  const faces = labelFaces(occurrences.data?.items ?? [])
  const latest = runs.data?.items[0]
  const people = [...new Map(faces.map((f) => [f.occurrence.identity_id, f.label])).entries()]

  return (
    <section className="flex flex-col gap-4">
      <div className="flex items-center gap-3">
        <Link to="/library" className="text-sm text-muted-foreground hover:underline">
          ← Library
        </Link>
        <h1 className="text-xl font-semibold">{detail.display_name}</h1>
        <StatusBadge state={detail.processing_status} />
      </div>

      {notice ? (
        <p
          role="status"
          aria-label="Source notice"
          className="rounded-md bg-muted px-3 py-2 text-sm"
        >
          {notice}
        </p>
      ) : null}

      <div className="grid gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(16rem,1fr)]">
        <div>
          {image.url ? (
            <FaceOverlay url={image.url} alt={detail.display_name} faces={faces} />
          ) : (
            <p className="rounded-lg border border-dashed p-10 text-center text-muted-foreground">
              {missing
                ? 'The file for this image is missing. Put it back where it was to see it again.'
                : image.isError
                  ? 'The image could not be loaded.'
                  : 'Loading the image…'}
            </p>
          )}
        </div>

        <div className="flex flex-col gap-5">
          <div className="flex flex-wrap gap-2">
            {canProcess(detail.processing_status) && !missing ? (
              <Button disabled={actions.busy} onClick={() => actions.process.mutate(sourceId)}>
                Process
              </Button>
            ) : null}
            {latest && canCancel(latest.state) ? (
              <Button
                variant="outline"
                disabled={actions.busy}
                onClick={() => actions.cancel.mutate(latest)}
              >
                Cancel processing
              </Button>
            ) : null}
            {latest && canRetry(latest.state) && !missing ? (
              <Button disabled={actions.busy} onClick={() => actions.retry.mutate(latest)}>
                Try again
              </Button>
            ) : null}
          </div>

          {latest && isActive(latest.state) ? (
            <p className="text-sm text-muted-foreground">
              Processing is under way. This page updates by itself.
            </p>
          ) : null}

          <div>
            <h2 className="mb-1 font-medium">People in this image</h2>
            {occurrences.isPending ? (
              <p className="text-sm text-muted-foreground">Loading…</p>
            ) : people.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                {detail.processing_status === 'COMPLETED'
                  ? 'No faces were found in this image.'
                  : 'Nobody yet. Faces appear here once the image has been processed.'}
              </p>
            ) : (
              <ul className="flex flex-col gap-1">
                {people.map(([identityId, label]) => (
                  <li key={identityId}>
                    <Link to={`/identities/${identityId}`} className="text-primary underline">
                      {label}
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <UnresolvedFaces sourceId={sourceId} />

          {faces.length > 0 ? (
            <div>
              <h2 className="mb-1 font-medium">Faces</h2>
              <ul className="flex flex-col gap-2">
                {faces.map((face) => (
                  <li key={face.occurrence.id} className="flex flex-col gap-1">
                    <span className="text-sm">{face.label}</span>
                    <FaceCorrection face={face} />
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          <div>
            <h2 className="mb-1 font-medium">Processing history</h2>
            {runs.isPending ? (
              <p className="text-sm text-muted-foreground">Loading…</p>
            ) : runs.isError ? (
              <p role="alert" className="text-sm text-destructive">
                The processing history could not be loaded: {errorMessage(runs.error)}
              </p>
            ) : runs.data.items.length === 0 ? (
              <p className="text-sm text-muted-foreground">This image has not been processed.</p>
            ) : (
              <ul className="flex flex-col gap-1">
                {runs.data.items.map((run) => (
                  <li key={run.id} className="flex items-center gap-2 text-sm">
                    <StatusBadge state={run.state} />
                    <Link to={`/processing/${run.id}`} className="text-primary underline">
                      {new Date(run.requested_at).toLocaleString()}
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm text-muted-foreground">
            {detail.width && detail.height ? (
              <>
                <dt>Size</dt>
                <dd>
                  {detail.width} × {detail.height} px
                  {detail.size_bytes !== null ? `, ${kilobytes(detail.size_bytes)}` : ''}
                </dd>
              </>
            ) : null}
            {detail.original_filename ? (
              <>
                <dt>File</dt>
                <dd className="break-all">{detail.original_filename}</dd>
              </>
            ) : null}
            <dt>Kept</dt>
            <dd>{detail.storage_mode === 'MANAGED' ? 'In your library' : 'Where it was'}</dd>
          </dl>
        </div>
      </div>
    </section>
  )
}
