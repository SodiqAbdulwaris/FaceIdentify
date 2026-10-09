import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { apiError, renderApp } from '@/test/harness'
import { occurrence } from '@/test/fixtures'

const SEARCH = '/api/v1/search'
const media = { path: /\/media$/, respond: 'bytes' }

const answer = (over: Record<string, unknown> = {}) => ({
  query: 'ada',
  results: { people: [], identities: [], sources: [], occurrences: [] },
  coverage: { sources: 3, processed: 3, not_processed: 0 },
  ranking: {
    plan: 'NAME_LOOKUP',
    ranker: 'rule-v1',
    recycled: 'include',
    types: [],
  },
  ...over,
})

const ada = {
  id: 'p1',
  display_name: 'Ada',
  match: 'EXACT',
  identity_ids: ['i1'],
  occurrence_count: 2,
  source_count: 2,
  visual_support: true,
  biometric_memory_forgotten: false,
}

describe('search', () => {
  it('asks nothing until a word is typed, then shows people, images and appearances', async () => {
    const user = userEvent.setup()
    const { calls } = renderApp('/search', [
      {
        path: SEARCH,
        respond: answer({
          results: {
            people: [ada],
            identities: [
              {
                id: 'abc',
                label: 'Person ABC123',
                match: 'PREFIX',
                occurrence_count: 1,
                source_count: 1,
              },
            ],
            sources: [
              {
                id: 's1',
                display_name: 'ada.png',
                match: 'PREFIX',
                state: 'ACTIVE',
                source_recycled: false,
                processed: true,
              },
            ],
            occurrences: [occurrence({ source_recycled: true })],
          },
        }),
      },
      media,
    ])
    expect(screen.getByRole('button', { name: 'Search' })).toBeDisabled()
    expect(calls.filter((call) => call.path === SEARCH)).toHaveLength(0)

    await user.type(screen.getByRole('searchbox', { name: 'Search for' }), 'ada{Enter}')

    const people = await screen.findByRole('region', { name: 'People found' })
    expect(within(people).getByRole('link', { name: /Ada/ })).toHaveAttribute(
      'href',
      '/identities/i1',
    )
    expect(
      within(screen.getByRole('region', { name: 'Unnamed people found' })).getByText(
        'Person ABC123',
      ),
    ).toBeInTheDocument()
    expect(
      within(screen.getByRole('region', { name: 'Images found' })).getByRole('link'),
    ).toHaveAttribute('href', '/library/source/s1')
    expect(
      within(screen.getByRole('region', { name: 'Appearances found' })).getByText(
        /in the Recycle bin/,
      ),
    ).toBeInTheDocument()
    expect(screen.getByRole('status', { name: 'Search coverage' })).toHaveTextContent(
      'Looked through 3 images.',
    )
    expect(calls.find((call) => call.path === SEARCH)?.query.get('q')).toBe('ada')
  })

  it('excludes recycled images unless asked, and the address keeps the choice', async () => {
    const { calls } = renderApp('/search?q=ada&recycled=include', [
      { path: SEARCH, respond: answer() },
    ])

    expect(await screen.findByText(/Nothing found for/)).toBeInTheDocument()
    const call = calls.find((c) => c.path === SEARCH)
    expect([call?.query.get('q'), call?.query.get('recycled')]).toEqual(['ada', 'include'])
    expect(screen.getByRole('checkbox', { name: 'Include recycled images' })).toBeChecked()
  })

  it('does not include recycled images by default, and searches again when the box is ticked', async () => {
    const user = userEvent.setup()
    const { calls } = renderApp('/search?q=ada', [{ path: SEARCH, respond: answer() }])
    await screen.findByText(/Nothing found for/)
    const box = screen.getByRole('checkbox', { name: 'Include recycled images' })
    expect(box).not.toBeChecked()
    expect(calls.find((c) => c.path === SEARCH)?.query.get('recycled')).toBe('exclude')

    await user.click(box)

    await waitFor(() =>
      expect(calls.filter((c) => c.path === SEARCH).at(-1)?.query.get('recycled')).toBe('include'),
    )
  })

  it('says when nobody can be recognised and when images were not processed', async () => {
    renderApp('/search?q=ada', [
      {
        path: SEARCH,
        respond: answer({
          results: {
            people: [
              {
                ...ada,
                identity_ids: [],
                occurrence_count: 0,
                source_count: 0,
                visual_support: false,
              },
            ],
            identities: [],
            sources: [
              {
                id: 's2',
                display_name: 'ada2.png',
                match: 'PREFIX',
                state: 'RECYCLED',
                source_recycled: true,
                processed: false,
              },
            ],
            occurrences: [],
          },
          coverage: { sources: 4, processed: 3, not_processed: 1 },
        }),
      },
    ])

    const people = await screen.findByRole('region', { name: 'People found' })
    expect(within(people).queryByRole('link')).toBeNull() // nothing to open
    expect(within(people).getByText(/no remembered face/)).toBeInTheDocument()
    expect(screen.getByText('In the Recycle bin · Not processed yet')).toBeInTheDocument()
    expect(screen.getByRole('status', { name: 'Search coverage' })).toHaveTextContent(
      '1 image has not been processed yet, so any faces in it cannot be found.',
    )
  })

  it('follows the address when going back, so the box shows what the results are for', async () => {
    const user = userEvent.setup()
    const { router } = renderApp('/search?q=ada', [{ path: SEARCH, respond: answer() }])
    const box = await screen.findByRole('searchbox', { name: 'Search for' })

    await user.clear(box)
    await user.type(box, 'bob{Enter}')
    await waitFor(() => expect(router.state.location.search).toBe('?q=bob'))
    await router.navigate(-1)

    await waitFor(() => expect(box).toHaveValue('ada'))
  })

  it('labels a person whose biometric memory was forgotten, who is still found by name', async () => {
    renderApp('/search?q=ada', [
      {
        path: SEARCH,
        respond: answer({
          results: {
            people: [
              {
                ...ada,
                identity_ids: [],
                occurrence_count: 0,
                source_count: 0,
                visual_support: false,
                biometric_memory_forgotten: true,
              },
            ],
            identities: [],
            sources: [],
            occurrences: [],
          },
        }),
      },
    ])

    const people = await screen.findByRole('region', { name: 'People found' })

    expect(within(people).getByText(/Biometric memory forgotten/)).toBeInTheDocument()
    expect(within(people).queryByText(/not recognisable/)).toBeNull()
  })

  it('shows the plain reason when the search fails', async () => {
    renderApp('/search?q=ada', [
      {
        path: SEARCH,
        ...apiError('INVALID_SEARCH', 'Give a word to look for.', 422),
      },
    ])

    expect(await screen.findByRole('alert')).toHaveTextContent('Give a word to look for.')
  })
})
