// The complete desktop image workflow, end to end, with a restart in the middle (M4's definition of
// done; TST-052, TST-053 in the web view's terms).
//
// Real in this test: the web app (React, queries, routes, the event client), HTTP and WebSocket
// over a real loopback socket, the real FastAPI backend started as the shell starts it, the real
// scheduler, executor, acceptance, SQLite and the vector index, on files made here. Stood in for:
// the desktop shell's two native calls (where the backend is, and the file picker), and the
// perception, which is the development profile's fake (no real model is cleared yet, issue #69).

import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { screen, waitFor, within } from '@testing-library/react'
import { render } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { App } from '@/app/App'
import type { BackendStatus } from '@/native/backend'
import { type RunningBackend, startBackend } from './backend'
import { TestSocket } from './socket'
import { solidPng } from './png'

const shell = vi.hoisted(() => ({
  status: { state: 'starting' } as BackendStatus,
  pick: [] as string[],
}))
vi.mock('@/native/backend', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/native/backend')>()),
  backendStatus: async () => shell.status,
  chooseImages: async () => shell.pick,
}))

const LONG = { timeout: 90_000 }
let root: string
let pictures: string
let backend: RunningBackend | null = null

function picture(name: string, colour: [number, number, number]): string {
  const path = join(pictures, name)
  writeFileSync(path, solidPng(8, 6, colour))
  return path
}

async function launch(library = 'library') {
  backend = await startBackend(join(root, library), join(root, `local-${library}`))
  shell.status = { state: 'ready', connection: backend.connection }
}

async function quit(): Promise<number | null> {
  const code = (await backend?.stop()) ?? null
  backend = null
  shell.status = { state: 'starting' } // nothing is serving until the next launch
  return code
}

beforeAll(() => {
  root = mkdtempSync(join(tmpdir(), 'faceidentify-e2e-'))
  pictures = join(root, 'pictures')
  mkdirSync(join(root, 'library'))
  mkdirSync(join(root, 'corrections'))
  mkdirSync(pictures)
  window.location.hash = '#/library'
})

// (restored after every test by the config, so set again before each one)
beforeEach(() => {
  vi.stubGlobal('WebSocket', TestSocket)
})

afterAll(async () => {
  await quit()
  // (Windows may hold a file for a moment after the process exits: retry before giving up)
  rmSync(root, { recursive: true, force: true, maxRetries: 10, retryDelay: 200 })
})

describe('the desktop image workflow', () => {
  it('imports, processes, shows who is in each image, and still does after a restart', async () => {
    const user = userEvent.setup()
    const red = picture('red.png', [200, 10, 10])
    const sameRed = picture('also-red.png', [200, 10, 10])
    const blue = picture('blue.png', [10, 10, 200])

    // --- first launch: an empty library ---------------------------------------------------
    await launch()
    const first = render(<App />)
    expect(await screen.findByText('No images yet', {}, LONG)).toBeInTheDocument()

    // import three images through the (stood-in) native picker
    shell.pick = [red, sameRed, blue]
    await user.click(screen.getByRole('button', { name: 'Import images' }))
    expect(await screen.findByRole('status', { name: 'Library notice' }, LONG)).toHaveTextContent(
      'Imported 3 images.',
    )
    for (const name of ['red', 'also-red', 'blue']) {
      expect(await screen.findByText(name)).toBeInTheDocument()
    }
    expect(await screen.findAllByText('Not processed')).toHaveLength(3)

    // process each; the backend does the work in the background and the cards say when it is done
    for (const name of ['red', 'also-red', 'blue']) {
      await user.click(screen.getByRole('button', { name: `Process ${name}` }))
    }
    await waitFor(() => expect(screen.getAllByText('Done')).toHaveLength(3), LONG)

    // results made with the development policy are labelled as such, wherever they are shown
    expect(await screen.findByRole('note', {}, LONG)).toHaveTextContent('Uncalibrated results.')

    // the same picture is the same person; a different picture is a different person
    await user.click(screen.getByRole('link', { name: 'People' }))
    const people = await screen.findAllByRole('link', { name: /Person [0-9A-F]{6}/ }, LONG)
    expect(people).toHaveLength(2)
    const counts = people.map((p) => within(p).getByText(/appearances? in/).textContent).sort()
    expect(counts).toEqual(['1 appearance in 1 image', '2 appearances in 2 images'])

    // the person seen twice: both images are listed, each a way back to the image
    const twice = people.find((p) => /2 appearances/.test(p.textContent ?? ''))!
    const name = within(twice).getByText(/Person [0-9A-F]{6}/).textContent!
    await user.click(twice)
    expect(await screen.findByRole('heading', { name }, LONG)).toBeInTheDocument()
    expect(await screen.findByText(/Appears 2 times in 2 images/, {}, LONG)).toBeInTheDocument()
    const where = await screen.findAllByRole('link', { name: /red/ }, LONG)
    expect(where.length).toBeGreaterThanOrEqual(2)

    // an image shows its face and goes to the person
    await user.click(where[0])
    expect(await screen.findByRole('link', { name: `${name}: open` }, LONG)).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Processing history' })).toBeInTheDocument()

    // --- the application closes; the backend stops cleanly ---------------------------------
    first.unmount()
    window.location.hash = '#/library'
    expect(await quit()).toBe(0)

    // --- second launch: everything is still there -----------------------------------------
    await launch()
    render(<App />)
    for (const picked of ['red', 'also-red', 'blue']) {
      expect(await screen.findByText(picked, {}, LONG)).toBeInTheDocument()
    }
    expect(screen.getAllByText('Done')).toHaveLength(3)
    await user.click(screen.getByRole('link', { name: 'People' }))
    const again = await screen.findAllByRole('link', { name: /Person [0-9A-F]{6}/ }, LONG)
    expect(again.map((p) => within(p).getByText(/Person [0-9A-F]{6}/).textContent).sort()).toEqual(
      people.map((p) => within(p).getByText(/Person [0-9A-F]{6}/).textContent).sort(),
    )

    // a new copy of the first picture is recognised from the stored memory: no new person
    shell.pick = [picture('red-again.png', [200, 10, 10])]
    await user.click(screen.getByRole('link', { name: 'Library' }))
    await user.click(await screen.findByRole('button', { name: 'Import images' }))
    await user.click(await screen.findByRole('button', { name: 'Process red-again' }, LONG))
    await waitFor(() => expect(screen.getAllByText('Done')).toHaveLength(4), LONG)
    await user.click(screen.getByRole('link', { name: 'People' }))
    await waitFor(() => {
      const now = screen.getAllByRole('link', { name: /Person [0-9A-F]{6}/ })
      expect(now).toHaveLength(2) // still two people
      expect(now.map((p) => within(p).getByText(/appearances? in/).textContent).sort()).toEqual([
        '1 appearance in 1 image',
        '3 appearances in 3 images',
      ])
    }, LONG)
    expect(await quit()).toBe(0)
  }, 600_000)

  it('keeps the corrections (confirm, move, someone new) after a restart', async () => {
    const user = userEvent.setup()
    const pick = [
      picture('c-red.png', [200, 10, 10]),
      picture('c-also-red.png', [200, 10, 10]),
      picture('c-blue.png', [10, 10, 200]),
    ]
    const personName = /Person [0-9A-F]{6}/
    // the emptied person stays in the library, with no appearances
    const AFTER = [
      '0 appearances in 0 images',
      '1 appearance in 1 image',
      '2 appearances in 2 images',
    ]
    const openImage = async (name: string) => {
      await user.click(screen.getByRole('link', { name: 'Library' }))
      await user.click((await screen.findAllByRole('link', { name }, LONG))[0])
      expect(
        await screen.findByRole('heading', { name: 'People in this image' }, LONG),
      ).toBeInTheDocument()
    }
    const check = async (name: string, choose: () => Promise<void>) => {
      await openImage(name)
      await user.click(await screen.findByRole('button', { name: 'Check this face' }, LONG))
      await choose()
      expect(await screen.findByText('Checked by you.', {}, LONG)).toBeInTheDocument()
    }
    const faceOf = async () =>
      (await screen.findByRole('link', { name: /: open$/ }, LONG))
        .getAttribute('aria-label')!
        .replace(': open', '')
    const peopleNow = async (expected: string[]) => {
      await user.click(screen.getByRole('link', { name: 'People' }))
      await waitFor(() => {
        const now = screen.getAllByRole('link', { name: personName })
        expect(now.map((p) => within(p).getByText(/appearances? in/).textContent).sort()).toEqual(
          expected,
        )
      }, LONG)
    }

    // --- first launch: three images, two people (red twice, blue once) -----------------------
    window.location.hash = '#/library' // the earlier test left the address on People
    await launch('corrections')
    const first = render(<App />)
    expect(await screen.findByText('No images yet', {}, LONG)).toBeInTheDocument()
    shell.pick = pick
    await user.click(screen.getByRole('button', { name: 'Import images' }))
    for (const name of ['c-red', 'c-also-red', 'c-blue']) {
      await user.click(await screen.findByRole('button', { name: `Process ${name}` }, LONG))
    }
    await waitFor(() => expect(screen.getAllByText('Done')).toHaveLength(3), LONG)
    await peopleNow(['1 appearance in 1 image', '2 appearances in 2 images'])
    const twice = screen
      .getAllByRole('link', { name: personName })
      .find((p) => /2 appearances/.test(p.textContent ?? ''))!
    const redPerson = within(twice).getByText(personName).textContent!

    // move the blue face to the person already seen twice (an existing identity)
    await check('c-blue', async () => {
      await user.selectOptions(
        screen.getByLabelText('This is someone already in the library'),
        redPerson,
      )
      await user.click(screen.getByRole('button', { name: 'Move this face' }))
    })
    expect(
      await screen.findByRole('link', { name: `${redPerson}: open` }, LONG),
    ).toBeInTheDocument()

    // say the second red face is someone new (a new identity)
    await check('c-also-red', async () => {
      await user.click(screen.getByRole('button', { name: 'This is someone new' }))
    })
    const newPerson = await faceOf()
    expect(newPerson).not.toBe(redPerson)

    // confirm the first red face where it is
    await check('c-red', async () => {
      await user.click(screen.getByRole('button', { name: `Yes, this is ${redPerson}` }))
    })
    await peopleNow(AFTER)

    // --- restart: the corrections are the authoritative placement ---------------------------
    first.unmount()
    window.location.hash = '#/library'
    expect(await quit()).toBe(0)
    await launch('corrections')
    render(<App />)
    expect(await screen.findByText('c-blue', {}, LONG)).toBeInTheDocument()
    await peopleNow(AFTER)
    const after = screen.getAllByRole('link', { name: personName }).map((p) => p.textContent ?? '')
    expect(after.some((t) => t.includes(redPerson) && /2 appearances/.test(t))).toBe(true)
    expect(after.some((t) => t.includes(newPerson) && /1 appearance /.test(t))).toBe(true)
    for (const [image, person] of [
      ['c-blue', redPerson],
      ['c-also-red', newPerson],
      ['c-red', redPerson],
    ]) {
      await openImage(image)
      expect(await screen.findByRole('link', { name: `${person}: open` }, LONG)).toBeInTheDocument()
      expect(await screen.findByText('Checked by you.', {}, LONG)).toBeInTheDocument()
    }
    expect(await quit()).toBe(0)
  }, 600_000)
})
