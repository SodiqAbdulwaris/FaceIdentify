import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { failure, page, renderApp, type Handler } from '@/test/harness'
import { occurrence } from '@/test/fixtures'
import { dayRange, failureMessage, sessionLabel } from './session'

const CAMERAS = '/api/v1/cameras'

const off = {
  state: null,
  job_id: null,
  frames: 0,
  dropped: 0,
  open_encounters: 0,
  encounters: 0,
  failure_code: null,
}

const camera = (over: Record<string, unknown> = {}) => ({
  id: 'c1',
  display_name: 'Front door',
  device_name: 'Integrated Camera',
  device_path: '@device_pnp_1',
  session: off,
  ...over,
})

const running = {
  ...off,
  state: 'RUNNING',
  frames: 40,
  dropped: 3,
  open_encounters: 1,
  encounters: 2,
}

beforeEach(() => {
  vi.stubGlobal(
    'URL',
    Object.assign(URL, { createObjectURL: () => 'blob:x', revokeObjectURL: () => {} }),
  )
})
afterEach(() => vi.unstubAllGlobals())

describe('cameras', () => {
  it('adds a camera the computer offers', async () => {
    const { calls } = renderApp('/cameras', [
      { path: CAMERAS, respond: [] },
      {
        path: `${CAMERAS}/devices`,
        respond: [{ name: 'Integrated Camera', path: '@device_pnp_1' }],
      },
      { method: 'POST', path: CAMERAS, respond: camera() },
    ])

    expect(await screen.findByText('No camera yet. Add one below.')).toBeInTheDocument()
    const form = screen.getByRole('form', { name: 'Add a camera' })
    await userEvent.selectOptions(
      within(form).getByRole('combobox'),
      await within(form).findByRole('option', { name: 'Integrated Camera' }),
    )
    await userEvent.type(within(form).getByRole('textbox', { name: 'Name' }), 'Front door')
    await userEvent.click(within(form).getByRole('button', { name: 'Add camera' }))

    const posted = calls.find((call) => call.method === 'POST' && call.path === CAMERAS)
    expect(posted?.body).toEqual({
      display_name: 'Front door',
      device_name: 'Integrated Camera',
      device_path: '@device_pnp_1',
    })
  })

  it('starts a camera and shows that it is on, on every screen', async () => {
    let session: Record<string, unknown> = off
    const { calls } = renderApp('/cameras', [
      { path: CAMERAS, respond: () => [camera({ session })] },
      { path: `${CAMERAS}/devices`, respond: [] },
      {
        method: 'POST',
        path: `${CAMERAS}/c1/start`,
        respond: () => {
          session = running
          return running
        },
      },
      { path: `${CAMERAS}/c1/preview`, respond: 'jpeg' },
    ])

    const card = await screen.findByRole('article', { name: 'Front door' })
    expect(within(card).getByRole('status')).toHaveTextContent('Off')
    expect(screen.queryByRole('status', { name: 'Camera on' })).not.toBeInTheDocument()

    await userEvent.click(within(card).getByRole('button', { name: 'Start' }))

    expect(await screen.findByRole('status', { name: 'Camera on' })).toHaveTextContent(
      'Camera on: Front door',
    )
    expect(within(card).getByRole('status', { name: 'Front door status' })).toHaveTextContent(
      'On: 1 in view, 2 recorded, 3 frames skipped',
    )
    expect(
      await within(card).findByRole('img', { name: 'What Front door sees now' }),
    ).toBeInTheDocument()
    expect(within(card).getByRole('button', { name: 'Stop' })).toBeInTheDocument()
    expect(within(card).queryByRole('button', { name: 'Remove' })).not.toBeInTheDocument()
    expect(calls.some((call) => call.path === `${CAMERAS}/c1/start`)).toBe(true)
  })

  it('says why a session ended, in words a person can act on', async () => {
    renderApp('/cameras', [
      {
        path: CAMERAS,
        respond: [camera({ session: { ...off, state: 'FAILED', failure_code: 'CAMERA_IN_USE' } })],
      },
      { path: `${CAMERAS}/devices`, respond: [] },
    ])

    expect(await screen.findByRole('status', { name: 'Front door status' })).toHaveTextContent(
      'Another program is using the camera.',
    )
  })

  it('shows a refused start', async () => {
    renderApp('/cameras', [
      { path: CAMERAS, respond: [camera()] },
      { path: `${CAMERAS}/devices`, respond: [] },
      {
        method: 'POST',
        path: `${CAMERAS}/c1/start`,
        respond: () => failure(409, 'CAMERA_BUSY', 'A camera session is running; stop it first.'),
      },
    ])

    await userEvent.click(await screen.findByRole('button', { name: 'Start' }))

    expect(await screen.findByRole('status', { name: 'Cameras notice' })).toHaveTextContent(
      'A camera session is running; stop it first.',
    )
  })

  it('removes a camera with its history only after asking', async () => {
    const { calls } = renderApp('/cameras', [
      { path: CAMERAS, respond: [camera()] },
      { path: `${CAMERAS}/devices`, respond: [] },
      { method: 'DELETE', path: `${CAMERAS}/c1`, respond: null, status: 204 },
    ])

    await userEvent.click(await screen.findByRole('button', { name: 'Remove with its history' }))
    expect(screen.getByText(/delete everything it recorded for good/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Keep it' })).toHaveFocus()
    await userEvent.click(screen.getByRole('button', { name: 'Delete for good' }))

    const removed = calls.find((call) => call.method === 'DELETE')
    expect(removed?.query.get('history')).toBe('true')
    expect(await screen.findByRole('status', { name: 'Cameras notice' })).toHaveTextContent(
      'Front door and everything it recorded were deleted.',
    )
  })

  it('keeps a camera when the question is answered no', async () => {
    const { calls } = renderApp('/cameras', [
      { path: CAMERAS, respond: [camera()] },
      { path: `${CAMERAS}/devices`, respond: [] },
    ])

    const remove = await screen.findByRole('button', { name: 'Remove' })
    await userEvent.click(remove)
    await userEvent.keyboard('{Escape}')

    expect(screen.getByRole('button', { name: 'Remove' })).toHaveFocus()
    expect(calls.some((call) => call.method === 'DELETE')).toBe(false)
  })
})

describe('camera history', () => {
  const at = new Date(2026, 10, 12, 9, 30).getTime()
  const visit = occurrence({
    id: 'v1',
    source_id: 'c1',
    kind: 'TRACK',
    start_ms: at,
    end_ms: at + 60_000,
    person: { id: 'p1', display_name: 'Ada' },
  })
  const unknown = {
    representation_id: 'r9',
    observation_id: 'ob9',
    bounding_box: { x: 0.25, y: 0.25, width: 0.5, height: 0.5 },
    likely: [],
    seen_at_ms: at + 120_000,
  }

  const history = (over: Handler[] = []): Handler[] => [
    { path: CAMERAS, respond: [camera()] },
    { path: '/api/v1/sources/c1/occurrences', respond: page([visit]) },
    { path: '/api/v1/sources/c1/unresolved-faces', respond: { items: [unknown] } },
    { path: /\/crop$/, respond: 'jpeg' },
    ...over,
  ]

  it('shows who the camera saw, by day, with the faces it kept', async () => {
    renderApp('/cameras/c1', history())

    const day = await screen.findByRole('region', {
      name: new Date(at).toLocaleDateString(undefined, {
        weekday: 'long',
        year: 'numeric',
        month: 'long',
        day: 'numeric',
      }),
    })
    expect(within(day).getByRole('link', { name: 'Ada' })).toHaveAttribute('href', '/identities/i1')
    expect(within(day).getByText('Not recognised')).toBeInTheDocument()
    expect(await within(day).findByRole('img', { name: "Ada's face" })).toBeInTheDocument()
  })

  it('deletes a day, after asking', async () => {
    const { calls } = renderApp(
      '/cameras/c1',
      history([
        {
          method: 'POST',
          path: `${CAMERAS}/c1/history/delete`,
          respond: { faces: 4, encounters: 1, complete: true },
        },
      ]),
    )

    await userEvent.click(await screen.findByRole('button', { name: 'Delete this day' }))
    await userEvent.click(screen.getByRole('button', { name: 'Delete for good' }))

    const deleted = calls.find((call) => call.path.endsWith('/history/delete'))
    expect(deleted?.body).toEqual(dayRange(at))
    expect(await screen.findByRole('status', { name: 'History notice' })).toHaveTextContent(
      'Deleted for good.',
    )
  })

  it('deletes the visits selected', async () => {
    const { calls } = renderApp(
      '/cameras/c1',
      history([
        {
          method: 'POST',
          path: `${CAMERAS}/c1/history/delete`,
          respond: { faces: 3, encounters: 1, complete: false },
        },
      ]),
    )

    const deleteSelected = await screen.findByRole('button', { name: 'Delete selected (0)' })
    expect(deleteSelected).toBeDisabled()
    await userEvent.click(screen.getByRole('checkbox'))
    await userEvent.click(screen.getByRole('button', { name: 'Delete selected (1)' }))

    const deleted = calls.find((call) => call.path.endsWith('/history/delete'))
    expect(deleted?.body).toEqual({ occurrence_ids: ['v1'] })
    expect(await screen.findByRole('status', { name: 'History notice' })).toHaveTextContent(
      'could not finish yet',
    )
  })

  it('says so when nothing was recorded', async () => {
    renderApp('/cameras/c1', [
      { path: CAMERAS, respond: [camera()] },
      { path: '/api/v1/sources/c1/occurrences', respond: page([]) },
      { path: '/api/v1/sources/c1/unresolved-faces', respond: { items: [] } },
    ])

    expect(await screen.findByText('Nothing recorded.')).toBeInTheDocument()
  })
})

describe('session words', () => {
  it('names every state', () => {
    expect(sessionLabel({ ...off, state: 'STARTING' })).toBe('Starting…')
    expect(sessionLabel({ ...off, state: 'RECONNECTING' })).toBe('Reconnecting to the camera…')
    expect(sessionLabel({ ...off, state: 'STOPPED' })).toBe('Off')
    expect(failureMessage('CAMERA_ACCESS_DENIED')).toContain('Let desktop apps access your camera')
    expect(failureMessage('CAMERA_DISCONNECTED')).toContain('privacy shutter')
    expect(failureMessage('RuntimeError')).toBe(
      'The camera session stopped unexpectedly (RuntimeError).',
    )
    expect(failureMessage(null)).toBe('The camera session stopped unexpectedly.')
  })
})
