// A small typed HTTP client for the backend: the launch token on every request, the one error
// shape turned into one exception type, and nothing else (caching is the query layer's job).

import type { Connection } from '@/native/backend'
import type { ErrorBody } from './types'

/** A failed request: the API's own error when it sent one, else a transport-level description. */
export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly details: Record<string, unknown> | null
  readonly retryable: boolean

  constructor(status: number, body: Pick<ErrorBody, 'code' | 'message'> & Partial<ErrorBody>) {
    super(body.message)
    this.name = 'ApiError'
    this.status = status
    this.code = body.code
    this.details = body.details ?? null
    this.retryable = body.retryable ?? false
  }
}

export type Query = Record<string, string | number | boolean | undefined | null>

export class ApiClient {
  private readonly connection: Pick<Connection, 'base_url' | 'token'>
  private readonly fetcher: typeof fetch

  constructor(
    connection: Pick<Connection, 'base_url' | 'token'>,
    fetcher: typeof fetch = (...args) => fetch(...args),
  ) {
    this.connection = connection
    this.fetcher = fetcher
  }

  private url(path: string, query?: Query): string {
    const params = new URLSearchParams()
    for (const [key, value] of Object.entries(query ?? {})) {
      if (value !== undefined && value !== null) params.set(key, String(value))
    }
    const text = params.toString()
    return `${this.connection.base_url}${path}${text ? `?${text}` : ''}`
  }

  private async send(path: string, init: RequestInit, query?: Query): Promise<Response> {
    let response: Response
    try {
      response = await this.fetcher(this.url(path, query), {
        ...init,
        headers: { ...init.headers, Authorization: `Bearer ${this.connection.token}` },
      })
    } catch {
      throw new ApiError(0, { code: 'NETWORK_ERROR', message: 'The backend could not be reached.', retryable: true })
    }
    if (response.ok) return response
    const body = await response.json().catch(() => null)
    const error = body && typeof body === 'object' && 'error' in body ? (body.error as ErrorBody) : null
    throw new ApiError(
      response.status,
      error ?? { code: 'HTTP_ERROR', message: `The backend answered ${response.status}.` },
    )
  }

  async get<T>(path: string, query?: Query): Promise<T> {
    return (await this.send(path, { method: 'GET' }, query)).json() as Promise<T>
  }

  async post<T>(path: string, body?: unknown): Promise<T> {
    const init: RequestInit =
      body === undefined
        ? { method: 'POST' }
        : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }
    return (await this.send(path, init)).json() as Promise<T>
  }

  /** A file the API serves (the browser cannot add the token to an `<img src>`). */
  async blob(path: string): Promise<Blob> {
    return (await this.send(path, { method: 'GET' })).blob()
  }
}
