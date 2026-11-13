// The desktop video workflow, end to end (M6, TST-070): import a video, process it, pause it,
// resume it, and see who appears in it on the video screen.
//
// Real in this test: the web app, HTTP and WebSocket over a real loopback socket, the real backend
// started as the shell starts it, the real scheduler, frame sampling through the pinned LGPL
// ffmpeg, chunks, pause and resume at a chunk boundary, the tracker, acceptance and SQLite. Stood
// in for: the shell's native calls and the perception (the development profile's fake, which sees
// one face in the middle of every frame, the same person wherever the pixels are the same).
//
// A video never creates a person by itself, so the person must be known first: one frame of the
// clip, extracted by the same ffmpeg, is processed as a picture before the video. The clip is a
// single synthetic colour; no real face is used or committed.

import { spawnSync } from 'node:child_process'
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { App } from '@/app/App'
import type { BackendStatus } from '@/native/backend'
import { type RunningBackend, startBackend } from './backend'
import { TestSocket } from './socket'

const shell = vi.hoisted(() => ({
  status: { state: 'starting' } as BackendStatus,
  pick: [] as string[],
}))
vi.mock('@/native/backend', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/native/backend')>()),
  backendStatus: async () => shell.status,
  chooseImages: async () => shell.pick,
}))

const LONG = { timeout: 120_000 }
// Two minutes: 240 frames at two a second, twelve chunks. The pause does not race the run: the
// development profile's detection waits while the gate file exists (FACEIDENTIFY_DEVELOPMENT_GATE),
// so the run is held RUNNING until the pause is asked for, then let go to its chunk boundary.
const CLIP_SECONDS = 120
let root: string
let gate: string
let backend: RunningBackend | null = null

function ffmpeg(args: string[]): void {
  const directory = process.env.FACEIDENTIFY_FFMPEG_DIR
  if (!directory) throw new Error('set FACEIDENTIFY_FFMPEG_DIR to the pinned ffmpeg (CI does)')
  const done = spawnSync(join(directory, 'ffmpeg.exe'), ['-v', 'error', '-y', ...args])
  if (done.status !== 0) throw new Error(`ffmpeg failed: ${done.stderr.toString()}`)
}

beforeAll(() => {
  root = mkdtempSync(join(tmpdir(), 'faceidentify-e2e-video-'))
  mkdirSync(join(root, 'library'))
  gate = join(root, 'gate')
  process.env.FACEIDENTIFY_DEVELOPMENT_GATE = gate // the backend inherits it
  window.location.hash = '#/library'
})

beforeEach(() => {
  vi.stubGlobal('WebSocket', TestSocket)
})

afterAll(async () => {
  rmSync(gate, { force: true })
  delete process.env.FACEIDENTIFY_DEVELOPMENT_GATE
  await backend?.stop()
  rmSync(root, { recursive: true, force: true, maxRetries: 10, retryDelay: 200 })
})

describe('the desktop video workflow', () => {
  it('processes a video, pauses and resumes it, and shows who appears in it', async () => {
    const user = userEvent.setup()
    const scene = join(root, 'scene.mp4')
    const still = join(root, 'still.png')
    ffmpeg(['-f', 'lavfi', '-i', 'color=c=0xC80A0A:size=64x48:rate=2', '-t', String(CLIP_SECONDS)]
      .concat(['-c:v', 'libopenh264', '-pix_fmt', 'yuv420p', scene])) // prettier-ignore
    ffmpeg(['-i', scene, '-frames:v', '1', still])

    backend = await startBackend(join(root, 'library'), join(root, 'local'))
    shell.status = { state: 'ready', connection: backend.connection }
    render(<App />)
    expect(await screen.findByText('No images yet', {}, LONG)).toBeInTheDocument()

    // the picture and the video, through the (stood-in) native picker
    shell.pick = [still, scene]
    await user.click(screen.getByRole('button', { name: 'Import images' }))
    expect(await screen.findByText('scene', {}, LONG)).toBeInTheDocument()

    // the picture first: it is the person the video will be recognised against
    await user.click(await screen.findByRole('button', { name: 'Process still' }, LONG))
    await waitFor(() => expect(screen.getAllByText('Done')).toHaveLength(1), LONG)
    await user.click(screen.getByRole('link', { name: 'People' }))
    const person = within(
      await screen.findByRole('link', { name: /Person [0-9A-F]{6}/ }, LONG),
    ).getByText(/Person [0-9A-F]{6}/).textContent!

    // the video: process it, pause it on its screen while it is held, let the chunk end, resume
    writeFileSync(gate, '')
    await user.click(screen.getByRole('link', { name: 'Library' }))
    await user.click(await screen.findByRole('button', { name: 'Process scene' }, LONG))
    await user.click((await screen.findAllByRole('link', { name: /scene/ }, LONG))[0])
    await user.click(await screen.findByRole('button', { name: 'Pause' }, LONG))
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Pause' })).toBeNull(), LONG)
    expect(screen.queryByRole('button', { name: 'Resume' })).toBeNull() // pausing, still held
    rmSync(gate)
    await user.click(await screen.findByRole('button', { name: 'Resume' }, LONG))
    expect(await screen.findByRole('heading', { name: 'Appearances' }, LONG)).toBeInTheDocument()

    // the person from the picture appears in the video, over its time
    const appearances = screen.getByRole('heading', { name: 'Appearances' }).parentElement!
    expect(within(appearances).getByRole('link', { name: person })).toBeInTheDocument()
    expect(within(appearances).getByText(/^0:00 to /)).toBeInTheDocument()
    // the run's own state is fetched apart from the appearances: it reaches the screen a moment later
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Pause' })).toBeNull(), LONG)

    expect(await backend.stop()).toBe(0)
    backend = null
  }, 900_000)
})
