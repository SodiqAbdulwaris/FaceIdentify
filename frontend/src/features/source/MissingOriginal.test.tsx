import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { apiError, page, renderApp } from '@/test/harness'
import { detail } from '@/test/fixtures'

const choosePicture = vi.hoisted(() => vi.fn<() => Promise<string | null>>())
const shell = vi.hoisted(() => ({ on: true }))
vi.mock('@/native/backend', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/native/backend')>()),
  inShell: () => shell.on,
  choosePicture,
}))

const SOURCE = '/api/v1/sources/s1'
const noFaces = { path: `${SOURCE}/occurrences`, respond: page([]) }
const noRuns = { path: `${SOURCE}/processing-runs`, respond: page([]) }
const missing = (over: Record<string, unknown> = {}) =>
  detail({
    availability: 'MISSING',
    availability_reason: 'REFERENCED_FILE_MISSING',
    original: null,
    ...over,
  })

beforeEach(() => {
  choosePicture.mockReset()
  shell.on = true
})

describe('a missing original', () => {
  it('rechecks the file and shows the image again when it is back', async () => {
    const { calls } = renderApp('/library/source/s1', [
      { path: SOURCE, respond: missing() },
      { method: 'POST', path: `${SOURCE}/recheck`, respond: detail() },
      { path: `${SOURCE}/media`, respond: 'bytes' },
      noFaces,
      noRuns,
    ])

    await userEvent.setup().click(await screen.findByRole('button', { name: 'Recheck file' }))

    expect(await screen.findByRole('status', { name: 'Source notice' })).toHaveTextContent(
      'The file is back.',
    )
    expect(await screen.findByRole('img', { name: 'beach.png' })).toBeInTheDocument()
    expect(calls.filter((c) => c.path === `${SOURCE}/recheck`)).toHaveLength(1)
  })

  it('says why when the file is still not the original', async () => {
    renderApp('/library/source/s1', [
      { path: SOURCE, respond: missing() },
      {
        method: 'POST',
        path: `${SOURCE}/recheck`,
        respond: missing({ availability_reason: 'REFERENCED_CONTENT_CHANGED' }),
      },
      noFaces,
      noRuns,
    ])

    await userEvent.setup().click(await screen.findByRole('button', { name: 'Recheck file' }))

    expect(await screen.findByRole('status', { name: 'Source notice' })).toHaveTextContent(
      /Still missing\. A different file is now where this image was/,
    )
  })

  it('locates a referenced original with the native dialog', async () => {
    choosePicture.mockResolvedValue('D:/albums/beach.png')
    const { calls } = renderApp('/library/source/s1', [
      { path: SOURCE, respond: missing({ storage_mode: 'REFERENCED' }) },
      {
        method: 'POST',
        path: `${SOURCE}/relink`,
        respond: detail({ storage_mode: 'REFERENCED' }),
      },
      { path: `${SOURCE}/media`, respond: 'bytes' },
      noFaces,
      noRuns,
    ])

    await userEvent.setup().click(await screen.findByRole('button', { name: 'Locate original…' }))

    await waitFor(() => expect(calls.some((c) => c.path === `${SOURCE}/relink`)).toBe(true))
    expect(calls.find((c) => c.path === `${SOURCE}/relink`)?.body).toEqual({
      path: 'D:/albums/beach.png',
    })
    expect(await screen.findByRole('status', { name: 'Source notice' })).toHaveTextContent(
      'The file is back.',
    )
  })

  it('shows the refusal when the located file is different media', async () => {
    choosePicture.mockResolvedValue('D:/albums/other.png')
    renderApp('/library/source/s1', [
      { path: SOURCE, respond: missing({ storage_mode: 'REFERENCED' }) },
      {
        method: 'POST',
        path: `${SOURCE}/relink`,
        ...apiError('SOURCE_RELINK_MISMATCH', 'That file is not the original.', 409),
      },
      noFaces,
      noRuns,
    ])

    await userEvent.setup().click(await screen.findByRole('button', { name: 'Locate original…' }))

    expect(await screen.findByRole('status', { name: 'Source notice' })).toHaveTextContent(
      'That file is not the original.',
    )
  })

  it('does nothing when the dialog is cancelled', async () => {
    choosePicture.mockResolvedValue(null)
    const { calls } = renderApp('/library/source/s1', [
      { path: SOURCE, respond: missing({ storage_mode: 'REFERENCED' }) },
      noFaces,
      noRuns,
    ])

    await userEvent.setup().click(await screen.findByRole('button', { name: 'Locate original…' }))

    await waitFor(() => expect(choosePicture).toHaveBeenCalled())
    expect(calls.some((c) => c.path.endsWith('/relink'))).toBe(false)
    expect(screen.queryByRole('status', { name: 'Source notice' })).toBeNull()
  })

  it('offers no Locate for a managed original', async () => {
    renderApp('/library/source/s1', [{ path: SOURCE, respond: missing() }, noFaces, noRuns])
    expect(await screen.findByRole('button', { name: 'Recheck file' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Locate original…' })).toBeNull()
  })

  it('offers no Locate outside the desktop app', async () => {
    shell.on = false
    renderApp('/library/source/s1', [
      { path: SOURCE, respond: missing({ storage_mode: 'REFERENCED' }) },
      noFaces,
      noRuns,
    ])
    expect(await screen.findByRole('button', { name: 'Recheck file' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Locate original…' })).toBeNull()
  })
})
