import { describe, expect, it, vi } from 'vitest'
import { ApiClient, ApiError } from './client'

const connection = { base_url: 'http://127.0.0.1:5000', token: 'secret-token' }

function respond(status: number, body: unknown, init: ResponseInit = {}) {
  return new Response(typeof body === 'string' ? body : JSON.stringify(body), { status, ...init })
}

describe('ApiClient', () => {
  it('sends the launch token on every request and builds the query without empty values', async () => {
    const fetcher = vi.fn().mockResolvedValue(respond(200, { ok: true }))
    const client = new ApiClient(connection, fetcher)

    const result = await client.get('/api/v1/sources', {
      state: 'ACTIVE',
      cursor: undefined,
      limit: 50,
      skip: null,
    })

    expect(result).toEqual({ ok: true })
    const [url, init] = fetcher.mock.calls[0]
    expect(url).toBe('http://127.0.0.1:5000/api/v1/sources?state=ACTIVE&limit=50')
    expect(init.headers.Authorization).toBe('Bearer secret-token')
    expect(init.method).toBe('GET')
  })

  it('posts JSON with a content type, and posts nothing when there is no body', async () => {
    const fetcher = vi.fn().mockImplementation(async () => respond(200, { id: 'x' }))
    const client = new ApiClient(connection, fetcher)

    await client.post('/api/v1/sources/import', { path: 'C:\\a.png' })
    await client.post('/api/v1/sources/1/process')

    const [, withBody] = fetcher.mock.calls[0]
    expect(withBody.headers['Content-Type']).toBe('application/json')
    expect(JSON.parse(withBody.body)).toEqual({ path: 'C:\\a.png' })
    const [url, without] = fetcher.mock.calls[1]
    expect(url).toBe('http://127.0.0.1:5000/api/v1/sources/1/process')
    expect(without.body).toBeUndefined()
    expect(without.headers.Authorization).toBe('Bearer secret-token')
  })

  it('turns the one error shape into an ApiError', async () => {
    const error = {
      code: 'SOURCE_NOT_FOUND',
      message: 'The requested source could not be found.',
      details: { source_id: 's1' },
      retryable: false,
      diagnostic_id: null,
    }
    const client = new ApiClient(connection, vi.fn().mockResolvedValue(respond(404, { error })))

    const failure = await client.get('/api/v1/sources/s1').catch((e: unknown) => e)

    expect(failure).toBeInstanceOf(ApiError)
    expect(failure).toMatchObject({
      status: 404,
      code: 'SOURCE_NOT_FOUND',
      message: error.message,
      details: { source_id: 's1' },
      retryable: false,
    })
  })

  it('describes a failure that is not the API error shape', async () => {
    const client = new ApiClient(connection, vi.fn().mockResolvedValue(respond(502, 'Bad gateway')))

    const failure = await client.get('/x').catch((e: unknown) => e)

    expect(failure).toMatchObject({ status: 502, code: 'HTTP_ERROR', details: null, retryable: false })
  })

  it('reports an unreachable backend as a retryable network error', async () => {
    const client = new ApiClient(
      connection,
      vi.fn().mockRejectedValue(new TypeError('failed to fetch')),
    )

    const failure = await client.get('/x').catch((e: unknown) => e)

    expect(failure).toMatchObject({ status: 0, code: 'NETWORK_ERROR', retryable: true })
  })

  it('fetches a file as a blob with the token (an image tag could not)', async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValue(
        new Response('bytes', { headers: { 'Content-Type': 'image/png' } }),
      )
    const client = new ApiClient(connection, fetcher)

    const blob = await client.blob('/api/v1/sources/s1/media')

    expect(blob.type).toBe('image/png')
    expect(await blob.text()).toBe('bytes')
    expect(fetcher.mock.calls[0][1].headers.Authorization).toBe('Bearer secret-token')
  })
})
