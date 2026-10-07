// Renders the real app (routes, layout, query cache) against a scripted backend: `fetch` answers
// from a list of handlers, the event socket stays quiet, and anything the app asks that no handler
// expects fails the test. The backend itself has its own tests; here it is a script.

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { vi } from 'vitest'
import { routes } from '@/app/routes'
import { BackendProvider } from '@/app/BackendProvider'
import type { Connection } from '@/native/backend'

export const connection: Connection = {
  base_url: 'http://127.0.0.1:5000',
  events_url: 'ws://127.0.0.1:5000/api/v1/events',
  token: 'test-token',
  protocol: 'faceidentify.v1',
}

export interface Call {
  method: string
  path: string
  query: URLSearchParams
  body: unknown
  authorization: string | null
}

type Body = object | string | null

export interface Handler {
  method?: string
  /** A path, or a pattern the path must match. */
  path: string | RegExp
  /** The JSON answer, or a function making it (a status other than 200 needs `reply`). */
  respond: Body | ((call: Call) => Body | Reply)
  status?: number
}

export const page = <T,>(items: T[], next: string | null = null) => ({
  items,
  page: { next_cursor: next, has_more: next !== null },
})

/** An answer with its own status (a handler's function may return one instead of a plain body). */
export class Reply {
  readonly status: number
  readonly body: unknown
  constructor(status: number, body: unknown) {
    this.status = status
    this.body = body
  }
}

const errorBody = (code: string, message: string) => ({
  error: { code, message, details: null, retryable: false, diagnostic_id: null },
})

/** A handler's answer that is the API's error shape. */
export function apiError(code: string, message: string, status = 400) {
  return { status, respond: errorBody(code, message) }
}

/** The same, for a function that chooses its answer per request. */
export const failure = (status: number, code: string, message: string) =>
  new Reply(status, errorBody(code, message))

class QuietSocket {
  onopen = null
  onmessage = null
  onclose = null
  onerror = null
  close() {}
}

export function renderApp(initialPath: string, handlers: Handler[]) {
  const calls: Call[] = []
  const unexpected: string[] = []
  const all: Handler[] = [
    { path: '/api/v1/processing-runs', respond: page([]) }, // the layout asks for the newest run
    ...handlers,
  ].reverse() // the test's own handlers win over the default
  vi.stubGlobal('WebSocket', QuietSocket)
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: string, init: RequestInit = {}) => {
      const url = new URL(input)
      const method = init.method ?? 'GET'
      const call: Call = {
        method,
        path: url.pathname,
        query: url.searchParams,
        body: typeof init.body === 'string' ? JSON.parse(init.body) : undefined,
        authorization: (init.headers as Record<string, string> | undefined)?.Authorization ?? null,
      }
      calls.push(call)
      const handler = all.find(
        (h) =>
          (h.method ?? 'GET') === method &&
          (typeof h.path === 'string' ? h.path === url.pathname : h.path.test(url.pathname)),
      )
      if (handler === undefined) {
        unexpected.push(`${method} ${url.pathname}`)
        return new Response('{}', { status: 599 })
      }
      const answer = typeof handler.respond === 'function' ? handler.respond(call) : handler.respond
      if (answer instanceof Reply) {
        return new Response(JSON.stringify(answer.body), { status: answer.status })
      }
      return new Response(JSON.stringify(answer), { status: handler.status ?? 200 })
    }),
  )

  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const router = createMemoryRouter(routes, { initialEntries: [initialPath] })
  const utils = render(
    <QueryClientProvider client={queryClient}>
      <BackendProvider connection={connection}>
        <RouterProvider router={router} />
      </BackendProvider>
    </QueryClientProvider>,
  )
  return { ...utils, calls, unexpected, router, queryClient }
}

// --- the shapes the API returns, with sensible defaults ---------------------------------------

export const source = (over: Record<string, unknown> = {}) => ({
  id: 's1',
  type: 'IMAGE',
  display_name: 'beach.png',
  availability: 'AVAILABLE',
  processing_status: 'NOT_PROCESSED',
  thumbnail: null,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  ...over,
})

export const run = (over: Record<string, unknown> = {}) => ({
  id: 'r1',
  source_id: 's1',
  state: 'PENDING',
  parent_run_id: null,
  requested_at: '2026-01-01T00:00:00Z',
  started_at: null,
  completed_at: null,
  failed_at: null,
  failure_code: null,
  policy: {
    calibration_mode: 'UNCALIBRATED',
    decision_policy_version: 'development-uncalibrated-v1',
    calibrated: false,
  },
  job: {
    id: 'j1',
    state: 'QUEUED',
    priority: 'INTERACTIVE',
    attempt_number: 1,
    progress: null,
  },
  ...over,
})
