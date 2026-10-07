import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { failure, page, renderApp } from '@/test/harness'
import { detail, identity, occurrence } from '@/test/fixtures'

const SOURCE = '/api/v1/sources/s1'
const FACE = '/api/v1/occurrences/o1'

function open(extra: Parameters<typeof renderApp>[1] = []) {
  return renderApp('/library/source/s1', [
    { path: SOURCE, respond: detail({ processing_status: 'COMPLETED' }) },
    { path: `${SOURCE}/media`, respond: 'bytes' },
    { path: `${SOURCE}/occurrences`, respond: page([occurrence()]) },
    { path: `${SOURCE}/processing-runs`, respond: page([]) },
    {
      path: '/api/v1/identities',
      respond: page([identity({ id: 'i1' }), identity({ id: 'i2', person: { id: 'p2', display_name: 'Bob', revision: 1 } })]),
    },
    ...extra,
  ])
}

async function check(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole('button', { name: 'Check this face' }))
  return screen.getByRole('group', { name: 'Check Person I1' })
}

describe('checking a face', () => {
  it('confirms that it is the person it was recognised as', async () => {
    const user = userEvent.setup()
    const { calls } = open([{ method: 'POST', path: `${FACE}/confirm`, respond: occurrence() }])

    await check(user)
    await user.click(screen.getByRole('button', { name: 'Yes, this is Person I1' }))

    await screen.findByRole('button', { name: 'Check this face' })
    expect(calls.find((c) => c.path === `${FACE}/confirm`)?.body).toEqual({
      expected_identity_id: 'i1',
    })
  })

  it('moves the face to a new person', async () => {
    const user = userEvent.setup()
    const { calls } = open([{ method: 'POST', path: `${FACE}/reassign`, respond: occurrence() }])

    await check(user)
    await user.click(screen.getByRole('button', { name: 'This is someone new' }))

    await screen.findByRole('button', { name: 'Check this face' })
    expect(calls.find((c) => c.path === `${FACE}/reassign`)?.body).toEqual({
      expected_identity_id: 'i1',
      identity_id: null,
    })
  })

  it('moves the face to a chosen person, never offering the one it already has', async () => {
    const user = userEvent.setup()
    const { calls } = open([{ method: 'POST', path: `${FACE}/reassign`, respond: occurrence() }])

    const group = await check(user)
    const choose = await screen.findByRole('combobox', {
      name: 'This is someone already in the library',
    })
    expect(group).toContainElement(choose)
    expect(await screen.findByRole('option', { name: 'Bob' })).toBeInTheDocument()
    expect(screen.queryByRole('option', { name: 'Person I1' })).toBeNull()
    expect(screen.getByRole('button', { name: 'Move this face' })).toBeDisabled()
    await user.selectOptions(choose, 'i2')
    await user.click(screen.getByRole('button', { name: 'Move this face' }))

    await screen.findByRole('button', { name: 'Check this face' })
    expect(calls.find((c) => c.path === `${FACE}/reassign`)?.body).toEqual({
      expected_identity_id: 'i1',
      identity_id: 'i2',
    })
  })

  it('says so when the face has moved since the page was loaded', async () => {
    const user = userEvent.setup()
    open([
      {
        method: 'POST',
        path: `${FACE}/confirm`,
        respond: () => failure(409, 'OCCURRENCE_MOVED', 'moved'),
      },
    ])

    await check(user)
    await user.click(screen.getByRole('button', { name: 'Yes, this is Person I1' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'This face now belongs to someone else.',
    )
  })

  it('shows the backend message for any other failure and can be closed', async () => {
    const user = userEvent.setup()
    open([
      {
        method: 'POST',
        path: `${FACE}/reassign`,
        respond: () => failure(409, 'FACE_NOT_CORRECTABLE', 'This face cannot be moved there.'),
      },
    ])

    await check(user)
    await user.click(screen.getByRole('button', { name: 'This is someone new' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'The correction could not be saved: This face cannot be moved there.',
    )
    await user.click(screen.getByRole('button', { name: 'Close' }))
    expect(screen.getByRole('button', { name: 'Check this face' })).toBeInTheDocument()
  })
})

describe('the people to choose from', () => {
  it('can be paged: more people are loaded on request', async () => {
    const user = userEvent.setup()
    const { calls } = renderApp('/library/source/s1', [
      { path: SOURCE, respond: detail({ processing_status: 'COMPLETED' }) },
      { path: `${SOURCE}/media`, respond: 'bytes' },
      { path: `${SOURCE}/occurrences`, respond: page([occurrence()]) },
      { path: `${SOURCE}/processing-runs`, respond: page([]) },
      {
        path: '/api/v1/identities',
        respond: (call) =>
          call.query.get('cursor') === 'more'
            ? page([identity({ id: 'i3' })])
            : page([identity({ id: 'i2' })], 'more'),
      },
    ])

    await check(user)
    expect(await screen.findByRole('option', { name: 'Person I2' })).toBeInTheDocument()
    expect(screen.queryByRole('option', { name: 'Person I3' })).toBeNull()
    await user.click(screen.getByRole('button', { name: 'Show more people' }))

    expect(await screen.findByRole('option', { name: 'Person I3' })).toBeInTheDocument()
    const cursors = calls.filter((c) => c.path === '/api/v1/identities').map((c) => c.query.get('cursor'))
    expect(cursors).toContain('more')
  })

  it('are offered from the person screen too, for each appearance', async () => {
    const user = userEvent.setup()
    renderApp('/identities/i1', [
      { path: '/api/v1/identities/i1', respond: identity() },
      {
        path: '/api/v1/identities/i1/occurrences',
        respond: page([occurrence({ id: 'o1' }), occurrence({ id: 'o2', source_id: 's2' })]),
      },
      { path: /\/media$/, respond: 'bytes' },
      { path: '/api/v1/identities', respond: page([identity({ id: 'i2' })]) },
    ])

    const buttons = await screen.findAllByRole('button', { name: 'Check this face' })
    expect(buttons).toHaveLength(2)
    await user.click(buttons[0])
    expect(screen.getByRole('group', { name: 'Check Person I1' })).toBeInTheDocument()
  })
})
