import { afterEach, describe, expect, it, vi } from 'vitest'
import { NO_SHELL_MESSAGE, backendStatus, chooseImages, inShell, libraryRoot } from './backend'

const invoke = vi.hoisted(() => vi.fn())
vi.mock('@tauri-apps/api/core', () => ({ invoke }))

afterEach(() => {
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
  invoke.mockReset()
})

describe('outside the desktop shell', () => {
  it('has no shell, no files to pick and no library folder', async () => {
    expect(inShell()).toBe(false)
    expect(await chooseImages()).toEqual([])
    expect(await libraryRoot()).toBe('')
  })

  it('fails with an explanation when no backend was named for development', async () => {
    vi.stubEnv('VITE_BACKEND_URL', '')
    vi.stubEnv('VITE_BACKEND_TOKEN', '')

    expect(await backendStatus()).toEqual({ state: 'failed', error: NO_SHELL_MESSAGE })
  })

  it('needs both the address and the token of a backend started by hand', async () => {
    vi.stubEnv('VITE_BACKEND_URL', 'http://127.0.0.1:8000')
    vi.stubEnv('VITE_BACKEND_TOKEN', '')
    expect(await backendStatus()).toEqual({ state: 'failed', error: NO_SHELL_MESSAGE })

    vi.stubEnv('VITE_BACKEND_URL', '')
    vi.stubEnv('VITE_BACKEND_TOKEN', 'dev-token')
    expect(await backendStatus()).toEqual({ state: 'failed', error: NO_SHELL_MESSAGE })
  })

  it('connects to a backend started by hand when it is named', async () => {
    vi.stubEnv('VITE_BACKEND_URL', 'http://127.0.0.1:8000')
    vi.stubEnv('VITE_BACKEND_TOKEN', 'dev-token')

    expect(await backendStatus()).toEqual({
      state: 'ready',
      connection: {
        base_url: 'http://127.0.0.1:8000',
        events_url: 'ws://127.0.0.1:8000/api/v1/events',
        token: 'dev-token',
        protocol: 'faceidentify.v1',
      },
    })
  })
})

describe('inside the desktop shell', () => {
  it('asks the shell, never the network, for the backend, the files and the library', async () => {
    vi.stubGlobal('__TAURI_INTERNALS__', {})
    ;(window as unknown as Record<string, unknown>).__TAURI_INTERNALS__ = {}
    invoke.mockImplementation(async (command: string) => {
      if (command === 'backend_status') return { state: 'starting' }
      if (command === 'choose_images') return ['C:\\pictures\\a.png']
      if (command === 'library_info') return { library_root: 'C:\\FaceIdentify\\library' }
      throw new Error(`unexpected command ${command}`)
    })

    try {
      expect(inShell()).toBe(true)
      expect(await backendStatus()).toEqual({ state: 'starting' })
      expect(await chooseImages()).toEqual(['C:\\pictures\\a.png'])
      expect(await libraryRoot()).toBe('C:\\FaceIdentify\\library')
    } finally {
      delete (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__
    }
  })
})
