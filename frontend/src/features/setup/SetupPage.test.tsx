import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { apiError, renderApp, type Handler } from '@/test/harness'

const chooseModels = vi.hoisted(() => vi.fn<(kind: 'zip' | 'folder') => Promise<string | null>>())
const chooseLibrary = vi.hoisted(() => vi.fn<() => Promise<string | null>>())
vi.mock('@/native/backend', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/native/backend')>()),
  inShell: () => true,
  chooseModels,
  chooseLibrary,
  libraryRoot: async () => 'C:\\Users\\me\\Documents\\FaceIdentify',
}))

const MODELS = '/api/v1/runtime/models'
const MODE = '/api/v1/runtime/recognition-mode'

const files = [
  { name: 'det_10g.onnx', size_bytes: 16_923_827, sha256: 'a'.repeat(64) },
  { name: 'w600k_r50.onnx', size_bytes: 174_383_860, sha256: 'b'.repeat(64) },
]
const models = (installed: boolean) => ({
  package_key: 'insightface-buffalo-l',
  installed,
  licence: 'InsightFace pretrained models: non-commercial research purposes only',
  source_url: 'https://example.test/buffalo_l',
  files,
})
const assisted = {
  mode: 'ASSISTED',
  description: 'Every face after the first waits for you to confirm it.',
  policy: { version: 'buffalo-l-abstain-only-v1', match_threshold: 2.0 },
}
const automatic = {
  mode: 'AUTOMATIC',
  description: 'A clear match is placed automatically.',
  policy: { version: 'buffalo-l-verified-match-v1', match_threshold: 0.45 },
}
const modeState = (mode: string) => ({ mode, options: [assisted, automatic] })
const readiness = (capabilities: Record<string, string> = {}) => ({ state: 'READY', capabilities })

function setup(extra: Handler[] = [], installed = false, mode = 'NONE') {
  return renderApp('/setup', [
    { path: MODELS, respond: models(installed) },
    { path: MODE, respond: modeState(mode) },
    { path: '/readiness', respond: readiness() },
    ...extra,
  ])
}

beforeEach(() => {
  chooseModels.mockReset()
  chooseLibrary.mockReset()
})

describe('first-run setup', () => {
  it('shows where the library is kept and saves another folder for the next start', async () => {
    const user = userEvent.setup()
    chooseLibrary.mockResolvedValueOnce('D:\\Pictures\\FaceIdentify')
    setup()

    expect(await screen.findByText('C:\\Users\\me\\Documents\\FaceIdentify')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Choose another folder…' }))

    expect(await screen.findByText('D:\\Pictures\\FaceIdentify')).toBeInTheDocument()
    expect(screen.getByText(/used after you restart/)).toBeInTheDocument()
  })

  it('keeps the library as it is when the dialog is cancelled, and says when it cannot open', async () => {
    const user = userEvent.setup()
    chooseLibrary.mockResolvedValueOnce(null)
    setup()
    const choose = await screen.findByRole('button', { name: 'Choose another folder…' })

    await user.click(choose)
    expect(screen.queryByText(/used after you restart/)).toBeNull()

    chooseLibrary.mockRejectedValueOnce(new Error('no dialog'))
    await user.click(choose)
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'The file dialog could not be opened.',
    )
  })

  it('says what the models are, their licence and the exact files it will accept', async () => {
    setup()

    expect(await screen.findByText(/non-commercial research purposes only/)).toBeInTheDocument()
    expect(screen.getByText(/never downloads them and never includes them/)).toBeInTheDocument()
    expect(screen.getByText('det_10g.onnx')).toBeInTheDocument()
    expect(screen.getByText('a'.repeat(64))).toBeInTheDocument()
  })

  it('installs the models from the path the user typed and then shows them as installed', async () => {
    const user = userEvent.setup()
    let installed = false
    const { calls } = setup([
      { path: MODELS, respond: () => models(installed) },
      {
        method: 'POST',
        path: `${MODELS}/install`,
        respond: () => {
          installed = true
          return models(true)
        },
      },
    ])
    const install = await screen.findByRole('button', { name: 'Install the models' })
    expect(install).toBeDisabled() // nothing to install from yet

    await user.type(screen.getByLabelText(/downloaded zip, or the folder/), 'C:\\dl\\buffalo_l.zip')
    await user.click(install)

    expect(await screen.findByText('The face models are installed.')).toBeInTheDocument()
    expect(calls.find((c) => c.path === `${MODELS}/install`)?.body).toEqual({
      path: 'C:\\dl\\buffalo_l.zip',
    })
  })

  it('fills the path from the native dialog and tells the user when the dialog cannot open', async () => {
    const user = userEvent.setup()
    chooseModels.mockResolvedValueOnce('C:\\picked\\models')
    setup()

    await user.click(await screen.findByRole('button', { name: 'Choose the folder…' }))
    await waitFor(() =>
      expect(screen.getByLabelText(/downloaded zip, or the folder/)).toHaveValue(
        'C:\\picked\\models',
      ),
    )
    expect(chooseModels).toHaveBeenCalledWith('folder')

    chooseModels.mockResolvedValueOnce(null) // cancelled: the path stays
    await user.click(screen.getByRole('button', { name: 'Choose the zip…' }))
    expect(screen.getByLabelText(/downloaded zip, or the folder/)).toHaveValue('C:\\picked\\models')

    chooseModels.mockRejectedValueOnce(new Error('no dialog'))
    await user.click(screen.getByRole('button', { name: 'Choose the zip…' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'The file dialog could not be opened',
    )
  })

  it('shows why a file was refused', async () => {
    const user = userEvent.setup()
    setup([
      {
        method: 'POST',
        path: `${MODELS}/install`,
        ...apiError('MODEL_SOURCE_INVALID', 'w600k_r50.onnx is not the selected model'),
      },
    ])

    await user.type(await screen.findByLabelText(/downloaded zip, or the folder/), 'C:\\x')
    await user.click(screen.getByRole('button', { name: 'Install the models' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'w600k_r50.onnx is not the selected model',
    )
  })

  it('offers Assisted first, shows exactly what each choice saves and saves the one chosen', async () => {
    const user = userEvent.setup()
    const { calls } = setup([{ method: 'PUT', path: MODE, respond: modeState('AUTOMATIC') }])

    expect(await screen.findByText(/You have not chosen yet/)).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: /Assisted/ })).toBeChecked()
    expect(screen.getByText(/"match_threshold": 2/)).toBeInTheDocument()

    await user.click(screen.getByRole('radio', { name: /Automatic/ }))
    expect(screen.getByText(/"match_threshold": 0.45/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Use Automatic recognition' }))

    await waitFor(() => expect(calls.some((c) => c.method === 'PUT')).toBe(true))
    expect(calls.find((c) => c.method === 'PUT')?.body).toEqual({
      mode: 'AUTOMATIC',
      shown_version: 'buffalo-l-verified-match-v1',
    })
  })

  it('names the current choice, and reports a policy the owner made without offering to change it', async () => {
    setup([], true, 'ASSISTED')
    expect(await screen.findByText('Current choice: Assisted.')).toBeInTheDocument()
  })

  it('leaves an owner-made policy alone', async () => {
    setup([], true, 'CUSTOM')

    expect(await screen.findByText(/policy that this app did not write/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Use .* recognition/ })).toBeNull()
  })

  it('shows a refused choice', async () => {
    const user = userEvent.setup()
    setup([
      {
        method: 'PUT',
        path: MODE,
        ...apiError('POLICY_NOT_REPLACEABLE', 'A policy this app did not write is installed.', 409),
      },
    ])

    await user.click(await screen.findByRole('button', { name: 'Use Assisted recognition' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('did not write')
  })

  it('reports what the backend found, with the card line filling in after the first picture', async () => {
    setup([
      {
        path: '/readiness',
        respond: readiness({
          runtime_package: 'READY',
          processing_policy: 'UNAVAILABLE',
          execution_provider: 'DmlExecutionProvider',
          provider_fallback: 'NONE',
        }),
      },
    ])

    const found = (await screen.findByRole('heading', { name: '3. What the app found' })).closest(
      'section',
    )!
    await waitFor(() =>
      expect(within(found).getByText(/Face models: installed and registered/)).toBeInTheDocument(),
    )
    expect(within(found).getByText(/Recognition mode: not chosen yet/)).toBeInTheDocument()
    expect(within(found).getByText(/in use \(DmlExecutionProvider\)/)).toBeInTheDocument()
  })

  it('says the processor is used when the card could not be', async () => {
    setup([
      {
        path: '/readiness',
        respond: readiness({
          execution_provider: 'CPUExecutionProvider',
          provider_fallback: 'ACTIVE',
        }),
      },
    ])

    expect(await screen.findByText(/not available, so the processor is used/)).toBeInTheDocument()
  })

  it('says the card is checked later, with nothing for the user to do, before any picture', async () => {
    setup([{ path: '/readiness', respond: readiness({ execution_provider: 'NOT_STARTED' }) }])

    expect(
      await screen.findByText(/otherwise everything runs on the processor/),
    ).toBeInTheDocument()
  })
})
