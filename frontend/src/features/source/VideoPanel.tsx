import { Link } from 'react-router'
import type { ProcessingRun } from '@/api/types'
import { clock } from '@/lib/utils'
import type { Face } from './faces'

/**
 * How far processing has got through the video, and about how long is left: the time spent so far
 * shared over the part done (the run's own pace, so no estimate before the first chunk).
 */
export function VideoProgress({ run, now }: { run: ProcessingRun; now: number }) {
  const progress = run.job?.progress
  if (!progress || !progress.total) return null
  const done = progress.completed / progress.total
  const started = run.started_at ? Date.parse(run.started_at) : null
  const left =
    started !== null && done > 0 && done < 1
      ? ((now - started) / done) * (1 - done)
      : null
  return (
    <div className="flex flex-col gap-1">
      <div
        role="progressbar"
        aria-label="Video processed"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(done * 100)}
        className="h-2 w-full overflow-hidden rounded bg-muted"
      >
        <div className="h-full bg-primary" style={{ width: `${done * 100}%` }} />
      </div>
      <p className="text-sm text-muted-foreground">
        {Math.round(done * 100)}% of the video checked
        {left !== null ? `, about ${clock(left)} left` : ''}
      </p>
    </div>
  )
}

/** Who appears when: one row per person, a bar per appearance, the times also written out. */
export function VideoTimeline({ durationMs, faces }: { durationMs: number; faces: Face[] }) {
  const people = new Map<string, { label: string; spans: Face[] }>()
  for (const face of faces) {
    const row = people.get(face.occurrence.identity_id) ?? { label: face.label, spans: [] }
    row.spans.push(face)
    people.set(face.occurrence.identity_id, row)
  }
  if (people.size === 0) return null
  const at = (ms: number | null) => `${((ms ?? 0) / Math.max(durationMs, 1)) * 100}%`
  return (
    <div>
      <h2 className="mb-1 font-medium">Appearances</h2>
      <ul className="flex flex-col gap-3">
        {[...people.entries()].map(([identityId, { label, spans }]) => (
          <li key={identityId} className="flex flex-col gap-1">
            <Link to={`/identities/${identityId}`} className="text-primary underline">
              {label}
            </Link>
            <div aria-hidden className="relative h-3 w-full rounded bg-muted">
              {spans.map(({ occurrence }) => (
                <div
                  key={occurrence.id}
                  className="absolute h-full rounded bg-primary"
                  style={{
                    left: at(occurrence.start_ms),
                    width: `max(2px, calc(${at(occurrence.end_ms)} - ${at(occurrence.start_ms)}))`,
                  }}
                />
              ))}
            </div>
            <p className="text-sm text-muted-foreground">
              {spans
                .map(({ occurrence }) =>
                  occurrence.start_ms === occurrence.end_ms
                    ? `at ${clock(occurrence.start_ms ?? 0)}`
                    : `${clock(occurrence.start_ms ?? 0)} to ${clock(occurrence.end_ms ?? 0)}`,
                )
                .join(', ')}
            </p>
          </li>
        ))}
      </ul>
    </div>
  )
}
