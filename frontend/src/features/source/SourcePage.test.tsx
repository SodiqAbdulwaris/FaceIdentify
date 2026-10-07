import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { keys } from '@/api/keys'
import { apiError, failure, page, renderApp, run } from '@/test/harness'
import { detail, occurrence } from '@/test/fixtures'

const SOURCE = '/api/v1/sources/s1'
const media = { path: `${SOURCE}/media`, respond: 'bytes' }
const noFaces = { path: `${SOURCE}/occurrences`, respond: page([]) }
const noRuns = { path: `${SOURCE}/processing-runs`, respond: page([]) }

function open(handlers: Parameters<typeof renderApp>[1]) {
  return renderApp('/library/source/s1', handlers)
}

describe('a source', () => {
  it('shows the image, its facts and where it is kept', async () => {
    open([{ path: SOURCE, respond: detail() }, media, noFaces, noRuns])

    expect(await screen.findByRole('heading', { name: 'beach.png' })).toBeInTheDocument()
    expect(await screen.findByRole('img', { name: 'beach.png' })).toHaveAttribute(
      'src',
      expect.stringMatching(/^blob:/),
    )
    expect(screen.getByText('Not processed')).toBeInTheDocument()
    expect(screen.getByText(/800 × 600 px, 20 KB/)).toBeInTheDocument()
    expect(screen.getByText('In your library')).toBeInTheDocument()
    expect(screen.getByText('This image has not been processed.')).toBeInTheDocument()
    expect(screen.getByText(/Nobody yet/)).toBeInTheDocument()
  })

  it('boxes each face where it is and sends the person to the identity', async () => {
    open([
      { path: SOURCE, respond: detail({ processing_status: 'COMPLETED' }) },
      media,
      {
        path: `${SOURCE}/occurrences`,
        respond: page([
          occurrence({ id: 'o1', identity_id: 'i1' }),
          occurrence({
            id: 'o2',
            identity_id: 'i2',
            representative_observation: {
              id: 'ob2',
              source_id: 's1',
              bounding_box: { x: 0.6, y: 0.3, width: 0.2, height: 0.25 },
              face_crop: null,
            },
          }),
        ]),
      },
      noRuns,
    ])

    const first = await screen.findByRole('link', { name: 'Person 1: open' })
    const second = screen.getByRole('link', { name: 'Person 2: open' })

    expect(first).toHaveAttribute('href', '/identities/i1')
    expect(first).toHaveStyle({ left: '20%', top: '10%', width: '40%', height: '50%' })
    expect(second).toHaveAttribute('href', '/identities/i2')
    expect(second).toHaveStyle({ left: '60%', top: '30%', width: '20%', height: '25%' })
    const people = screen.getByRole('heading', { name: 'People in this image' }).parentElement!
    expect(within(people).getByRole('link', { name: 'Person 1' })).toHaveAttribute(
      'href',
      '/identities/i1',
    )
    expect(within(people).getByRole('link', { name: 'Person 2' })).toBeInTheDocument()
  })

  it('draws no box for a face whose observation is not shown, and still lists the person', async () => {
    open([
      { path: SOURCE, respond: detail({ processing_status: 'COMPLETED' }) },
      media,
      {
        path: `${SOURCE}/occurrences`,
        respond: page([occurrence({ representative_observation: null })]),
      },
      noRuns,
    ])

    const people = (await screen.findByRole('heading', { name: 'People in this image' }))
      .parentElement!

    expect(await within(people).findByRole('link', { name: 'Person 1' })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Person 1: open' })).toBeNull()
  })

  it('says so when a processed image has no faces', async () => {
    open([
      { path: SOURCE, respond: detail({ processing_status: 'COMPLETED' }) },
      media,
      noFaces,
      noRuns,
    ])

    expect(await screen.findByText('No faces were found in this image.')).toBeInTheDocument()
  })

  it('processes an image that has not been, and tells the person when that is refused', async () => {
    const user = userEvent.setup()
    const { calls } = open([
      { path: SOURCE, respond: detail() },
      media,
      noFaces,
      noRuns,
      { method: 'POST', path: `${SOURCE}/process`, status: 202, respond: run() },
    ])

    await user.click(await screen.findByRole('button', { name: 'Process' }))

    await waitFor(() =>
      expect(calls.some((c) => c.method === 'POST' && c.path.endsWith('/process'))).toBe(true),
    )
    expect(screen.queryByRole('status', { name: 'Source notice' })).toBeNull()
  })

  it('shows the backend message when processing is refused', async () => {
    const user = userEvent.setup()
    open([
      { path: SOURCE, respond: detail() },
      media,
      noFaces,
      noRuns,
      {
        method: 'POST',
        path: `${SOURCE}/process`,
        respond: () =>
          failure(409, 'SOURCE_NOT_PROCESSABLE', 'The source cannot be processed now.'),
      },
    ])

    await user.click(await screen.findByRole('button', { name: 'Process' }))

    expect(await screen.findByRole('status', { name: 'Source notice' })).toHaveTextContent(
      'The source cannot be processed now.',
    )
  })

  it('lets a queued or running run be cancelled, and says it is under way', async () => {
    const user = userEvent.setup()
    const { calls } = open([
      { path: SOURCE, respond: detail({ processing_status: 'RUNNING' }) },
      media,
      noFaces,
      { path: `${SOURCE}/processing-runs`, respond: page([run({ id: 'r9', state: 'RUNNING' })]) },
      {
        method: 'POST',
        path: '/api/v1/processing-runs/r9/cancel',
        status: 202,
        respond: run({ id: 'r9' }),
      },
    ])

    expect(await screen.findByText(/Processing is under way/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Process' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Try again' })).toBeNull()
    await user.click(await screen.findByRole('button', { name: 'Cancel processing' }))

    await waitFor(() =>
      expect(calls.some((c) => c.path === '/api/v1/processing-runs/r9/cancel')).toBe(true),
    )
  })

  it('offers a retry for a run that failed, and shows the history with links to each run', async () => {
    const user = userEvent.setup()
    const { calls } = open([
      { path: SOURCE, respond: detail({ processing_status: 'FAILED' }) },
      media,
      noFaces,
      {
        path: `${SOURCE}/processing-runs`,
        respond: page([
          run({ id: 'r2', state: 'FAILED', requested_at: '2026-02-02T10:00:00Z' }),
          run({ id: 'r1', state: 'CANCELLED', requested_at: '2026-01-01T10:00:00Z' }),
        ]),
      },
      {
        method: 'POST',
        path: '/api/v1/processing-runs/r2/retry',
        status: 202,
        respond: run({ id: 'r3' }),
      },
    ])

    const retry = await screen.findByRole('button', { name: 'Try again' })
    const history = screen.getByRole('heading', { name: 'Processing history' }).parentElement!
    expect(
      within(history)
        .getAllByRole('link')
        .map((l) => l.getAttribute('href')),
    ).toEqual(['/processing/r2', '/processing/r1'])
    await user.click(retry)

    await waitFor(() =>
      expect(calls.some((c) => c.path === '/api/v1/processing-runs/r2/retry')).toBe(true),
    )
    // a failed image can also be processed from scratch, but there is nothing to cancel
    expect(screen.getByRole('button', { name: 'Process' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Cancel processing' })).toBeNull()
    expect(screen.queryByText(/Processing is under way/)).toBeNull()
  })

  it('offers no retry when the file is gone, whatever happened before', async () => {
    open([
      { path: SOURCE, respond: detail({ availability: 'MISSING', processing_status: 'FAILED' }) },
      noFaces,
      { path: `${SOURCE}/processing-runs`, respond: page([run({ state: 'FAILED' })]) },
    ])

    await screen.findByText(/The file for this image is missing/)

    expect(screen.queryByRole('button', { name: 'Try again' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Process' })).toBeNull()
  })

  it('says so when the processing history cannot be loaded', async () => {
    open([
      { path: SOURCE, respond: detail() },
      media,
      noFaces,
      {
        path: `${SOURCE}/processing-runs`,
        ...apiError('LIBRARY_UNAVAILABLE', 'The library is not available.', 503),
      },
    ])

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'The processing history could not be loaded: The library is not available.',
    )
    expect(screen.queryByText('This image has not been processed.')).toBeNull()
  })

  it('says a referenced image stays where it was', async () => {
    open([
      { path: SOURCE, respond: detail({ storage_mode: 'REFERENCED' }) },
      media,
      noFaces,
      noRuns,
    ])

    expect(await screen.findByText('Where it was')).toBeInTheDocument()
    expect(screen.queryByText('In your library')).toBeNull()
  })

  it('refreshes the image, the library and the people after a request', async () => {
    const user = userEvent.setup()
    const { calls, queryClient } = open([
      { path: SOURCE, respond: detail() },
      media,
      noFaces,
      noRuns,
      { method: 'POST', path: `${SOURCE}/process`, status: 202, respond: run() },
    ])
    await screen.findByRole('button', { name: 'Process' })
    queryClient.setQueryData(keys.sources, { pages: [], pageParams: [] }) // the library list, cached
    queryClient.setQueryData(keys.identities, { pages: [], pageParams: [] })

    await user.click(screen.getByRole('button', { name: 'Process' }))

    await waitFor(() => expect(calls.filter((c) => c.path === SOURCE).length).toBeGreaterThan(1))
    expect(queryClient.getQueryState(keys.sources)?.isInvalidated).toBe(true)
    expect(queryClient.getQueryState(keys.identities)?.isInvalidated).toBe(true)
  })

  it('says when the file is missing and offers nothing that needs it', async () => {
    const { calls } = open([
      { path: SOURCE, respond: detail({ availability: 'MISSING', original: null }) },
      noFaces,
      noRuns,
    ])

    expect(await screen.findByText(/The file for this image is missing/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Process' })).toBeNull()
    expect(calls.some((c) => c.path.endsWith('/media'))).toBe(false)
  })

  it('tells the person when the image is not in the library', async () => {
    open([
      {
        path: SOURCE,
        ...apiError('SOURCE_NOT_FOUND', 'The requested source could not be found.', 404),
      },
    ])

    expect(
      await screen.findByRole('heading', { name: 'This image is not in your library' }),
    ).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Back to the library' })).toHaveAttribute(
      'href',
      '/library',
    )
  })

  it('shows the backend message for any other failure', async () => {
    open([
      { path: SOURCE, ...apiError('LIBRARY_UNAVAILABLE', 'The library is not available.', 503) },
    ])

    expect(
      await screen.findByRole('heading', { name: 'This image could not be loaded' }),
    ).toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent('The library is not available.')
  })

  it('shows a failed image load as such', async () => {
    open([
      { path: SOURCE, respond: detail() },
      {
        path: `${SOURCE}/media`,
        ...apiError('SOURCE_FILE_MISSING', 'The original file is not available.', 404),
      },
      noFaces,
      noRuns,
    ])

    expect(await screen.findByText('The image could not be loaded.')).toBeInTheDocument()
  })
})
