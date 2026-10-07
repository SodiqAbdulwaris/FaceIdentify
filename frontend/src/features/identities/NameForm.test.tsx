import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { failure, page, renderApp } from '@/test/harness'
import { identity, occurrence } from '@/test/fixtures'

const PERSON = '/api/v1/identities/i1'
const alice = { id: 'p1', display_name: 'Alice', revision: 1 }
const summary = (over: Record<string, unknown> = {}) => ({
  id: 'p1',
  display_name: 'Alice',
  revision: 1,
  identity_count: 1,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  ...over,
})

describe('naming a person', () => {
  it('creates the person with the typed name, then shows the name everywhere', async () => {
    const user = userEvent.setup()
    let named = false
    const { calls } = renderApp('/identities/i1', [
      { path: PERSON, respond: () => identity({ person: named ? alice : null }) },
      { path: `${PERSON}/occurrences`, respond: page([occurrence()]) },
      { path: /\/media$/, respond: 'bytes' },
      {
        method: 'POST',
        path: '/api/v1/people',
        respond: () => {
          named = true
          return summary()
        },
      },
    ])

    expect(await screen.findByRole('heading', { name: 'Person I1' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Name this person' }))
    await user.type(screen.getByRole('textbox', { name: 'Name' }), '  Alice ')
    await user.click(screen.getByRole('button', { name: 'Save name' }))

    expect(await screen.findByRole('heading', { name: 'Alice' })).toBeInTheDocument()
    expect(screen.queryByText(/Nobody has named this person yet/)).toBeNull()
    expect(calls.find((c) => c.method === 'POST')?.body).toEqual({
      display_name: 'Alice',
      identity_id: 'i1',
    })
    expect(screen.getByRole('button', { name: 'Rename' })).toBeInTheDocument()
  })

  it('does not save an empty name', async () => {
    const user = userEvent.setup()
    renderApp('/identities/i1', [
      { path: PERSON, respond: identity() },
      { path: `${PERSON}/occurrences`, respond: page([]) },
    ])

    await user.click(await screen.findByRole('button', { name: 'Name this person' }))
    await user.type(screen.getByRole('textbox', { name: 'Name' }), '   ')

    expect(screen.getByRole('button', { name: 'Save name' })).toBeDisabled()
    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(screen.getByRole('button', { name: 'Name this person' })).toBeInTheDocument()
  })

  it('says so when the name could not be saved, and keeps the form', async () => {
    const user = userEvent.setup()
    renderApp('/identities/i1', [
      { path: PERSON, respond: identity() },
      { path: `${PERSON}/occurrences`, respond: page([]) },
      {
        method: 'POST',
        path: '/api/v1/people',
        respond: () => failure(409, 'IDENTITY_ALREADY_NAMED', 'The identity already has a person.'),
      },
    ])

    await user.click(await screen.findByRole('button', { name: 'Name this person' }))
    await user.type(screen.getByRole('textbox', { name: 'Name' }), 'Bob')
    await user.click(screen.getByRole('button', { name: 'Save name' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'The name could not be saved: The identity already has a person.',
    )
    expect(screen.getByRole('textbox', { name: 'Name' })).toHaveValue('Bob')
  })
})

describe('renaming a person', () => {
  it('sends the revision that was shown', async () => {
    const user = userEvent.setup()
    const { calls } = renderApp('/identities/i1', [
      { path: PERSON, respond: identity({ person: alice }) },
      { path: `${PERSON}/occurrences`, respond: page([]) },
      { method: 'PATCH', path: '/api/v1/people/p1', respond: summary({ revision: 2 }) },
    ])

    expect(await screen.findByRole('heading', { name: 'Alice' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Rename' }))
    const box = screen.getByRole('textbox', { name: 'New name' })
    expect(box).toHaveValue('Alice')
    await user.clear(box)
    await user.type(box, 'Alicia')
    await user.click(screen.getByRole('button', { name: 'Save name' }))

    await screen.findByRole('button', { name: 'Rename' })
    expect(calls.find((c) => c.method === 'PATCH')?.body).toEqual({
      display_name: 'Alicia',
      expected_revision: 1,
    })
  })

  it('tells the user when the name was changed somewhere else', async () => {
    const user = userEvent.setup()
    renderApp('/identities/i1', [
      { path: PERSON, respond: identity({ person: alice }) },
      { path: `${PERSON}/occurrences`, respond: page([]) },
      {
        method: 'PATCH',
        path: '/api/v1/people/p1',
        respond: () => failure(409, 'PERSON_REVISION_CONFLICT', 'conflict'),
      },
    ])

    await user.click(await screen.findByRole('button', { name: 'Rename' }))
    await user.type(screen.getByRole('textbox', { name: 'New name' }), 'x')
    await user.click(screen.getByRole('button', { name: 'Save name' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'This name was changed somewhere else.',
    )
  })
})
