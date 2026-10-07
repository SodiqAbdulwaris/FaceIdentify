import { statusLabel, statusTone, type Tone } from './status'

const TONE_CLASSES: Record<Tone, string> = {
  neutral: 'bg-muted text-muted-foreground',
  busy: 'bg-blue-100 text-blue-900 dark:bg-blue-950 dark:text-blue-200',
  good: 'bg-green-100 text-green-900 dark:bg-green-950 dark:text-green-200',
  bad: 'bg-red-100 text-red-900 dark:bg-red-950 dark:text-red-200',
}

export function StatusBadge({ state }: { state: string }) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${TONE_CLASSES[statusTone(state)]}`}
    >
      {statusLabel(state)}
    </span>
  )
}
