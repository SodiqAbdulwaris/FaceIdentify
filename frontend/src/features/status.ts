// How processing states read to a person, and which actions make sense in each. The backend sends
// the states; this is only wording and a few rules about buttons.

export const NOT_PROCESSED = 'NOT_PROCESSED'

const LABELS: Record<string, string> = {
  NOT_PROCESSED: 'Not processed',
  PENDING: 'Queued',
  RUNNING: 'Processing',
  PAUSING: 'Pausing',
  PAUSED: 'Paused',
  CANCELLING: 'Cancelling',
  CANCELLED: 'Cancelled',
  FINALIZING: 'Finishing',
  COMPLETED: 'Done',
  FAILED: 'Failed',
  INTERRUPTED: 'Interrupted',
  NOT_RESUMABLE: 'Failed',
}

export type Tone = 'neutral' | 'busy' | 'good' | 'bad'

const TONES: Record<string, Tone> = {
  NOT_PROCESSED: 'neutral',
  CANCELLED: 'neutral',
  PENDING: 'busy',
  RUNNING: 'busy',
  PAUSING: 'busy',
  PAUSED: 'busy',
  CANCELLING: 'busy',
  FINALIZING: 'busy',
  COMPLETED: 'good',
  FAILED: 'bad',
  INTERRUPTED: 'bad',
  NOT_RESUMABLE: 'bad',
}

export const statusLabel = (state: string): string => LABELS[state] ?? state
export const statusTone = (state: string): Tone => TONES[state] ?? 'neutral'

const ACTIVE = new Set(['PENDING', 'RUNNING', 'PAUSING', 'PAUSED', 'CANCELLING', 'FINALIZING'])

/** Work is queued or under way: it can change by itself, and it cannot be started again. */
export const isActive = (state: string): boolean => ACTIVE.has(state)

/** Processing can be requested: nothing is in progress and there is no finished result to repeat. */
export const canProcess = (state: string): boolean => !isActive(state) && state !== 'COMPLETED'

/** A run can be asked to stop while it has not yet been made authoritative. */
export const canCancel = (state: string): boolean => state === 'PENDING' || state === 'RUNNING'

/** A finished-without-result run can be tried again as a new run. */
export const canRetry = (state: string): boolean =>
  state === 'FAILED' || state === 'INTERRUPTED' || state === 'NOT_RESUMABLE'
