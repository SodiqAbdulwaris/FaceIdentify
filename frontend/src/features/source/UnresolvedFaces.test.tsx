import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { failure, page, renderApp } from '@/test/harness'
import { detail, identity, occurrence } from '@/test/fixtures'

const SOURCE = '/api/v1/sources/s1'
const RESOLVE = '/api/v1/representations/r1/resolve'

const unresolved = (over: Record<string, unknown> = {}) => ({
  representation_id: 'r1',
  observation_id: 'ob9',
  bounding_box: { x: 0.2, y: 0.1, width: 0.3, height: 0.4 },
  likely: [
    { identity_id: 'i7', person: null, similarity: 0.412 },
    { identity_id: 'i8', person: { id: 'p8', display_name: 'Bob', revision: 1 }, similarity: 0.38 },
  ],
  ...over,
})

function open(faces: unknown[], extra: Parameters<typeof renderApp>[1] = []) {
  return renderApp('/library/source/s1', [
    { path: SOURCE, respond: detail({ processing_status: 'COMPLETED' }) },
    { path: `${SOURCE}/media`, respond: 'bytes' },
    { path: `${SOURCE}/occurrences`, respond: page([occurrence()]) },
    { path: `${SOURCE}/processing-runs`, respond: page([]) },
    { path: `${SOURCE}/unresolved-faces`, respond: { items: faces } },
    { path: '/api/v1/identities', respond: page([identity({ id: 'i2' })]) },
    ...extra,
  ])
}

describe('faces to place', () => {
  it('lists each face with who it resembled, best first, and the choices a person has', async () => {
    open([unresolved()])

    expect(await screen.findByRole('heading', { name: 'Faces to place' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'This is Person I7 (41% alike)' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'This is Bob (38% alike)' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'This is someone new' })).toBeInTheDocument()
  })

  it('shows nothing when every face has been placed', async () => {
    open([])

    expect(await screen.findByRole('heading', { name: 'beach.png' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Faces to place' })).toBeNull()
  })

  it('places a face with one of the people it resembled', async () => {
    const user = userEvent.setup()
    const { calls } = open([unresolved()], [{ method: 'POST', path: RESOLVE, respond: occurrence() }])

    await user.click(await screen.findByRole('button', { name: 'This is Bob (38% alike)' }))

    await screen.findByRole('button', { name: 'This is Bob (38% alike)' })
    expect(calls.find((c) => c.path === RESOLVE)?.body).toEqual({ identity_id: 'i8' })
  })

  it('places a face as someone new', async () => {
    const user = userEvent.setup()
    const { calls } = open([unresolved()], [{ method: 'POST', path: RESOLVE, respond: occurrence() }])

    await user.click(await screen.findByRole('button', { name: 'This is someone new' }))

    await screen.findByRole('heading', { name: 'beach.png' })
    expect(calls.find((c) => c.path === RESOLVE)?.body).toEqual({ identity_id: null })
  })

  it('places a face with anyone in the library', async () => {
    const user = userEvent.setup()
    const { calls } = open([unresolved()], [{ method: 'POST', path: RESOLVE, respond: occurrence() }])

    await user.click(await screen.findByRole('button', { name: 'Someone else in the library…' }))
    const choose = await screen.findByRole('combobox', { name: 'Choose a person' })
    expect(screen.getByRole('button', { name: 'Place this face' })).toBeDisabled()
    await user.selectOptions(choose, 'i2')
    await user.click(screen.getByRole('button', { name: 'Place this face' }))

    await screen.findByRole('heading', { name: 'beach.png' })
    expect(calls.find((c) => c.path === RESOLVE)?.body).toEqual({ identity_id: 'i2' })
  })

  it('says so when the face could not be placed', async () => {
    const user = userEvent.setup()
    open(
      [unresolved()],
      [
        {
          method: 'POST',
          path: RESOLVE,
          respond: () => failure(409, 'FACE_NOT_RESOLVABLE', 'This face cannot be resolved now.'),
        },
      ],
    )

    await user.click(await screen.findByRole('button', { name: 'This is someone new' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'The face could not be placed: This face cannot be resolved now.',
    )
  })
})
