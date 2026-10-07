import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  EVENTS_PROTOCOL,
  EventsClient,
  parseEnvelope,
  retryDelay,
  type EventEnvelope,
  type EventsStatus,
  type SocketLike,
} from './events'

class FakeSocket implements SocketLike {
  onopen: (() => void) | null = null
  onmessage: ((message: { data: unknown }) => void) | null = null
  onclose: (() => void) | null = null
  onerror: (() => void) | null = null
  closed = false
  readonly url: string
  readonly protocols: string[]
  constructor(url: string, protocols: string[]) {
    this.url = url
    this.protocols = protocols
  }
  close() {
    this.closed = true
  }
  send(event: Partial<EventEnvelope>) {
    this.onmessage?.({ data: JSON.stringify(event) })
  }
}

const envelope = (sequence: number, type = 'processing_run.updated'): Partial<EventEnvelope> => ({
  version: 1,
  event_id: `e${sequence}`,
  sequence,
  type,
  occurred_at: '2026-01-01T00:00:00Z',
  resource: { type: 'processing_run', id: 'r1' },
  data: {},
})

function setup() {
  const sockets: FakeSocket[] = []
  const log = { events: [] as EventEnvelope[], resyncs: 0, statuses: [] as EventsStatus[] }
  const client = new EventsClient(
    'ws://127.0.0.1:5000/api/v1/events',
    'tok',
    {
      onEvent: (event) => log.events.push(event),
      onResync: () => (log.resyncs += 1),
      onStatus: (status) => log.statuses.push(status),
    },
    (url, protocols) => {
      const socket = new FakeSocket(url, protocols)
      sockets.push(socket)
      return socket
    },
  )
  return { client, sockets, log }
}

describe('EventsClient', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  it('offers the application protocol and the token, and refetches once connected', () => {
    const { client, sockets, log } = setup()

    client.start()
    sockets[0].onopen?.()

    expect(sockets[0].url).toBe('ws://127.0.0.1:5000/api/v1/events')
    expect(sockets[0].protocols).toEqual([EVENTS_PROTOCOL, 'fi.tok'])
    expect(log.statuses).toEqual(['connecting', 'open'])
    expect(log.resyncs).toBe(1)
  })

  it('delivers events after the greeting, in order, and ignores a repeat', () => {
    const { client, sockets, log } = setup()
    client.start()
    sockets[0].onopen?.()

    sockets[0].send(envelope(7, 'system.hello'))
    sockets[0].send(envelope(8))
    sockets[0].send(envelope(8)) // a repeat
    sockets[0].send(envelope(7)) // older than the last
    sockets[0].send(envelope(9))

    expect(log.events.map((e) => e.sequence)).toEqual([8, 9])
    expect(log.resyncs).toBe(1) // only the connection's own
  })

  it('asks for a refetch when the numbering skips (an event was lost)', () => {
    const { client, sockets, log } = setup()
    client.start()
    sockets[0].onopen?.()
    sockets[0].send(envelope(1, 'system.hello'))

    sockets[0].send(envelope(2))
    sockets[0].send(envelope(5)) // 3 and 4 never arrived

    expect(log.events.map((e) => e.sequence)).toEqual([2, 5])
    expect(log.resyncs).toBe(2)
  })

  it('notices a single lost event, and one lost right after the greeting', () => {
    const { client, sockets, log } = setup()
    client.start()
    sockets[0].onopen?.()
    sockets[0].send(envelope(10, 'system.hello'))
    expect(log.resyncs).toBe(1)

    sockets[0].send(envelope(12)) // 11 was lost between the greeting and this one
    expect(log.resyncs).toBe(2)
    sockets[0].send(envelope(13))
    expect(log.resyncs).toBe(2) // consecutive: nothing lost
    sockets[0].send(envelope(15)) // 14 was lost
    expect(log.resyncs).toBe(3)
  })

  it('does not treat the first event as a gap when there was no greeting', () => {
    const { client, sockets, log } = setup()
    client.start()
    sockets[0].onopen?.()

    sockets[0].send(envelope(40))

    expect(log.events.map((e) => e.sequence)).toEqual([40])
    expect(log.resyncs).toBe(1)
  })

  it('ignores what is not an event', () => {
    const { client, sockets, log } = setup()
    client.start()

    sockets[0].onmessage?.({ data: 'not json' })
    sockets[0].onmessage?.({ data: new ArrayBuffer(2) })
    sockets[0].onmessage?.({
      data: JSON.stringify({ version: 2, sequence: 1, type: 'x', resource: { id: 'a' } }),
    })
    sockets[0].onmessage?.({
      data: JSON.stringify({ version: 1, sequence: 'one', type: 'x', resource: { id: 'a' } }),
    })
    sockets[0].onerror?.()

    expect(log.events).toEqual([])
  })

  it('reconnects with a growing delay, restarts from a new greeting, and resets after success', () => {
    const { client, sockets, log } = setup()
    client.start()
    sockets[0].onopen?.()
    sockets[0].send(envelope(5, 'system.hello'))

    sockets[0].onclose?.()
    expect(log.statuses.at(-1)).toBe('reconnecting')
    vi.advanceTimersByTime(retryDelay(0) - 1)
    expect(sockets).toHaveLength(1)
    vi.advanceTimersByTime(1)
    expect(sockets).toHaveLength(2)

    sockets[1].onclose?.() // it failed to connect: the next wait is longer
    vi.advanceTimersByTime(retryDelay(0))
    expect(sockets).toHaveLength(2)
    vi.advanceTimersByTime(retryDelay(1) - retryDelay(0))
    expect(sockets).toHaveLength(3)

    sockets[2].onopen?.()
    sockets[2].send(envelope(100)) // a new connection: no greeting yet, so no false gap
    expect(log.events.map((e) => e.sequence)).toEqual([100])
    sockets[2].onclose?.()
    vi.advanceTimersByTime(retryDelay(0))
    expect(sockets).toHaveLength(4) // the delay started over after a success
  })

  it('stops for good: no reconnection, the socket is closed, and its late close is ignored', () => {
    const { client, sockets, log } = setup()
    client.start()
    sockets[0].onopen?.()

    client.stop()
    sockets[0].onclose?.()
    vi.advanceTimersByTime(60_000)

    expect(sockets).toHaveLength(1)
    expect(sockets[0].closed).toBe(true)
    expect(log.statuses.at(-1)).toBe('stopped')
  })

  it('stopping while a reconnection is pending cancels it', () => {
    const { client, sockets } = setup()
    client.start()
    sockets[0].onclose?.()

    client.stop()
    vi.advanceTimersByTime(60_000)

    expect(sockets).toHaveLength(1)
  })

  it('a close from an older socket does not disturb the current one', () => {
    const { client, sockets } = setup()
    client.start()
    sockets[0].onclose?.()
    vi.advanceTimersByTime(retryDelay(0))
    expect(sockets).toHaveLength(2)

    sockets[0].onclose?.() // the first one reports closing again

    vi.advanceTimersByTime(60_000)
    expect(sockets).toHaveLength(2)
  })
})

describe('retryDelay', () => {
  it('doubles from half a second and stops growing at fifteen', () => {
    expect([0, 1, 2, 3].map(retryDelay)).toEqual([500, 1000, 2000, 4000])
    expect(retryDelay(10)).toBe(15_000)
    expect(retryDelay(50)).toBe(15_000)
  })
})

describe('parseEnvelope', () => {
  it('accepts a well-formed event and rejects anything else', () => {
    const good = JSON.stringify(envelope(3))

    expect(parseEnvelope(good)?.sequence).toBe(3)
    expect(parseEnvelope(JSON.stringify(null))).toBeNull()
    expect(parseEnvelope(JSON.stringify([1]))).toBeNull()
    expect(parseEnvelope(42)).toBeNull()
  })
})
