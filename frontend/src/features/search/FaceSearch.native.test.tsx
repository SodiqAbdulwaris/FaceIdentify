import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { renderApp } from '@/test/harness'

const choosePicture = vi.hoisted(() => vi.fn<() => Promise<string | null>>())
vi.mock('@/native/backend', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/native/backend')>()),
  inShell: () => true,
  choosePicture,
}))

const FACE = '/api/v1/search/face'
const answer = { faces: [], ranking: { plan: 'FACE_QUERY', policy_version: 'v', similarity: 'x' } }

beforeEach(() => choosePicture.mockReset())

describe('face search in the desktop app', () => {
  it('searches with the path of the picture chosen in the native dialog, sending no bytes', async () => {
    choosePicture.mockResolvedValue('C:/pictures/a.png')
    const { calls } = renderApp('/search', [{ method: 'POST', path: FACE, respond: answer }])

    await userEvent.setup().click(screen.getByRole('button', { name: 'Choose a picture' }))

    await waitFor(() => expect(calls.filter((c) => c.path === FACE)).toHaveLength(1))
    expect(calls.find((c) => c.path === FACE)?.body).toEqual({ path: 'C:/pictures/a.png' })
    await screen.findByText('No face was found in this picture.')
  })

  it('does nothing when the dialog is cancelled', async () => {
    choosePicture.mockResolvedValue(null)
    const { calls } = renderApp('/search', [])

    await userEvent.setup().click(screen.getByRole('button', { name: 'Choose a picture' }))

    await waitFor(() => expect(choosePicture).toHaveBeenCalledTimes(1))
    expect(calls.filter((c) => c.path === FACE)).toHaveLength(0)
  })
})
