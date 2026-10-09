import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { Reply, apiError, failure, page, renderApp, run, source } from '@/test/harness'

const chooseImages = vi.hoisted(() => vi.fn<() => Promise<string[]>>())
vi.mock('@/native/backend', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/native/backend')>()),
  chooseImages,
}))

const SOURCES = '/api/v1/sources'
const media = { path: /\/api\/v1\/sources\/[^/]+\/media/, respond: 'bytes' }

beforeEach(() => chooseImages.mockReset())

describe('the library', () => {
  it('lets go of an image address when the screen goes away', async () => {
    const { unmount } = renderApp('/library', [{ path: SOURCES, respond: page([source()]) }, media])
    await screen.findByRole('img', { name: 'beach.png' })
    const made = vi.mocked(URL.createObjectURL).mock.results.map((r) => r.value as string)

    unmount()

    expect(made.length).toBeGreaterThan(0)
    expect(vi.mocked(URL.revokeObjectURL).mock.calls.map((c) => c[0])).toEqual(
      expect.arrayContaining(made),
    )
  })

  it('invites the user to import images when there are none', async () => {
    renderApp('/library', [{ path: SOURCES, respond: page([]) }])

    expect(await screen.findByText('No images yet')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Import images' })).toBeEnabled()
  })

  it('lists the sources with their status and shows each image fetched with the token', async () => {
    const { calls } = renderApp('/library', [
      {
        path: SOURCES,
        respond: page([
          source({
            id: 's1',
            display_name: 'beach.png',
            processing_status: 'COMPLETED',
          }),
          source({
            id: 's2',
            display_name: 'party.jpg',
            processing_status: 'RUNNING',
          }),
        ]),
      },
      media,
    ])

    const beach = (await screen.findByText('beach.png')).closest('li')!
    const party = screen.getByText('party.jpg').closest('li')!

    expect(within(beach).getByText('Done')).toBeInTheDocument()
    expect(within(party).getByText('Processing')).toBeInTheDocument()
    expect(await within(beach).findByRole('img', { name: 'beach.png' })).toHaveAttribute(
      'src',
      expect.stringMatching(/^blob:/),
    )
    const mediaCall = calls.find((c) => c.path === '/api/v1/sources/s1/media')!
    expect(mediaCall.authorization).toBe('Bearer test-token')
    expect(calls.find((c) => c.path === SOURCES)!.query.get('state')).toBe('ACTIVE')
  })

  it('offers Process only where processing can start, and says when the file is missing', async () => {
    const { calls } = renderApp('/library', [
      {
        path: SOURCES,
        respond: page([
          source({ id: 's1', display_name: 'new.png' }),
          source({
            id: 's2',
            display_name: 'busy.png',
            processing_status: 'RUNNING',
          }),
          source({
            id: 's3',
            display_name: 'done.png',
            processing_status: 'COMPLETED',
          }),
          source({
            id: 's4',
            display_name: 'failed.png',
            processing_status: 'FAILED',
          }),
          source({
            id: 's5',
            display_name: 'gone.png',
            availability: 'MISSING',
          }),
        ]),
      },
      media,
    ])

    await screen.findByText('new.png')

    const buttons = screen.getAllByRole('button', { name: /^Process / }).map((b) => b.textContent)
    expect(screen.getAllByRole('button', { name: /^Process / })).toHaveLength(2) // new, failed
    expect(buttons).toEqual(['Process', 'Process'])
    expect(screen.getByRole('button', { name: 'Process new.png' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Process failed.png' })).toBeInTheDocument()
    const gone = screen.getByText('gone.png').closest('li')!
    expect(within(gone).getByText('The file is missing')).toBeInTheDocument()
    expect(calls.some((c) => c.path === '/api/v1/sources/s5/media')).toBe(false)
  })

  it('requests processing and refreshes the list', async () => {
    const user = userEvent.setup()
    let status = 'NOT_PROCESSED'
    const { calls } = renderApp('/library', [
      {
        path: SOURCES,
        respond: () => page([source({ processing_status: status })]),
      },
      media,
      {
        method: 'POST',
        path: '/api/v1/sources/s1/process',
        status: 202,
        respond: () => {
          status = 'PENDING'
          return run()
        },
      },
    ])

    await user.click(await screen.findByRole('button', { name: 'Process beach.png' }))

    expect(await screen.findByText('Queued')).toBeInTheDocument()
    expect(calls.filter((c) => c.method === 'POST' && c.path.endsWith('/process'))).toHaveLength(1)
    expect(screen.queryByRole('button', { name: 'Process beach.png' })).toBeNull()
  })

  it('disables Process for the image being requested, and only that one', async () => {
    const user = userEvent.setup()
    let answer: (reply: Reply) => void = () => undefined
    renderApp('/library', [
      {
        path: SOURCES,
        respond: page([
          source({ id: 's1', display_name: 'one.png' }),
          source({ id: 's2', display_name: 'two.png' }),
        ]),
      },
      media,
    ])
    const scripted = vi.mocked(fetch).getMockImplementation()!
    vi.mocked(fetch).mockImplementation(async (input, init) => {
      if (init?.method !== 'POST') return scripted(input, init)
      return new Promise((resolve) => {
        answer = (reply) =>
          resolve(new Response(JSON.stringify(reply.body), { status: reply.status }))
      })
    })

    await user.click(await screen.findByRole('button', { name: 'Process one.png' }))

    expect(screen.getByRole('button', { name: 'Process one.png' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Process two.png' })).toBeEnabled()
    answer(new Reply(202, run()))
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Process one.png' })).toBeEnabled(),
    )
  })

  it('keeps a button disabled while its own request is out, whatever is clicked next', async () => {
    const user = userEvent.setup()
    renderApp('/library', [
      {
        path: SOURCES,
        respond: page([
          source({ id: 's1', display_name: 'one.png' }),
          source({ id: 's2', display_name: 'two.png' }),
        ]),
      },
      media,
    ])
    const scripted = vi.mocked(fetch).getMockImplementation()!
    vi.mocked(fetch).mockImplementation(async (input, init) =>
      init?.method === 'POST' ? new Promise<Response>(() => undefined) : scripted(input, init),
    )

    await user.click(await screen.findByRole('button', { name: 'Process one.png' }))
    await user.click(screen.getByRole('button', { name: 'Process two.png' }))

    expect(screen.getByRole('button', { name: 'Process one.png' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Process two.png' })).toBeDisabled()
  })

  it('refreshes the newest run (and so the policy notice) after a request', async () => {
    const user = userEvent.setup()
    const { calls } = renderApp('/library', [
      { path: SOURCES, respond: page([source()]) },
      media,
      { method: 'POST', path: '/api/v1/sources/s1/process', status: 202, respond: run() },
    ])

    await user.click(await screen.findByRole('button', { name: 'Process beach.png' }))

    await waitFor(() =>
      expect(calls.filter((c) => c.path === '/api/v1/processing-runs').length).toBeGreaterThan(1),
    )
  })

  it('shows the backend message when processing cannot start', async () => {
    const user = userEvent.setup()
    renderApp('/library', [
      { path: SOURCES, respond: page([source()]) },
      media,
      {
        method: 'POST',
        path: '/api/v1/sources/s1/process',
        ...apiError('PROCESSING_UNAVAILABLE', 'No processing configuration is available.', 503),
      },
    ])

    await user.click(await screen.findByRole('button', { name: 'Process beach.png' }))

    expect(await screen.findByRole('status', { name: 'Library notice' })).toHaveTextContent(
      'No processing configuration is available.',
    )
  })

  it('pages through a long library on request', async () => {
    const user = userEvent.setup()
    const { calls } = renderApp('/library', [
      {
        path: SOURCES,
        respond: (call) =>
          call.query.get('cursor') === 'next-page'
            ? page([source({ id: 's2', display_name: 'second.png' })])
            : page([source({ id: 's1', display_name: 'first.png' })], 'next-page'),
      },
      media,
    ])

    await user.click(await screen.findByRole('button', { name: 'Load more' }))

    expect(await screen.findByText('second.png')).toBeInTheDocument()
    expect(screen.getByText('first.png')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Load more' })).toBeNull()
    expect(calls.filter((c) => c.path === SOURCES).map((c) => c.query.get('cursor'))).toEqual([
      null,
      'next-page',
    ])
  })

  it('says so when the library cannot be loaded', async () => {
    renderApp('/library', [
      {
        path: SOURCES,
        ...apiError('LIBRARY_UNAVAILABLE', 'The library is not available.', 503),
      },
    ])

    expect(await screen.findByRole('alert')).toHaveTextContent('The library is not available.')
  })
})

describe('importing', () => {
  it('imports each chosen image and reports how many worked and why one did not', async () => {
    const user = userEvent.setup()
    chooseImages.mockResolvedValue(['C:\\pictures\\a.png', 'C:\\pictures\\b.gif'])
    let imported = false
    const { calls } = renderApp('/library', [
      {
        path: SOURCES,
        respond: () => page(imported ? [source({ display_name: 'a.png' })] : []),
      },
      media,
      {
        method: 'POST',
        path: `${SOURCES}/import`,
        respond: (call) => {
          if ((call.body as { path: string }).path.endsWith('.gif')) {
            return failure(
              415,
              'MEDIA_FORMAT_UNSUPPORTED',
              'Only JPEG, PNG, BMP and WebP images are supported.',
            )
          }
          imported = true
          return new Reply(201, source({ display_name: 'a.png' }))
        },
      },
    ])

    await user.click(await screen.findByRole('button', { name: 'Import images' }))

    expect(await screen.findByRole('status', { name: 'Library notice' })).toHaveTextContent(
      'Imported 1 image. 1 could not be imported (b.gif: Only JPEG, PNG, BMP and WebP images are supported.).',
    )
    const imports = calls.filter((c) => c.path === `${SOURCES}/import`)
    expect(imports.map((c) => c.body)).toEqual([
      { path: 'C:\\pictures\\a.png', storage_mode: 'MANAGED' },
      { path: 'C:\\pictures\\b.gif', storage_mode: 'MANAGED' },
    ])
    await waitFor(() => expect(screen.getByText('a.png')).toBeInTheDocument())
  })

  it('reports a clean import without mentioning failures', async () => {
    const user = userEvent.setup()
    chooseImages.mockResolvedValue(['C:\\pictures\\a.png', 'C:\\pictures\\b.png'])
    renderApp('/library', [
      { path: SOURCES, respond: page([]) },
      media,
      {
        method: 'POST',
        path: `${SOURCES}/import`,
        status: 201,
        respond: source(),
      },
    ])

    await user.click(await screen.findByRole('button', { name: 'Import images' }))

    const notice = await screen.findByRole('status', {
      name: 'Library notice',
    })
    expect(notice).toHaveTextContent(/^Imported 2 images\.$/)
  })

  it('does nothing when the user cancels the file dialog', async () => {
    const user = userEvent.setup()
    chooseImages.mockResolvedValue([])
    const { calls } = renderApp('/library', [{ path: SOURCES, respond: page([]) }])

    await user.click(await screen.findByRole('button', { name: 'Import images' }))

    await waitFor(() => expect(screen.getByRole('button', { name: 'Import images' })).toBeEnabled())
    expect(calls.some((c) => c.path.endsWith('/import'))).toBe(false)
    expect(screen.queryByRole('status', { name: 'Library notice' })).toBeNull()
  })

  it('moves an image to the recycle bin with one click and refreshes the library', async () => {
    const user = userEvent.setup()
    let recycled = false
    const { calls, queryClient } = renderApp('/library', [
      {
        path: SOURCES,
        respond: () => page(recycled ? [] : [source({ id: 's1', display_name: 'beach.png' })]),
      },
      {
        method: 'DELETE',
        path: `${SOURCES}/s1`,
        status: 204,
        respond: () => {
          recycled = true
          return null
        },
      },
      media,
    ])

    queryClient.setQueryData(['source', 's1'], { state: 'ACTIVE' }) // as if its page was visited
    await screen.findByRole('button', { name: 'Move beach.png to the recycle bin' })
    expect(screen.queryByRole('button', { name: /permanently/ })).toBeNull() // only from the bin
    await user.click(screen.getByRole('button', { name: 'Move beach.png to the recycle bin' }))

    expect(await screen.findByText('No images yet')).toBeInTheDocument()
    expect(calls.some((c) => c.method === 'DELETE' && c.path === `${SOURCES}/s1`)).toBe(true)
    // a cached page for this image must not keep showing it as active
    expect(queryClient.getQueryState(['source', 's1'])?.isInvalidated).toBe(true)
  })

  it('shows what was recycled in the recycle bin, where it can be restored, not processed', async () => {
    const user = userEvent.setup()
    let restored = false
    const { calls } = renderApp('/library', [
      {
        path: SOURCES,
        respond: (call) =>
          call.query.get('state') === 'RECYCLED'
            ? page(restored ? [] : [source({ id: 's1', display_name: 'beach.png' })])
            : page([]),
      },
      {
        method: 'POST',
        path: `${SOURCES}/s1/restore`,
        respond: () => {
          restored = true
          return source({ id: 's1' })
        },
      },
      media,
    ])
    await screen.findByText('No images yet')

    await user.click(screen.getByRole('button', { name: 'Recycle bin' }))

    expect(await screen.findByRole('heading', { name: 'Recycle bin' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Import images' })).toBeNull()
    expect(screen.queryByRole('button', { name: /Process/ })).toBeNull()
    await screen.findByRole('button', { name: 'Restore beach.png' })
    expect(screen.queryByRole('button', { name: /to the recycle bin/ })).toBeNull() // already there
    await user.click(screen.getByRole('button', { name: 'Restore beach.png' }))
    expect(await screen.findByText('The recycle bin is empty')).toBeInTheDocument()
    expect(calls.some((c) => c.method === 'POST' && c.path === `${SOURCES}/s1/restore`)).toBe(true)
    await user.click(screen.getByRole('button', { name: 'Library' }))
    expect(await screen.findByRole('heading', { name: 'Library' })).toBeInTheDocument()
  })

  describe('deleting an image in the recycle bin for good', () => {
    const inTheBin = (permanent: Record<string, unknown>) => {
      let gone = false
      return renderApp('/library', [
        {
          path: SOURCES,
          respond: (call) =>
            call.query.get('state') === 'RECYCLED'
              ? page(gone ? [] : [source({ id: 's1', display_name: 'beach.png' })])
              : page([]),
        },
        {
          method: 'POST',
          path: `${SOURCES}/s1/permanent-delete`,
          ...permanent,
          respond: () => {
            gone = permanent.status === 204
            return permanent.status === 204 ? null : { state: 'DELETING', outstanding: ['x'] }
          },
        },
        media,
      ])
    }

    it('asks first, can be cancelled, and then removes the image', async () => {
      const user = userEvent.setup()
      const { calls } = inTheBin({ status: 204 })
      await user.click(await screen.findByRole('button', { name: 'Recycle bin' }))
      const open = () => screen.findByRole('button', { name: 'Delete beach.png permanently' })

      await user.click(await open())
      expect(screen.getByRole('alertdialog')).toHaveTextContent('cannot be brought back')
      await user.click(screen.getByRole('button', { name: 'Keep it' }))
      expect(screen.queryByRole('alertdialog')).toBeNull()
      expect(calls.some((c) => c.path.endsWith('/permanent-delete'))).toBe(false) // nothing sent yet

      await user.click(await open())
      await user.click(screen.getByRole('button', { name: 'Yes, delete it' }))

      expect(await screen.findByText('The recycle bin is empty')).toBeInTheDocument()
      expect(calls.filter((c) => c.path.endsWith('/permanent-delete'))).toHaveLength(1)
    })

    it('says so when part of the deletion could not finish yet', async () => {
      const user = userEvent.setup()
      inTheBin({ status: 202 })
      await user.click(await screen.findByRole('button', { name: 'Recycle bin' }))

      await user.click(await screen.findByRole('button', { name: 'Delete beach.png permanently' }))
      await user.click(screen.getByRole('button', { name: 'Yes, delete it' }))

      expect(await screen.findByRole('status', { name: 'Library notice' })).toHaveTextContent(
        'tried again the next time the app starts',
      )
    })

    it('says why it was refused and leaves the image where it is', async () => {
      const user = userEvent.setup()
      renderApp('/library', [
        {
          path: SOURCES,
          respond: (call) =>
            call.query.get('state') === 'RECYCLED'
              ? page([source({ id: 's1', display_name: 'beach.png' })])
              : page([]),
        },
        {
          method: 'POST',
          path: `${SOURCES}/s1/permanent-delete`,
          ...apiError('SOURCE_BUSY', 'The source is being processed; cancel that first.', 409),
        },
        media,
      ])
      await user.click(await screen.findByRole('button', { name: 'Recycle bin' }))

      await user.click(await screen.findByRole('button', { name: 'Delete beach.png permanently' }))
      await user.click(screen.getByRole('button', { name: 'Yes, delete it' }))

      expect(await screen.findByRole('status', { name: 'Library notice' })).toHaveTextContent(
        'being processed',
      )
      expect(screen.getByRole('img', { name: 'beach.png' })).toBeInTheDocument()
    })
  })

  it('says why an image could not be recycled, and leaves it where it is', async () => {
    const user = userEvent.setup()
    renderApp('/library', [
      { path: SOURCES, respond: page([source({ id: 's1', display_name: 'beach.png' })]) },
      {
        method: 'DELETE',
        path: `${SOURCES}/s1`,
        ...apiError('SOURCE_BUSY', 'The source is being processed; cancel that first.', 409),
      },
      media,
    ])

    await user.click(
      await screen.findByRole('button', { name: 'Move beach.png to the recycle bin' }),
    )

    expect(await screen.findByRole('status', { name: 'Library notice' })).toHaveTextContent(
      'being processed',
    )
    expect(screen.getByRole('img', { name: 'beach.png' })).toBeInTheDocument()
  })
})
