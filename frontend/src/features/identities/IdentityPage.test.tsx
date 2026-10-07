import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { apiError, page, renderApp } from '@/test/harness'
import { identity, occurrence } from '@/test/fixtures'

const PERSON = '/api/v1/identities/i1'
const media = { path: /\/media$/, respond: 'bytes' }

describe('a person', () => {
  it('shows how often they appear and every image they appear in, each a way to that image', async () => {
    renderApp('/identities/i1', [
      { path: PERSON, respond: identity({ occurrence_count: 2, source_count: 2 }) },
      {
        path: `${PERSON}/occurrences`,
        respond: page([
          occurrence({ id: 'o1', source_id: 's1', source_display_name: 'beach.png' }),
          occurrence({
            id: 'o2',
            source_id: 's2',
            source_display_name: 'party.jpg',
            representative_observation: null,
          }),
        ]),
      },
      media,
    ])

    expect(await screen.findByRole('heading', { name: 'Person I1' })).toBeInTheDocument()
    expect(screen.getByText(/Appears 2 times in 2 images\./)).toBeInTheDocument()
    expect(screen.getByText(/Nobody has named this person yet\./)).toBeInTheDocument()
    const beach = await screen.findByRole('link', { name: /beach\.png/ })
    const party = screen.getByRole('link', { name: /party\.jpg/ })
    expect(beach).toHaveAttribute('href', '/library/source/s1')
    expect(party).toHaveAttribute('href', '/library/source/s2')
    expect(
      await within(beach).findByRole('img', { name: 'Person I1 in beach.png' }),
    ).toBeInTheDocument()
    expect(within(party).queryByRole('img')).toBeNull()
  })

  it('says once, and one image, for a single appearance', async () => {
    renderApp('/identities/i1', [
      { path: PERSON, respond: identity() },
      { path: `${PERSON}/occurrences`, respond: page([occurrence()]) },
      media,
    ])

    expect(await screen.findByText(/Appears once in 1 image\./)).toBeInTheDocument()
  })

  it('pages through many appearances on request', async () => {
    const user = userEvent.setup()
    const { calls } = renderApp('/identities/i1', [
      { path: PERSON, respond: identity({ occurrence_count: 2, source_count: 2 }) },
      {
        path: `${PERSON}/occurrences`,
        respond: (call) =>
          call.query.get('cursor') === 'more'
            ? page([occurrence({ id: 'o2', source_id: 's2', source_display_name: 'second.png' })])
            : page([occurrence({ id: 'o1', source_display_name: 'first.png' })], 'more'),
      },
      media,
    ])

    await user.click(await screen.findByRole('button', { name: 'Load more' }))

    expect(await screen.findByRole('link', { name: /second\.png/ })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /first\.png/ })).toBeInTheDocument()
    const cursors = calls
      .filter((c) => c.path.endsWith('/occurrences'))
      .map((c) => c.query.get('cursor'))
    expect(cursors).toEqual([null, 'more'])
  })

  it('says so when there are no appearances to show', async () => {
    renderApp('/identities/i1', [
      { path: PERSON, respond: identity({ occurrence_count: 0, source_count: 0 }) },
      { path: `${PERSON}/occurrences`, respond: page([]) },
    ])

    expect(await screen.findByText('No appearances to show.')).toBeInTheDocument()
  })

  it('says when the person is not in the library, and when anything else goes wrong', async () => {
    const { unmount, calls } = renderApp('/identities/i1', [
      {
        path: PERSON,
        ...apiError('IDENTITY_NOT_FOUND', 'The requested identity could not be found.', 404),
      },
    ])
    expect(
      await screen.findByRole('heading', { name: 'This person is not in your library' }),
    ).toBeInTheDocument()
    expect(calls.some((c) => c.path.endsWith('/occurrences'))).toBe(false) // nothing to look up
    expect(screen.getByRole('link', { name: 'Back to people' })).toHaveAttribute(
      'href',
      '/identities',
    )
    unmount()

    renderApp('/identities/i1', [
      { path: PERSON, ...apiError('LIBRARY_UNAVAILABLE', 'The library is not available.', 503) },
    ])
    expect(
      await screen.findByRole('heading', { name: 'This person could not be loaded' }),
    ).toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent('The library is not available.')
  })

  it('shows the backend message when the appearances cannot be loaded', async () => {
    renderApp('/identities/i1', [
      { path: PERSON, respond: identity() },
      {
        path: `${PERSON}/occurrences`,
        ...apiError('LIBRARY_UNAVAILABLE', 'The library is not available.', 503),
      },
    ])

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'The appearances could not be loaded: The library is not available.',
    )
  })
})
