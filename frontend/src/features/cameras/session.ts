// What a camera session's state means to a person (M7 step 5).

import type { CameraSession } from '@/api/types'

/** States in which the camera is on: the "Camera on" indicator shows. */
export const ON = ['STARTING', 'RUNNING', 'RECONNECTING']

export const isOn = (session: CameraSession) => session.state !== null && ON.includes(session.state)

/** Why a session ended, in words a person can act on. */
export function failureMessage(code: string | null): string {
  switch (code) {
    case 'CAMERA_IN_USE':
      return 'Another program is using the camera. Close it and start again.'
    case 'CAMERA_ACCESS_DENIED':
      return 'Windows does not let desktop apps use the camera. Turn on "Let desktop apps access your camera" in Settings, Privacy & security, Camera.'
    case 'CAMERA_DISCONNECTED':
      return 'The camera gave no picture or was disconnected. Check that it is plugged in and that its privacy shutter or camera key is not covering it.'
    default:
      return `The camera session stopped unexpectedly${code ? ` (${code})` : ''}.`
  }
}

export function sessionLabel(session: CameraSession): string {
  switch (session.state) {
    case 'STARTING':
      return 'Starting…'
    case 'RUNNING':
      return `On: ${session.open_encounters} in view, ${session.encounters} recorded, ${session.dropped} frames skipped`
    case 'RECONNECTING':
      return 'Reconnecting to the camera…'
    case 'FAILED':
      return failureMessage(session.failure_code)
    default:
      return 'Off'
  }
}

/** Local midnight to the next midnight, in UTC milliseconds, for the day `ms` falls in. */
export function dayRange(ms: number): { start_ms: number; end_ms: number } {
  const day = new Date(ms)
  day.setHours(0, 0, 0, 0)
  const next = new Date(day)
  next.setDate(next.getDate() + 1)
  return { start_ms: day.getTime(), end_ms: next.getTime() - 1 }
}

export const dayLabel = (ms: number) =>
  new Date(ms).toLocaleDateString(undefined, {
    weekday: 'long',
    year: 'numeric',
    month: 'long',
    day: 'numeric',
  })

export const timeLabel = (ms: number) =>
  new Date(ms).toLocaleTimeString(undefined, {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
