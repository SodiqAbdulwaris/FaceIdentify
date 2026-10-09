import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { apiError, page, renderApp } from '@/test/harness'
import { identity } from '@/test/fixtures'

const PEOPLE = '/api/v1/identities'
const media = { path: /\/media$/, respond: 'bytes' }
const face = {
  id: 'ob1',
  source_id: 's1',
  bounding_box: { x: 0.1, y: 0.1, width: 0.3, height: 0.3 },
  face_crop: null,
}

const person = (over: Record<string, unknown> = {}) => ({
  id: 'p1',
  display_name: 'Ada',
  revision: 1,
  identity_count: 0,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  ...over,
})

describe('people', () => {
  it('lists the named people of every page, not only the first', async () => {
    renderApp('/identities', [
      { path: PEOPLE, respond: page([identity({ id: 'a1' })]) },
      {
        path: '/api/v1/people',
        respond: (call) =>
          call.query.get('cursor') === 'more'
            ? page([person({ id: 'p2', display_name: 'Bob' })])
            : page([person({ id: 'p1', display_name: 'Ada' })], 'more'),
      },
      media,
    ])

    const section = await screen.findByRole('region', { name: 'People without a remembered face' })

    expect(await within(section).findByText('Bob')).toBeInTheDocument()
    expect(within(section).getByText('Ada')).toBeInTheDocument()
  })

  it('also lists a named person the app remembers no face for, and says it cannot recognise them', async () => {
    renderApp('/identities', [
      { path: PEOPLE, respond: page([identity({ id: 'a1' })]) },
      {
        path: '/api/v1/people',
        respond: page([
          person({ id: 'p1', display_name: 'Ada', identity_count: 0 }),
          person({ id: 'p2', display_name: 'Bob', identity_count: 2 }),
        ]),
      },
      media,
    ])

    const section = await screen.findByRole('region', { name: 'People without a remembered face' })

    expect(within(section).getByText('Ada')).toBeInTheDocument()
    expect(within(section).queryByText('Bob')).toBeNull() // Bob still has faces: he is in the list
    expect(within(section).getByText(/cannot recognise them/)).toBeInTheDocument()
  })

  it('invites the user to process images when nobody is known yet', async () => {
    renderApp('/identities', [{ path: PEOPLE, respond: page([]) }])

    expect(await screen.findByText('Nobody yet')).toBeInTheDocument()
  })

  it('lists each person with their face, how often and in how many images they appear', async () => {
    renderApp('/identities', [
      {
        path: PEOPLE,
        respond: page([
          identity({
            id: 'a1',
            occurrence_count: 3,
            source_count: 2,
            representative_observation: face,
          }),
          identity({ id: 'b2', occurrence_count: 1, source_count: 1 }),
        ]),
      },
      media,
    ])

    const first = await screen.findByRole('link', { name: /Person A1/ })
    const second = screen.getByRole('link', { name: /Person B2/ })

    expect(first).toHaveAttribute('href', '/identities/a1')
    expect(within(first).getByText('3 appearances in 2 images')).toBeInTheDocument()
    expect(await within(first).findByRole('img', { name: "Person A1's face" })).toBeInTheDocument()
    expect(second).toHaveAttribute('href', '/identities/b2')
    expect(within(second).getByText('1 appearance in 1 image')).toBeInTheDocument()
    expect(within(second).queryByRole('img')).toBeNull() // no face to show yet
  })

  it('pages through many people on request', async () => {
    const user = userEvent.setup()
    const { calls } = renderApp('/identities', [
      {
        path: PEOPLE,
        respond: (call) =>
          call.query.get('cursor') === 'more'
            ? page([identity({ id: 'c3' })])
            : page([identity({ id: 'a1' })], 'more'),
      },
    ])

    await user.click(await screen.findByRole('button', { name: 'Load more' }))

    expect(await screen.findByRole('link', { name: /Person C3/ })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Person A1/ })).toBeInTheDocument()
    expect(calls.filter((c) => c.path === PEOPLE).map((c) => c.query.get('cursor'))).toEqual([
      null,
      'more',
    ])
  })

  it('shows the backend message when people cannot be loaded', async () => {
    renderApp('/identities', [
      { path: PEOPLE, ...apiError('LIBRARY_UNAVAILABLE', 'The library is not available.', 503) },
    ])

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'People could not be loaded: The library is not available.',
    )
  })
})
