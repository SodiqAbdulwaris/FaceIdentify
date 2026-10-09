import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { identity } from '@/test/fixtures'
import { apiError, renderApp } from '@/test/harness'

const FACE = '/api/v1/search/face'

const face = (over: Record<string, unknown> = {}) => ({
  index: 0,
  bounding_box: { x: 0.2, y: 0.2, width: 0.6, height: 0.6 },
  detection_score: 0.9,
  status: 'POSSIBLE_PEOPLE',
  reason: 'NOT_SIMILAR',
  identity_answer: null,
  possible_people: [
    {
      identity: identity({ id: 'i1', person: { id: 'p1', display_name: 'Ada' }, source_count: 2 }),
      similarity: 0.8123,
      matching_faces: 3,
    },
  ],
  retrieval_complete: true,
  ...over,
})

const answer = (faces: unknown[]) => ({
  faces,
  ranking: { plan: 'FACE_QUERY', policy_version: 'v', similarity: 'COSINE_UNCALIBRATED' },
})

const picture = (type = 'image/png') => new File(['pixels'], 'face.png', { type })
const choose = async (file: File) =>
  userEvent.setup({ applyAccept: false }).upload(screen.getByLabelText('Choose a picture'), file)

describe('face search', () => {
  it('sends the picture once and lists the possible people of each face, nearest first', async () => {
    const { calls } = renderApp('/search', [{ method: 'POST', path: FACE, respond: answer([face()]) }])

    await choose(picture())

    const result = await screen.findByRole('region', { name: 'Face 1 of the picture' })
    expect(within(result).getByText('Possible people')).toBeInTheDocument()
    const link = within(result).getByRole('link', { name: /Ada/ })
    expect(link).toHaveAttribute('href', '/identities/i1')
    expect(link).toHaveTextContent('similarity 0.81 · 3 matching faces · 2 images')
    expect(within(result).getByText(/not a probability/)).toBeInTheDocument()
    const sent = calls.filter((c) => c.path === FACE)
    expect(sent).toHaveLength(1)
    expect(sent[0]?.method).toBe('POST')
  })

  it('gives every face its own answer, and says when nobody resembles one', async () => {
    renderApp('/search', [
      {
        method: 'POST',
        path: FACE,
        respond: answer([
          face(),
          face({ index: 1, status: 'UNKNOWN', possible_people: [] }),
        ]),
      },
    ])

    await choose(picture())

    expect(await screen.findByRole('region', { name: 'Face 2 of the picture' })).toHaveTextContent(
      'No one in your library resembles this face.',
    )
    expect(screen.getByRole('region', { name: 'Face 1 of the picture' })).toBeInTheDocument()
  })

  it('shows an accepted identity as an answer of its own, and warns when the memory was behind', async () => {
    renderApp('/search', [
      {
        method: 'POST',
        path: FACE,
        respond: answer([
          face({
            status: 'IDENTITY_ANSWER',
            identity_answer: identity({ id: 'i1', person: { id: 'p1', display_name: 'Ada' } }),
            retrieval_complete: false,
          }),
        ]),
      },
    ])

    await choose(picture())

    const result = await screen.findByRole('region', { name: 'Face 1 of the picture' })
    expect(within(result).getByText(/Recognised as/)).toBeInTheDocument()
    expect(within(result).getByText(/still catching up/)).toBeInTheDocument()
  })

  it('says so when no face was found', async () => {
    renderApp('/search', [{ method: 'POST', path: FACE, respond: answer([]) }])

    await choose(picture())

    await waitFor(() =>
      expect(screen.getByRole('status', { name: 'Face search status' })).toHaveTextContent(
        'No face was found in this picture.',
      ),
    )
  })

  it('refuses a file that is not a supported picture without sending it', async () => {
    const { calls } = renderApp('/search', [])

    await choose(picture('application/pdf'))

    expect(await screen.findByRole('alert')).toHaveTextContent('Only JPEG, PNG, BMP and WebP')
    expect(calls.filter((c) => c.path === FACE)).toHaveLength(0)
  })

  it('shows the reason when the search fails', async () => {
    renderApp('/search', [
      { method: 'POST', path: FACE, ...apiError('PERCEPTION_UNAVAILABLE', 'Not just now.', 503) },
    ])

    await choose(picture())

    expect(await screen.findByRole('alert')).toHaveTextContent('Not just now.')
  })

  it('asks again when something changes, hiding the old answer so a forgotten person never stays', async () => {
    let forgotten = false
    const { queryClient } = renderApp('/search', [
      {
        method: 'POST',
        path: FACE,
        respond: () => answer([face({ possible_people: forgotten ? [] : face().possible_people })]),
      },
    ])
    await choose(picture())
    expect(await screen.findByRole('link', { name: /Ada/ })).toBeInTheDocument()

    forgotten = true
    await queryClient.invalidateQueries({ queryKey: ['search'] })

    await waitFor(() => expect(screen.queryByRole('link', { name: /Ada/ })).toBeNull())
  })

  it('keeps neither the picture nor the answer once the screen is left', async () => {
    const { queryClient, router } = renderApp('/search', [
      { method: 'POST', path: FACE, respond: answer([face()]) },
    ])
    await choose(picture())
    await screen.findByRole('region', { name: 'Face 1 of the picture' })

    await router.navigate('/library')

    await waitFor(() =>
      expect(queryClient.getQueryCache().findAll({ queryKey: ['search', 'face'] })).toHaveLength(0),
    )
  })

  it('takes a dropped picture and a pasted one', async () => {
    const { calls } = renderApp('/search', [{ method: 'POST', path: FACE, respond: answer([]) }])
    const zone = (await screen.findByText(/or drop one here/)).parentElement as HTMLElement

    fireEvent.drop(zone, { dataTransfer: { files: [picture()] } })
    await waitFor(() => expect(calls.filter((c) => c.path === FACE)).toHaveLength(1))
    const event = new Event('paste', { cancelable: true }) as Event & { clipboardData: unknown }
    event.clipboardData = { files: [picture('image/webp')] }
    window.dispatchEvent(event)

    await waitFor(() => expect(calls.filter((c) => c.path === FACE)).toHaveLength(2))
    expect(event.defaultPrevented).toBe(true)
  })
})
