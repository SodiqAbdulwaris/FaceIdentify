import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useParams } from 'react-router'
import { ApiError } from '@/api/client'
import { keys } from '@/api/keys'
import { useBackend } from '@/app/useBackend'
import { Button } from '@/components/ui/button'
import { StatusBadge } from '../StatusBadge'
import { canCancel, canRetry, isActive } from '../status'
import { errorMessage } from '../library/messages'
import { useRunActions } from './useRunActions'

const when = (value: string | null) => (value ? new Date(value).toLocaleString() : null)

export function ProcessingPage() {
  const { runId = '' } = useParams()
  const { endpoints } = useBackend()
  const [notice, setNotice] = useState<string | null>(null)
  const actions = useRunActions(setNotice)

  const run = useQuery({
    queryKey: keys.run(runId),
    queryFn: () => endpoints.getRun(runId),
    retry: false,
  })

  if (run.isError) {
    const notFound = run.error instanceof ApiError && run.error.code === 'RUN_NOT_FOUND'
    return (
      <section className="flex flex-col gap-2">
        <h1 className="text-xl font-semibold">
          {notFound
            ? 'This processing run does not exist'
            : 'This processing run could not be loaded'}
        </h1>
        {notFound ? null : <p role="alert">{errorMessage(run.error)}</p>}
        <Link to="/library" className="text-primary underline">
          Back to the library
        </Link>
      </section>
    )
  }
  if (run.isPending) return <p className="text-muted-foreground">Loading…</p>

  const data = run.data
  const progress = data.job?.progress
  const steps: [string, string | null][] = [
    ['Requested', when(data.requested_at)],
    ['Started', when(data.started_at)],
    ['Finished', when(data.completed_at)],
    ['Failed', when(data.failed_at)],
  ]

  return (
    <section className="flex flex-col gap-4">
      <div className="flex items-center gap-3">
        <Link
          to={`/library/source/${data.source_id}`}
          className="text-sm text-muted-foreground hover:underline"
        >
          ← The image
        </Link>
        <h1 className="text-xl font-semibold">Processing</h1>
        <StatusBadge state={data.state} />
      </div>

      {notice ? (
        <p
          role="status"
          aria-label="Processing notice"
          className="rounded-md bg-muted px-3 py-2 text-sm"
        >
          {notice}
        </p>
      ) : null}

      {isActive(data.state) ? (
        <p className="text-sm text-muted-foreground">
          This is under way. The page updates by itself.
          {progress
            ? ` ${progress.completed}${progress.total !== null ? ` of ${progress.total}` : ''} done.`
            : ''}
        </p>
      ) : null}
      {data.failure_code ? (
        <p role="alert" className="text-sm text-destructive">
          It stopped without a result ({data.failure_code}). Nothing from this attempt was kept.
        </p>
      ) : null}

      <div className="flex flex-wrap gap-2">
        {canCancel(data.state) ? (
          <Button
            variant="outline"
            disabled={actions.busy}
            onClick={() => actions.cancel.mutate(data)}
          >
            Cancel processing
          </Button>
        ) : null}
        {canRetry(data.state) ? (
          <Button disabled={actions.busy} onClick={() => actions.retry.mutate(data)}>
            Try again
          </Button>
        ) : null}
      </div>

      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
        {steps.map(([name, value]) =>
          value ? (
            <div key={name} className="contents">
              <dt className="text-muted-foreground">{name}</dt>
              <dd>{value}</dd>
            </div>
          ) : null,
        )}
        {data.job ? (
          <>
            <dt className="text-muted-foreground">Job</dt>
            <dd>
              {data.job.state.toLowerCase()}, attempt {data.job.attempt_number}
            </dd>
          </>
        ) : null}
        {data.parent_run_id ? (
          <>
            <dt className="text-muted-foreground">Retry of</dt>
            <dd>
              <Link to={`/processing/${data.parent_run_id}`} className="text-primary underline">
                the earlier attempt
              </Link>
            </dd>
          </>
        ) : null}
        <dt className="text-muted-foreground">Policy</dt>
        <dd>
          {data.policy.decision_policy_version ?? data.policy.calibration_mode}
          {data.policy.calibrated ? '' : ' (uncalibrated)'}
        </dd>
      </dl>
    </section>
  )
}
