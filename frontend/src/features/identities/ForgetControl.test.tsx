import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { identity } from '@/test/fixtures'
import { failure, page, renderApp } from '@/test/harness'

const IDENTITY = '/api/v1/identities/i1'
const ada = { id: 'p1', display_name: 'Ada', revision: 1 }
const base = [
  { path: `${IDENTITY}/occurrences`, respond: page([]) },
  { path: '/api/v1/identities', respond: page([]) },
]

const forgetting = (answer: Record<string, unknown> = { status: 204 }) => ({
  method: 'POST' as const,
  path: `${IDENTITY}/forget`,
  ...answer,
  respond: () => (answer.status === 202 ? { outstanding: ['the write-ahead log'] } : null),
})

describe('forgetting a person', () => {
  it('promises no suppression: a whole-person forget says they count as new, a narrow one that other faces still recognise them', async () => {
    const user = userEvent.setup()
    renderApp('/identities/i1', [{ path: IDENTITY, respond: identity({ person: ada }) }, ...base])

    await user.click(await screen.findByRole('button', { name: 'Forget every face of Ada' }))
    expect(screen.getByRole('alertdialog')).toHaveTextContent('treats them as someone new')
    expect(screen.getByRole('alertdialog')).not.toHaveTextContent(/will not recognise/)
    await user.click(screen.getByRole('button', { name: 'Keep it' }))
    await user.click(screen.getByRole('button', { name: 'Forget how Ada looks' }))

    const narrow = screen.getByRole('alertdialog')
    expect(narrow).toHaveTextContent('Other faces remembered for Ada are kept')
    expect(narrow).toHaveTextContent('still recognise them from those')
    expect(narrow).not.toHaveTextContent('someone new')
  })

  it('gives focus back to the button that opened the question, whichever it was', async () => {
    const user = userEvent.setup()
    renderApp('/identities/i1', [
      { path: IDENTITY, respond: identity({ person: ada }) },
      ...base,
    ])

    await user.click(await screen.findByRole('button', { name: 'Forget every face of Ada' }))
    await user.keyboard('{Escape}')

    expect(screen.getByRole('button', { name: 'Forget every face of Ada' })).toHaveFocus()
  })

  it('drops every cached identity and face list, not only this one, when a whole person goes', async () => {
    const user = userEvent.setup()
    const { queryClient } = renderApp('/identities/i1', [
      { path: IDENTITY, respond: identity({ person: ada }) },
      { method: 'POST', path: '/api/v1/people/p1/forget', status: 204, respond: () => null },
      // the list cannot be refetched, so only dropping it keeps the forgotten entry off the screen
      { path: '/api/v1/identities', respond: () => failure(500, 'INTERNAL_ERROR', 'down') },
      base[0],
    ])
    await user.click(await screen.findByRole('button', { name: 'Forget every face of Ada' }))
    queryClient.setQueryData(['identity', 'i2'], identity({ id: 'i2' }))
    queryClient.setQueryData(['identity', 'i2', 'occurrences'], { pages: [] })
    queryClient.setQueryData(['source', 's1', 'occurrences'], { items: [] })
    queryClient.setQueryData(['search', 'ada', 'include'], { query: 'ada' })
    queryClient.setQueryData(['identities'], {
      pages: [{ items: [{ id: 'forgotten-i2' }], page: { next_cursor: null } }],
      pageParams: [undefined],
    })

    await user.click(screen.getByRole('button', { name: 'Yes, forget' }))

    expect(await screen.findByRole('heading', { name: 'People' })).toBeInTheDocument()
    expect(queryClient.getQueryData(['identity', 'i2'])).toBeUndefined()
    expect(queryClient.getQueryData(['identity', 'i2', 'occurrences'])).toBeUndefined()
    expect(queryClient.getQueryData(['source', 's1', 'occurrences'])).toBeUndefined()
    expect(queryClient.getQueryData(['search', 'ada', 'include'])).toBeUndefined()
    // the list of people is dropped and fetched anew: the forgotten entry is not carried over
    expect(JSON.stringify(queryClient.getQueryData(['identities']) ?? {})).not.toContain('forgotten-i2')
  })

  it('asks first, can be cancelled, and sends the revision it saw', async () => {
    const user = userEvent.setup()
    const { calls, queryClient } = renderApp('/identities/i1', [
      { path: IDENTITY, respond: identity({ revision: 7 }) },
      forgetting(),
      ...base,
    ])
    await user.click(await screen.findByRole('button', { name: /Forget how this person looks/ }))
    expect(screen.getByRole('alertdialog')).toHaveTextContent('cannot be brought back')
    await user.click(screen.getByRole('button', { name: 'Keep it' }))
    expect(screen.queryByRole('alertdialog')).toBeNull()
    expect(calls.some((c) => c.path.endsWith('/forget'))).toBe(false) // nothing sent yet

    await user.click(screen.getByRole('button', { name: /Forget how this person looks/ }))
    await user.click(screen.getByRole('button', { name: 'Yes, forget' }))

    await waitFor(() => expect(calls.some((c) => c.path === `${IDENTITY}/forget`)).toBe(true))
    expect(await screen.findByRole('heading', { name: 'People' })).toBeInTheDocument()
    const sent = calls.find((c) => c.path === `${IDENTITY}/forget`)
    expect(sent?.body).toEqual({ expected_revision: 7 })
    expect(queryClient.getQueryData(['identity', 'i1'])).toBeUndefined() // nothing of them is kept
  })

  it('moves focus to the safe answer, and gives it back on Escape', async () => {
    const user = userEvent.setup()
    renderApp('/identities/i1', [{ path: IDENTITY, respond: identity() }, ...base])

    await user.click(await screen.findByRole('button', { name: /Forget how this person looks/ }))

    expect(screen.getByRole('button', { name: 'Keep it' })).toHaveFocus()
    expect(screen.getByRole('alertdialog')).toHaveAccessibleDescription(/cannot be brought back/)
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('alertdialog')).toBeNull()
    expect(screen.getByRole('button', { name: /Forget how this person looks/ })).toHaveFocus()
  })

  it('offers a named person both scopes, and forgetting every face asks for the person', async () => {
    const user = userEvent.setup()
    const { calls } = renderApp('/identities/i1', [
      { path: IDENTITY, respond: identity({ person: ada }) },
      { method: 'POST', path: '/api/v1/people/p1/forget', status: 204, respond: () => null },
      ...base,
    ])

    await user.click(await screen.findByRole('button', { name: 'Forget every face of Ada' }))
    expect(screen.getByRole('alertdialog')).toHaveTextContent('Ada stays in your people')
    await user.click(screen.getByRole('button', { name: 'Yes, forget' }))

    await waitFor(() =>
      expect(calls.some((c) => c.path === '/api/v1/people/p1/forget')).toBe(true),
    )
    expect(calls.some((c) => c.path === `${IDENTITY}/forget`)).toBe(false)
  })

  it('does not offer the person scope for somebody nobody has named', async () => {
    renderApp('/identities/i1', [{ path: IDENTITY, respond: identity() }, ...base])

    await screen.findByRole('button', { name: /Forget how this person looks/ })

    expect(screen.queryByRole('button', { name: /Forget every face/ })).toBeNull()
  })

  it('carries the warning about unfinished cleanup to the people list', async () => {
    const user = userEvent.setup()
    renderApp('/identities/i1', [
      { path: IDENTITY, respond: identity() },
      forgetting({ status: 202 }),
      ...base,
    ])

    await user.click(await screen.findByRole('button', { name: /Forget how this person looks/ }))
    await user.click(screen.getByRole('button', { name: 'Yes, forget' }))

    expect(await screen.findByRole('status', { name: 'People notice' })).toHaveTextContent(
      'tried again the next time the app starts',
    )
  })

  it('says why it was refused, and puts focus back on the button', async () => {
    const user = userEvent.setup()
    renderApp('/identities/i1', [
      { path: IDENTITY, respond: identity() },
      {
        method: 'POST',
        path: `${IDENTITY}/forget`,
        respond: () => failure(409, 'IDENTITY_CHANGED', 'This person changed since you looked. Reload.'),
      },
      ...base,
    ])

    await user.click(await screen.findByRole('button', { name: /Forget how this person looks/ }))
    await user.click(screen.getByRole('button', { name: 'Yes, forget' }))

    expect(await screen.findByRole('status', { name: 'Forget notice' })).toHaveTextContent(
      'changed since you looked',
    )
    expect(screen.getByRole('button', { name: /Forget how this person looks/ })).toHaveFocus()
  })
})
