// The event connection (`WS /api/v1/events`): notifications that something changed.
//
// REST stays authoritative, so an event never carries state a screen relies on: it only says what
// to refetch. Delivery is best effort (events can be dropped, repeated or coalesced), so this
// client numbers what it sees: a repeat is ignored, a gap or a (re)connection means "refetch
// everything" (`onResync`), and a lost connection is retried with a growing delay.

export const EVENTS_PROTOCOL = 'faceidentify.v1'

export interface EventEnvelope {
  version: number
  event_id: string
  sequence: number
  type: string
  occurred_at: string
  resource: { type: string; id: string }
  data: Record<string, unknown>
}

export type EventsStatus = 'connecting' | 'open' | 'reconnecting' | 'stopped'

export interface SocketLike {
  onopen: (() => void) | null
  onmessage: ((message: { data: unknown }) => void) | null
  onclose: (() => void) | null
  onerror: (() => void) | null
  close(): void
}

export type SocketFactory = (url: string, protocols: string[]) => SocketLike

export interface EventsHandlers {
  onEvent(event: EventEnvelope): void
  /** Something may have been missed: refetch what is on screen. */
  onResync(): void
  onStatus(status: EventsStatus): void
}

const MIN_DELAY_MS = 500
const MAX_DELAY_MS = 15_000

export function retryDelay(attempt: number): number {
  return Math.min(MIN_DELAY_MS * 2 ** attempt, MAX_DELAY_MS)
}

export function parseEnvelope(data: unknown): EventEnvelope | null {
  if (typeof data !== 'string') return null
  try {
    const value = JSON.parse(data) as Partial<EventEnvelope>
    const valid =
      value !== null &&
      typeof value === 'object' &&
      value.version === 1 &&
      typeof value.sequence === 'number' &&
      typeof value.type === 'string' &&
      typeof value.resource?.id === 'string'
    return valid ? (value as EventEnvelope) : null
  } catch {
    return null
  }
}

// The browser's socket has the handlers this client uses (typed more loosely here so a test can
// stand in for it).
const browserSocket: SocketFactory = (url, protocols) =>
  new WebSocket(url, protocols) as unknown as SocketLike

export class EventsClient {
  private socket: SocketLike | null = null
  private timer: ReturnType<typeof setTimeout> | null = null
  private attempt = 0
  private last: number | null = null
  private stopped = false
  private readonly url: string
  private readonly token: string
  private readonly handlers: EventsHandlers
  private readonly open: SocketFactory

  constructor(
    url: string,
    token: string,
    handlers: EventsHandlers,
    open: SocketFactory = browserSocket,
  ) {
    this.url = url
    this.token = token
    this.handlers = handlers
    this.open = open
  }

  start(): void {
    this.release() // a second start never leaves the first connection (or its retry) running
    this.stopped = false
    this.attempt = 0
    this.connect()
  }

  stop(): void {
    this.release()
    this.stopped = true
    this.handlers.onStatus('stopped')
  }

  /** Drop the pending retry and the connection, and detach its handlers so nothing late reaches us. */
  private release(): void {
    if (this.timer !== null) clearTimeout(this.timer)
    this.timer = null
    const socket = this.socket
    this.socket = null
    if (socket) {
      socket.onopen = null
      socket.onmessage = null
      socket.onclose = null
      socket.onerror = null
      socket.close()
    }
  }

  private connect(): void {
    this.handlers.onStatus(this.attempt === 0 ? 'connecting' : 'reconnecting')
    this.last = null // a new connection starts with its own greeting
    const socket = this.open(this.url, [EVENTS_PROTOCOL, `fi.${this.token}`])
    this.socket = socket
    socket.onopen = () => {
      if (this.socket !== socket) return // released while it was opening
      this.attempt = 0
      this.handlers.onStatus('open')
      this.handlers.onResync() // whatever changed before the connection existed
    }
    socket.onmessage = (message) => {
      if (this.socket === socket) this.receive(message.data)
    }
    socket.onclose = () => this.lost(socket)
    socket.onerror = () => undefined // `close` follows an error: one place handles both
  }

  private receive(data: unknown): void {
    const event = parseEnvelope(data)
    if (event === null) return
    if (event.type === 'system.hello') {
      this.last = event.sequence // the baseline: the first real event is the next number
      return
    }
    if (this.last !== null && event.sequence <= this.last) return // a repeat
    const gap = this.last !== null && event.sequence > this.last + 1
    this.last = event.sequence
    if (gap) this.handlers.onResync()
    this.handlers.onEvent(event)
  }

  private lost(socket: SocketLike): void {
    if (this.stopped || this.socket !== socket) return
    this.socket = null
    this.handlers.onStatus('reconnecting')
    this.timer = setTimeout(() => {
      this.timer = null
      this.connect()
    }, retryDelay(this.attempt))
    this.attempt += 1
  }
}
