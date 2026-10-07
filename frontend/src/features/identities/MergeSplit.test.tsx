import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { failure, page, renderApp, Reply } from '@/test/harness'
import { identity, occurrence } from '@/test/fixtures'

const alice = { id: 'p1', display_name: 'Alice', revision: 1 }
const bob = { id: 'p2', display_name: 'Bob', revision: 1 }

function open(extra: Parameters<typeof renderApp>[1] = [], mine = identity({ revision: 3 })) {
  return renderApp('/identities/i1', [
    { path: '/api/v1/identities/i1', respond: mine },
    {
      path: '/api/v1/identities/i1/occurrences',
      respond: page([occurrence({ id: 'o1' }), occurrence({ id: 'o2', source_id: 's2' })]),
    },
    { path: /\/media$/, respond: 'bytes' },
    {
      path: '/api/v1/identities',
      respond: page([identity({ id: 'i2', revision: 5, person: bob })]),
    },
    ...extra,
  ])
}

describe('merging a person into another', () => {
  it('says what will happen, then merges and goes to the person they were merged into', async () => {
    const user = userEvent.setup()
    const { calls } = open([
      {
        method: 'POST',
        path: '/api/v1/identities/merge',
        respond: identity({ id: 'i2', revision: 6, person: bob }),
      },
      { path: '/api/v1/identities/i2', respond: identity({ id: 'i2', revision: 6, person: bob }) },
      { path: '/api/v1/identities/i2/occurrences', respond: page([]) },
    ], identity({ revision: 3, person: alice }))

    await user.click(await screen.findByRole('button', { name: 'This is the same person as…' }))
    await user.selectOptions(await screen.findByRole('combobox'), 'i2')
    expect(screen.getByText(/will be merged into/)).toHaveTextContent(
      'Alice will be merged into Bob: every face moves there and Alice goes. Both are named, so the name Bob is kept.',
    )
    await user.click(screen.getByRole('button', { name: 'Merge' }))

    expect(await screen.findByRole('heading', { name: 'Bob' })).toBeInTheDocument()
    expect(calls.find((c) => c.path.endsWith('/identities/merge'))?.body).toEqual({
      identities: [
        { id: 'i1', revision: 3 },
        { id: 'i2', revision: 5 },
      ],
      preferred_identity_id: 'i2',
    })
  })

  it('cannot merge until someone is chosen, and can be cancelled', async () => {
    const user = userEvent.setup()
    open()

    await user.click(await screen.findByRole('button', { name: 'This is the same person as…' }))

    expect(screen.getByRole('button', { name: 'Merge' })).toBeDisabled()
    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(screen.getByRole('button', { name: 'This is the same person as…' })).toBeInTheDocument()
  })

  it('says so when one of the people changed since the page was loaded', async () => {
    const user = userEvent.setup()
    open([
      {
        method: 'POST',
        path: '/api/v1/identities/merge',
        respond: () => failure(409, 'IDENTITY_CHANGED', 'changed'),
      },
    ])

    await user.click(await screen.findByRole('button', { name: 'This is the same person as…' }))
    await user.selectOptions(await screen.findByRole('combobox'), 'i2')
    await user.click(screen.getByRole('button', { name: 'Merge' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('One of these people changed')
  })
})

describe('splitting faces off a person', () => {
  const choose = async (user: ReturnType<typeof userEvent.setup>, which = 0) => {
    const boxes = await screen.findAllByRole('checkbox')
    await user.click(boxes[which])
  }

  it('splits the chosen faces into a new person and goes to them', async () => {
    const user = userEvent.setup()
    const { calls } = open([
      {
        method: 'POST',
        path: '/api/v1/identities/i1/split',
        respond: identity({ id: 'i9' }),
      },
      { path: '/api/v1/identities/i9', respond: identity({ id: 'i9' }) },
      { path: '/api/v1/identities/i9/occurrences', respond: page([]) },
    ])

    expect(screen.queryByRole('group', { name: 'Split off' })).toBeNull()
    await choose(user, 1)
    expect(screen.getByText('1 face chosen.')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'These are someone else' }))

    expect(await screen.findByRole('heading', { name: 'Person I9' })).toBeInTheDocument()
    expect(calls.find((c) => c.path.endsWith('/split'))?.body).toEqual({
      occurrence_ids: ['o2'],
      expected_revision: 3,
    })
  })

  it('offers the faces a split would have cut in two, and chooses them on request', async () => {
    const user = userEvent.setup()
    let attempts = 0
    const { calls } = open([
      {
        method: 'POST',
        path: '/api/v1/identities/i1/split',
        respond: () => {
          attempts += 1
          return attempts === 1
            ? new Reply(409, {
                error: {
                  code: 'SPLIT_CONFLICT',
                  message: 'conflict',
                  details: { occurrence_ids: ['o2'] },
                  retryable: false,
                  diagnostic_id: null,
                },
              })
            : identity({ id: 'i9' })
        },
      },
      { path: '/api/v1/identities/i9', respond: identity({ id: 'i9' }) },
      { path: '/api/v1/identities/i9/occurrences', respond: page([]) },
    ])

    await choose(user, 0)
    await user.click(screen.getByRole('button', { name: 'These are someone else' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Nothing was changed.')
    await user.click(screen.getByRole('button', { name: 'Choose that face too' }))
    expect(screen.getAllByRole('checkbox').map((box) => (box as HTMLInputElement).checked)).toEqual([
      true,
      true,
    ])
    await user.click(screen.getByRole('button', { name: 'These are someone else' }))

    expect(await screen.findByRole('heading', { name: 'Person I9' })).toBeInTheDocument()
    const bodies = calls.filter((c) => c.path.endsWith('/split')).map((c) => c.body)
    expect(bodies).toEqual([
      { occurrence_ids: ['o1'], expected_revision: 3 },
      { occurrence_ids: ['o1', 'o2'], expected_revision: 3 },
    ])
  })

  it('can be cleared, and unchoosing the last face hides the split controls', async () => {
    const user = userEvent.setup()
    open()

    await choose(user, 0)
    await choose(user, 0)

    expect(screen.queryByRole('group', { name: 'Split off' })).toBeNull()
    await choose(user, 1)
    await user.click(screen.getByRole('button', { name: 'Clear' }))
    expect(screen.queryByRole('group', { name: 'Split off' })).toBeNull()
  })

  it('shows the backend message when a split fails otherwise', async () => {
    const user = userEvent.setup()
    open([
      {
        method: 'POST',
        path: '/api/v1/identities/i1/split',
        respond: () => failure(404, 'OCCURRENCE_NOT_FOUND', 'That face is not theirs.'),
      },
    ])

    await choose(user, 0)
    await user.click(screen.getByRole('button', { name: 'These are someone else' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'They could not be split off: That face is not theirs.',
    )
  })
})
