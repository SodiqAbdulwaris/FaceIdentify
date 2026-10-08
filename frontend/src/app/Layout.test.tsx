import { act, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { useUi } from '@/state/ui'
import { page, renderApp, run, source } from '@/test/harness'

const RUNS = '/api/v1/processing-runs'
const library = { path: '/api/v1/sources', respond: page([source()]) }
const media = { path: /\/media$/, respond: 'bytes' }

afterEach(() => useUi.setState({ eventsStatus: 'connecting' }))

describe('the layout', () => {
  it('labels results that come from the uncalibrated development policy', async () => {
    renderApp('/library', [library, media, { path: RUNS, respond: page([run()]) }])

    const notice = await screen.findByRole('note')

    expect(notice).toHaveTextContent('Uncalibrated results.')
    expect(notice).toHaveTextContent('development-uncalibrated-v1')
    expect(notice).toHaveTextContent('not for real decisions')
  })

  it('says so when the policy cannot match a face to an existing person', async () => {
    const disabled = run({
      policy: {
        calibration_mode: 'UNCALIBRATED',
        decision_policy_version: 'buffalo-l-abstain-only-v1',
        calibrated: false,
        automatic_matching: false,
      },
    })
    renderApp('/library', [library, media, { path: RUNS, respond: page([disabled]) }])

    const notice = await screen.findByRole('note')

    expect(notice).toHaveTextContent('Automatic matching disabled.')
    expect(notice).toHaveTextContent('never matched to an existing person automatically')
    expect(notice).toHaveTextContent('Similarity scores are not probabilities')
  })

  it('shows only the matching notice when the policy is calibrated but cannot match', async () => {
    const disabled = run({
      policy: {
        calibration_mode: 'CALIBRATED',
        decision_policy_version: 'v2',
        calibrated: true,
        automatic_matching: false,
      },
    })
    renderApp('/library', [library, media, { path: RUNS, respond: page([disabled]) }])

    const notice = await screen.findByRole('note')

    expect(notice).toHaveTextContent('Automatic matching disabled.')
    expect(notice).not.toHaveTextContent('Uncalibrated results.')
  })

  it('shows no notice for a calibrated policy', async () => {
    const calibrated = run({
      policy: {
        calibration_mode: 'CALIBRATED',
        decision_policy_version: 'v1',
        calibrated: true,
        automatic_matching: true,
      },
    })
    renderApp('/library', [library, media, { path: RUNS, respond: page([calibrated]) }])

    await screen.findByText('beach.png')

    expect(screen.queryByRole('note')).toBeNull()
  })

  it('shows no notice before anything has been processed', async () => {
    const { calls } = renderApp('/library', [library, media])

    await screen.findByText('beach.png')

    expect(screen.queryByRole('note')).toBeNull()
    const latest = calls.find((c) => c.path === RUNS)!
    expect(latest.query.get('limit')).toBe('1') // only the newest run is asked for
  })

  it('names the places to go, and says whether live updates are on', async () => {
    renderApp('/library', [library, media])

    const nav = await screen.findByRole('navigation', { name: 'Main' })
    expect(within(nav).getByRole('link', { name: 'Library' })).toHaveAttribute('href', '/library')
    expect(within(nav).getByRole('link', { name: 'People' })).toHaveAttribute('href', '/identities')
    expect(screen.getByRole('status', { name: 'Live updates' })).toHaveTextContent('Reconnecting…')

    act(() => useUi.setState({ eventsStatus: 'open' }))

    expect(screen.getByRole('status', { name: 'Live updates' })).toHaveTextContent('Live')
  })

  it('sends the app root to the library', async () => {
    const { router } = renderApp('/', [library, media])

    await screen.findByRole('heading', { name: 'Library' })

    expect(router.state.location.pathname).toBe('/library')
  })
})
