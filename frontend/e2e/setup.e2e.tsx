// The first-run setup, end to end (M8 step 5(d)): the real web app and the real backend, started
// as the shell starts it, on the development profile and a scratch state folder. The user points at
// a folder holding stand-in model files that declare themselves a fixture (only the development
// profile accepts one), then chooses how recognition works; the policy lands where the real
// profile reads it. The weights are never involved.

import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { App } from '@/app/App'
import type { BackendStatus } from '@/native/backend'
import { type RunningBackend, startBackend } from './backend'
import { TestSocket } from './socket'

const shell = vi.hoisted(() => ({ status: { state: 'starting' } as BackendStatus }))
vi.mock('@/native/backend', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/native/backend')>()),
  backendStatus: async () => shell.status,
}))

const LONG = { timeout: 90_000 }
let root: string
let backend: RunningBackend | null = null

beforeAll(() => {
  root = mkdtempSync(join(tmpdir(), 'faceidentify-setup-e2e-'))
  mkdirSync(join(root, 'library'))
  window.location.hash = '#/setup'
})

beforeEach(() => {
  vi.stubGlobal('WebSocket', TestSocket)
})

afterAll(async () => {
  await backend?.stop()
  rmSync(root, { recursive: true, force: true, maxRetries: 10, retryDelay: 200 })
})

describe('the first-run setup', () => {
  it('installs stand-in models and saves the recognition mode the user chose', async () => {
    const user = userEvent.setup()
    const models = join(root, 'downloaded')
    mkdirSync(models)
    writeFileSync(join(models, 'det_10g.onnx'), 'a stand-in detector')
    writeFileSync(join(models, 'w600k_r50.onnx'), 'a stand-in embedder')
    writeFileSync(join(models, 'fixture.json'), JSON.stringify({ fixture: true }))
    const state = join(root, 'local')
    backend = await startBackend(join(root, 'library'), state)
    shell.status = { state: 'ready', connection: backend.connection }

    render(<App />)

    // step 1: the licence and the files are shown; the models are installed from the folder
    expect(await screen.findByText(/non-commercial research purposes only/, {}, LONG)).toBeVisible()
    await user.type(screen.getByLabelText(/downloaded zip, or the folder/), models)
    await user.click(screen.getByRole('button', { name: 'Install the models' }))
    expect(await screen.findByText('The face models are installed.', {}, LONG)).toBeVisible()

    // step 2: Assisted is offered first; the user chooses Automatic after seeing what it saves
    expect(await screen.findByText(/You have not chosen yet/, {}, LONG)).toBeVisible()
    await user.click(screen.getByRole('radio', { name: /Automatic/ }))
    await user.click(screen.getByRole('button', { name: 'Use Automatic recognition' }))
    expect(await screen.findByText('Current choice: Automatic.', {}, LONG)).toBeVisible()

    // the policy is where the real profile reads it, and is exactly the approved one
    const policy = JSON.parse(
      readFileSync(join(state, 'policies', 'insightface-buffalo-l.json'), 'utf8'),
    )
    expect(policy).toMatchObject({
      version: 'buffalo-l-verified-match-v1',
      match_threshold: 0.45,
      margin: 0.1,
      new_identity_ceiling: -1.0,
    })
  })
})
