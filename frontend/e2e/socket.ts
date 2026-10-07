// A browser-style WebSocket for the end-to-end test. The test runs in jsdom, whose `Event` is not
// the one Node's own WebSocket dispatches, so the real socket is `ws` wrapped in the four handlers
// the app's event client uses.

import WebSocketClient from 'ws'

export class TestSocket {
  onopen: (() => void) | null = null
  onmessage: ((message: { data: unknown }) => void) | null = null
  onclose: (() => void) | null = null
  onerror: (() => void) | null = null
  private readonly socket: WebSocketClient

  constructor(url: string, protocols: string[]) {
    this.socket = new WebSocketClient(url, protocols)
    this.socket.on('open', () => this.onopen?.())
    this.socket.on('message', (data) => this.onmessage?.({ data: data.toString() }))
    this.socket.on('close', () => this.onclose?.())
    this.socket.on('error', () => this.onerror?.())
  }

  close(): void {
    this.socket.close()
  }
}
