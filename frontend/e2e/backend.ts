// Starts the real backend the way the desktop shell does (see desktop/src-tauri/src/sidecar.rs):
// the token only in the environment, `--parent-pid`, `--stdin-lifeline`, the development profile,
// one JSON handshake line on stdout, a clean stop by closing standard input.

import { type ChildProcessWithoutNullStreams, spawn } from 'node:child_process'
import { randomBytes } from 'node:crypto'
import { once } from 'node:events'
import { existsSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { createInterface } from 'node:readline'
import type { Connection } from '../src/native/backend'

const REPOSITORY = resolve(import.meta.dirname, '..', '..')
const TOKEN_ENV = 'FACEIDENTIFY_LAUNCH_TOKEN'

function python(): string {
  if (process.env.FACEIDENTIFY_PYTHON) return process.env.FACEIDENTIFY_PYTHON
  const venv = process.platform === 'win32' ? join('Scripts', 'python.exe') : join('bin', 'python')
  const found = join(REPOSITORY, '.venv', venv)
  if (!existsSync(found)) throw new Error(`no Python at ${found}: run \`uv sync\` first`)
  return found
}

export interface RunningBackend {
  connection: Connection
  /** Ask for a clean stop (close its standard input) and return its exit code. */
  stop(): Promise<number | null>
}

export async function startBackend(
  libraryRoot: string,
  localStateRoot: string,
): Promise<RunningBackend> {
  const token = randomBytes(32).toString('base64url')
  const child: ChildProcessWithoutNullStreams = spawn(
    python(),
    [
      '-m',
      'backend.api.host',
      '--library-root',
      libraryRoot,
      '--local-state-root',
      localStateRoot,
      '--parent-pid',
      String(process.pid),
      '--stdin-lifeline',
      '--development-profile',
    ],
    { cwd: REPOSITORY, env: { ...process.env, [TOKEN_ENV]: token }, windowsHide: true },
  )
  const errors: string[] = []
  child.stderr.on('data', (chunk: Buffer) => errors.push(chunk.toString()))
  const lines = createInterface({ input: child.stdout })
  const first = await Promise.race([
    once(lines, 'line').then(([line]) => String(line)),
    once(child, 'exit').then(() => {
      throw new Error(`the backend stopped while starting: ${errors.join('').slice(-2000)}`)
    }),
    new Promise<never>((_, reject) =>
      setTimeout(() => reject(new Error('the backend did not report in 120 s')), 120_000),
    ),
  ])
  lines.on('line', () => undefined) // keep draining
  const handshake = JSON.parse(first) as { host: string; port: number; protocol: string }
  const base = `http://${handshake.host}:${handshake.port}`
  return {
    connection: {
      base_url: base,
      events_url: `ws://${handshake.host}:${handshake.port}/api/v1/events`,
      token,
      protocol: handshake.protocol,
    },
    async stop() {
      if (child.exitCode !== null) return child.exitCode
      child.stdin.end()
      const timer = setTimeout(() => child.kill(), 60_000)
      const [code] = (await once(child, 'exit')) as [number | null]
      clearTimeout(timer)
      return code
    },
  }
}
