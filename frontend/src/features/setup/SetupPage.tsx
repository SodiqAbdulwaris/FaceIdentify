import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { keys } from '@/api/keys'
import type { ModeOption } from '@/api/types'
import { useBackend } from '@/app/useBackend'
import { Button } from '@/components/ui/button'
import { chooseLibrary, chooseModels, inShell, libraryRoot } from '@/native/backend'
import { errorMessage } from '../library/messages'

const megabytes = (bytes: number) => `${(bytes / 1e6).toFixed(1)} MB`
const modeName = (mode: string) => (mode === 'ASSISTED' ? 'Assisted' : 'Automatic')

/**
 * First-run setup: the face models the user obtained (never bundled, never downloaded by the app),
 * how automatic recognition is, and what the app found. Each step can be done on its own and in any
 * order; everything else in the app works without them.
 */
export function SetupPage() {
  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-8">
      <h1 className="text-2xl font-semibold">Set up recognition</h1>
      <LibraryStep />
      <ModelsStep />
      <ModeStep />
      <CheckStep />
    </div>
  )
}

function LibraryStep() {
  const current = useQuery({ queryKey: ['library-root'], queryFn: libraryRoot })
  const [saved, setSaved] = useState<string | null>(null)
  const [failed, setFailed] = useState(false)

  async function choose() {
    setFailed(false)
    try {
      const picked = await chooseLibrary()
      if (picked !== null) setSaved(picked)
    } catch {
      setFailed(true)
    }
  }

  return (
    <section aria-labelledby="library-heading" className="flex flex-col gap-3">
      <h2 id="library-heading" className="text-lg font-medium">
        Where your library is kept
      </h2>
      <p>
        Your pictures, people and everything the app remembers live in one folder
        {current.data ? (
          <>
            : <code className="break-all">{current.data}</code>
          </>
        ) : null}
        . You can keep it as it is or choose another folder.
      </p>
      {inShell() ? (
        <div>
          <Button variant="outline" onClick={() => void choose()}>
            Choose another folder…
          </Button>
        </div>
      ) : null}
      {saved !== null ? (
        <p role="status">
          Saved: <code className="break-all">{saved}</code>. It is used after you restart
          FaceIdentify; nothing is moved for you.
        </p>
      ) : null}
      {failed ? <p role="alert">The file dialog could not be opened.</p> : null}
    </section>
  )
}

function ModelsStep() {
  const { endpoints } = useBackend()
  const queryClient = useQueryClient()
  const models = useQuery({ queryKey: keys.models, queryFn: endpoints.models })
  const [path, setPath] = useState('')
  const [dialogError, setDialogError] = useState<string | null>(null)
  const install = useMutation({
    mutationFn: () => endpoints.installModels(path.trim()),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: keys.models })
      await queryClient.invalidateQueries({ queryKey: keys.readiness })
    },
  })

  async function choose(kind: 'zip' | 'folder') {
    setDialogError(null)
    try {
      const picked = await chooseModels(kind)
      if (picked !== null) setPath(picked)
    } catch {
      setDialogError('The file dialog could not be opened. Type the path instead.')
    }
  }

  if (models.data === undefined) return <section aria-label="Face models">Loading…</section>
  const state = models.data
  return (
    <section aria-labelledby="models-heading" className="flex flex-col gap-3">
      <h2 id="models-heading" className="text-lg font-medium">
        1. Face models
      </h2>
      <p>
        FaceIdentify recognises faces with models you obtain yourself: it never downloads them and
        never includes them. They come under this licence: <em>{state.licence}</em>. They are
        published at {state.source_url} (the file <code>buffalo_l.zip</code>).
      </p>
      <p>
        The app checks each file against the size and checksum it expects before it installs it:
      </p>
      <ul className="list-disc pl-6 text-sm">
        {state.files.map((file) => (
          <li key={file.name}>
            <code>{file.name}</code>, {megabytes(file.size_bytes)}, SHA-256{' '}
            <code className="break-all">{file.sha256}</code>
          </li>
        ))}
      </ul>
      {state.installed ? (
        <p role="status" className="font-medium">
          The face models are installed.
        </p>
      ) : (
        <div className="flex flex-col gap-2">
          <label className="flex flex-col gap-1">
            <span>The downloaded zip, or the folder you unpacked it into</span>
            <input
              className="rounded-md border px-2 py-1"
              value={path}
              onChange={(event) => setPath(event.target.value)}
            />
          </label>
          <div className="flex flex-wrap gap-2">
            {inShell() ? (
              <>
                <Button variant="outline" onClick={() => void choose('zip')}>
                  Choose the zip…
                </Button>
                <Button variant="outline" onClick={() => void choose('folder')}>
                  Choose the folder…
                </Button>
              </>
            ) : null}
            <Button
              disabled={path.trim() === '' || install.isPending}
              onClick={() => install.mutate()}
            >
              {install.isPending ? 'Installing…' : 'Install the models'}
            </Button>
          </div>
          {dialogError ? <p role="alert">{dialogError}</p> : null}
          {install.isError ? <p role="alert">{errorMessage(install.error)}</p> : null}
        </div>
      )}
    </section>
  )
}

function ModeStep() {
  const { endpoints } = useBackend()
  const queryClient = useQueryClient()
  const mode = useQuery({ queryKey: keys.recognitionMode, queryFn: endpoints.recognitionMode })
  const [picked, setPicked] = useState<ModeOption['mode']>('ASSISTED')
  const save = useMutation({
    mutationFn: (option: ModeOption) =>
      endpoints.chooseRecognitionMode(option.mode, String(option.policy.version)),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: keys.recognitionMode })
      await queryClient.invalidateQueries({ queryKey: keys.readiness })
    },
  })

  if (mode.data === undefined) return <section aria-label="Recognition mode">Loading…</section>
  const { options } = mode.data
  const chosen = options.find((option) => option.mode === picked) ?? options[0]
  return (
    <section aria-labelledby="mode-heading" className="flex flex-col gap-3">
      <h2 id="mode-heading" className="text-lg font-medium">
        2. How recognition works
      </h2>
      {mode.data.mode === 'CUSTOM' ? (
        <p role="status">
          A recognition policy that this app did not write is installed. It is used as it is and the
          app will not change it.
        </p>
      ) : (
        <>
          <p role="status">
            {mode.data.mode === 'NONE'
              ? 'You have not chosen yet: until you do, faces are not processed.'
              : `Current choice: ${modeName(mode.data.mode)}.`}
          </p>
          <fieldset className="flex flex-col gap-2">
            <legend className="sr-only">Recognition mode</legend>
            {options.map((option) => (
              <label key={option.mode} className="flex items-start gap-2">
                <input
                  type="radio"
                  name="mode"
                  checked={picked === option.mode}
                  onChange={() => setPicked(option.mode)}
                />
                <span>
                  <strong>{modeName(option.mode)}</strong>: {option.description}
                </span>
              </label>
            ))}
          </fieldset>
          <details>
            <summary>Exactly what will be saved</summary>
            <pre className="overflow-auto text-xs">{JSON.stringify(chosen.policy, null, 2)}</pre>
          </details>
          <div>
            <Button disabled={save.isPending} onClick={() => save.mutate(chosen)}>
              Use {modeName(chosen.mode)} recognition
            </Button>
          </div>
          {save.isError ? <p role="alert">{errorMessage(save.error)}</p> : null}
        </>
      )}
    </section>
  )
}

const CHECKS: { key: string; label: string; ready: string; waiting: string }[] = [
  {
    key: 'runtime_package',
    label: 'Face models',
    ready: 'installed and registered',
    waiting: 'not installed yet (step 1)',
  },
  {
    key: 'processing_policy',
    label: 'Recognition mode',
    ready: 'chosen',
    waiting: 'not chosen yet (step 2)',
  },
]

function CheckStep() {
  const { endpoints } = useBackend()
  const readiness = useQuery({ queryKey: keys.readiness, queryFn: endpoints.readiness })
  const capabilities = readiness.data?.capabilities ?? {}
  const provider = capabilities.execution_provider
  const fellBack = capabilities.provider_fallback === 'ACTIVE'
  let card: string
  if (provider === undefined || provider === 'NOT_STARTED') {
    card =
      'checked the first time a picture is processed. A supported card is used, otherwise ' +
      'everything runs on the processor, with nothing for you to do.'
  } else if (fellBack) {
    card = `not available, so the processor is used (${provider}).`
  } else {
    card = `in use (${provider}).`
  }
  return (
    <section aria-labelledby="check-heading" className="flex flex-col gap-2">
      <h2 id="check-heading" className="text-lg font-medium">
        3. What the app found
      </h2>
      <ul className="list-disc pl-6">
        {CHECKS.map((check) => (
          <li key={check.key}>
            {check.label}: {capabilities[check.key] === 'READY' ? check.ready : check.waiting}
          </li>
        ))}
        <li>Graphics card: {card}</li>
      </ul>
    </section>
  )
}
