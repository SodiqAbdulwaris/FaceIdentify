import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { BackendStatus } from '@/native/backend'
import { BackendGate } from './BackendGate'

const status = vi.hoisted(() => ({ current: { state: 'starting' } as unknown }))
vi.mock('@/native/backend', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/native/backend')>()),
  backendStatus: vi.fn(async () => status.current as BackendStatus),
}))

const connection = {
  base_url: 'http://127.0.0.1:5000',
  events_url: 'ws://127.0.0.1:5000/api/v1/events',
  token: 'tok',
  protocol: 'faceidentify.v1',
}

class QuietSocket {
  onopen = null
  onmessage = null
  onclose = null
  onerror = null
  close() {}
}

function readinessIs(...bodies: Array<{ state: string; failure?: string } | 'down'>) {
  const queue = [...bodies]
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => {
      const next = queue.length > 1 ? queue.shift()! : queue[0]
      if (next === 'down') throw new TypeError('connection refused')
      return new Response(JSON.stringify(next), { status: 200 })
    }),
  )
}

function renderGate() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <BackendGate>
        <p>the library</p>
      </BackendGate>
    </QueryClientProvider>,
  )
}

describe('BackendGate', () => {
  beforeEach(() => {
    vi.stubGlobal('WebSocket', QuietSocket)
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.useRealTimers()
  })

  it('says the app is starting while the shell has not yet started the backend', async () => {
    status.current = { state: 'starting' }

    renderGate()

    expect(await screen.findByRole('heading', { name: 'Starting FaceIdentify…' })).toBeInTheDocument()
    expect(screen.queryByText('the library')).toBeNull()
  })

  it('shows why the backend could not start', async () => {
    status.current = { state: 'failed', error: 'the backend stopped while starting (exit code 3)' }

    renderGate()

    expect(await screen.findByRole('heading', { name: 'FaceIdentify could not start' })).toBeInTheDocument()
    expect(screen.getByText(/exit code 3/)).toBeInTheDocument()
  })

  it('waits while the library opens, then shows the app', async () => {
    status.current = { state: 'ready', connection }
    readinessIs({ state: 'INITIALIZING' }, { state: 'READY' })

    renderGate()

    expect(await screen.findByRole('heading', { name: 'Opening your library…' })).toBeInTheDocument()
    expect(await screen.findByText('the library', {}, { timeout: 3000 })).toBeInTheDocument()
  })

  it('uses the library when it is degraded but serving', async () => {
    status.current = { state: 'ready', connection }
    readinessIs({ state: 'DEGRADED' })

    renderGate()

    expect(await screen.findByText('the library')).toBeInTheDocument()
  })

  it('keeps trying while the backend is not yet answering', async () => {
    status.current = { state: 'ready', connection }
    readinessIs('down', { state: 'READY' })

    renderGate()

    expect(await screen.findByText('the library', {}, { timeout: 3000 })).toBeInTheDocument()
  })

  it('tells the user when the library could not be opened, and why', async () => {
    status.current = { state: 'ready', connection }
    readinessIs({ state: 'FAILED', failure: 'LibraryLockedError' })

    renderGate()

    expect(await screen.findByRole('heading', { name: 'Your library could not be opened' })).toBeInTheDocument()
    expect(screen.getByText('Reason: LibraryLockedError')).toBeInTheDocument()
    expect(screen.queryByText('the library')).toBeNull()
  })

  it('sends the launch token when it asks the backend whether it is ready', async () => {
    status.current = { state: 'ready', connection }
    readinessIs({ state: 'READY' })

    renderGate()
    await screen.findByText('the library')

    const call = vi.mocked(fetch).mock.calls[0]
    const headers = call[1]?.headers as Record<string, string>
    expect(call[0]).toBe('http://127.0.0.1:5000/readiness')
    expect(headers.Authorization).toBe('Bearer tok')
  })
})
