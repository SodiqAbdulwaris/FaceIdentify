import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { detail } from '@/test/fixtures'
import { apiError, failure, renderApp, run } from '@/test/harness'

// look again quickly while work is under way (the real wait is seconds)
vi.mock('../status', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../status')>()),
  ACTIVE_REFETCH_MS: 40,
}))

const RUN = '/api/v1/processing-runs/r1'
const OWNER = { path: '/api/v1/sources/s1', respond: detail() }
const job = (over: Record<string, unknown> = {}) => ({
  id: 'j1',
  state: 'RUNNING',
  priority: 'INTERACTIVE',
  attempt_number: 1,
  progress: null,
  ...over,
})

describe('a processing run', () => {
  it('shows a finished run: when, the job, and that its policy is uncalibrated', async () => {
    renderApp('/processing/r1', [
      {
        path: RUN,
        respond: run({
          state: 'COMPLETED',
          requested_at: '2026-01-01T10:00:00Z',
          started_at: '2026-01-01T10:00:05Z',
          completed_at: '2026-01-01T10:00:09Z',
          job: job({ state: 'COMPLETED' }),
        }),
      },
    ])

    expect(await screen.findByRole('heading', { name: 'Processing' })).toBeInTheDocument()
    expect(screen.getByText('Done')).toBeInTheDocument()
    expect(screen.getByText('Requested')).toBeInTheDocument()
    expect(screen.getByText('Started')).toBeInTheDocument()
    expect(screen.getByText('Finished')).toBeInTheDocument()
    expect(screen.queryByText('Failed', { selector: 'dt' })).toBeNull() // no failure time to show
    expect(screen.getByText('completed, attempt 1')).toBeInTheDocument()
    expect(screen.getByText('development-uncalibrated-v1 (uncalibrated)')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '← The image' })).toHaveAttribute(
      'href',
      '/library/source/s1',
    )
    expect(screen.queryByRole('button')).toBeNull() // nothing to cancel or retry
    expect(screen.queryByText(/This is under way/)).toBeNull()
  })

  it('says a running run is under way, with its progress, and offers to cancel it', async () => {
    const user = userEvent.setup()
    const { calls } = renderApp('/processing/r1', [
      {
        path: RUN,
        respond: run({
          state: 'RUNNING',
          job: job({ progress: { completed: 2, total: 5 } }),
        }),
      },
      { method: 'POST', path: `${RUN}/cancel`, status: 202, respond: run() },
    ])

    expect(await screen.findByText(/This is under way\./)).toHaveTextContent('2 of 5 done.')
    expect(screen.queryByRole('button', { name: 'Try again' })).toBeNull()
    await user.click(screen.getByRole('button', { name: 'Cancel processing' }))

    await waitFor(() => expect(calls.some((c) => c.path === `${RUN}/cancel`)).toBe(true))
  })

  it('reports progress without a total', async () => {
    renderApp('/processing/r1', [
      {
        path: RUN,
        respond: run({ state: 'RUNNING', job: job({ progress: { completed: 3, total: null } }) }),
      },
    ])

    expect(await screen.findByText(/This is under way\./)).toHaveTextContent('3 done.')
  })

  it('explains a failure plainly, links the earlier attempt, and offers a retry', async () => {
    const user = userEvent.setup()
    const { calls } = renderApp('/processing/r1', [
      {
        path: RUN,
        respond: run({
          state: 'FAILED',
          parent_run_id: 'r0',
          failure_code: 'INFERENCE_FAILED',
          failed_at: '2026-01-01T10:00:09Z',
        }),
      },
      { method: 'POST', path: `${RUN}/retry`, status: 202, respond: run({ id: 'r2' }) },
      OWNER,
    ])

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'It stopped without a result (INFERENCE_FAILED). Nothing from this attempt was kept.',
    )
    expect(screen.getByRole('link', { name: 'the earlier attempt' })).toHaveAttribute(
      'href',
      '/processing/r0',
    )
    expect(screen.getByText('Failed', { selector: 'dt' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Cancel processing' })).toBeNull()
    await user.click(await screen.findByRole('button', { name: 'Try again' }))

    await waitFor(() => expect(calls.some((c) => c.path === `${RUN}/retry`)).toBe(true))
  })

  it('offers no retry while the image is in the recycle bin', async () => {
    const { calls } = renderApp('/processing/r1', [
      { path: RUN, respond: run({ state: 'FAILED' }) },
      { path: '/api/v1/sources/s1', respond: detail({ state: 'RECYCLED' }) },
    ])

    await screen.findByRole('heading', { name: 'Processing' })
    await waitFor(() => expect(calls.some((c) => c.path === '/api/v1/sources/s1')).toBe(true))
    await new Promise((resolve) => setTimeout(resolve, 50)) // let the answer reach the screen
    expect(screen.queryByRole('button', { name: 'Try again' })).toBeNull()
  })

  it('shows the backend message when a request is refused', async () => {
    const user = userEvent.setup()
    renderApp('/processing/r1', [
      { path: RUN, respond: run({ state: 'FAILED' }) },
      OWNER,
      {
        method: 'POST',
        path: `${RUN}/retry`,
        respond: () => failure(409, 'RUN_NOT_RETRYABLE', 'The processing run cannot be retried.'),
      },
    ])

    await user.click(await screen.findByRole('button', { name: 'Try again' }))

    expect(await screen.findByRole('status', { name: 'Processing notice' })).toHaveTextContent(
      'The processing run cannot be retried.',
    )
  })

  it('says when the run does not exist, and when anything else goes wrong', async () => {
    const { unmount } = renderApp('/processing/r1', [
      {
        path: RUN,
        ...apiError('RUN_NOT_FOUND', 'The requested processing run could not be found.', 404),
      },
    ])
    expect(
      await screen.findByRole('heading', { name: 'This processing run does not exist' }),
    ).toBeInTheDocument()
    unmount()

    renderApp('/processing/r1', [
      { path: RUN, ...apiError('LIBRARY_UNAVAILABLE', 'The library is not available.', 503) },
    ])
    expect(
      await screen.findByRole('heading', { name: 'This processing run could not be loaded' }),
    ).toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent('The library is not available.')
  })

  it('keeps looking while the run is under way, and stops once it is over', async () => {
    let state = 'RUNNING'
    const { calls } = renderApp('/processing/r1', [{ path: RUN, respond: () => run({ state }) }])
    await screen.findByText(/This is under way\./)

    state = 'COMPLETED' // (the live connection is down: nothing told the page)
    await screen.findByText('Done')

    const looked = calls.filter((c) => c.path === RUN).length
    await new Promise((resolve) => setTimeout(resolve, 200))
    expect(calls.filter((c) => c.path === RUN).length).toBe(looked) // no more once it is over
  })
})
