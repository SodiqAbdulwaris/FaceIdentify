import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router'
import { keys } from '@/api/keys'
import type { CameraSummary, CaptureDevice } from '@/api/types'
import { useBackend } from '@/app/useBackend'
import { Button } from '@/components/ui/button'
import { errorMessage } from '../library/messages'
import { useObjectUrl } from '../useSourceImage'
import { ConfirmButton } from './ConfirmButton'
import { isOn, sessionLabel } from './session'

const POLL_MS = 1000

/**
 * The Cameras screen (M7 step 5): add a camera this computer offers, start and stop its session, see
 * what it sees while it runs (the newest frame with faces outlined, held in memory only), and go
 * to its history. Nothing starts on its own: a session runs only after Start.
 */
export function CamerasPage() {
  const { endpoints } = useBackend()
  const cameras = useQuery({
    queryKey: keys.cameras,
    queryFn: endpoints.listCameras,
    // while a session runs its counts change every moment; events say when one starts or ends
    refetchInterval: (query) => (query.state.data?.some((c) => isOn(c.session)) ? POLL_MS : false),
  })
  const [notice, setNotice] = useState<string | null>(null)

  return (
    <section className="flex flex-col gap-4">
      <h1 className="text-xl font-semibold">Cameras</h1>
      <p className="text-sm text-muted-foreground">
        A camera records who it sees and keeps up to three face pictures of each visit. It never
        records video, and it starts only when you start it.
      </p>
      {notice ? (
        <p
          role="status"
          aria-label="Cameras notice"
          className="rounded-md border px-3 py-2 text-sm"
        >
          {notice}
        </p>
      ) : null}
      {cameras.isError ? (
        <p role="alert" className="text-destructive">
          Cameras could not be loaded: {errorMessage(cameras.error)}
        </p>
      ) : null}
      {cameras.isSuccess && cameras.data.length === 0 ? (
        <p className="text-muted-foreground">No camera yet. Add one below.</p>
      ) : null}
      <ul className="flex flex-col gap-3">
        {(cameras.data ?? []).map((camera) => (
          <li key={camera.id}>
            <CameraCard camera={camera} onNotice={setNotice} />
          </li>
        ))}
      </ul>
      <AddCamera onNotice={setNotice} />
    </section>
  )
}

function CameraCard({
  camera,
  onNotice,
}: {
  camera: CameraSummary
  onNotice: (message: string | null) => void
}) {
  const { endpoints } = useBackend()
  const queryClient = useQueryClient()
  const on = isOn(camera.session)
  const refresh = () => queryClient.invalidateQueries({ queryKey: keys.cameras })
  const toggle = useMutation({
    mutationFn: () => (on ? endpoints.stopCamera(camera.id) : endpoints.startCamera(camera.id)),
    onSuccess: () => onNotice(null),
    onError: (error) => onNotice(errorMessage(error)),
    onSettled: refresh,
  })
  const remove = useMutation({
    mutationFn: (withHistory: boolean) => endpoints.removeCamera(camera.id, withHistory),
    onSuccess: (_result, withHistory) =>
      onNotice(
        withHistory
          ? `${camera.display_name} and everything it recorded were deleted.`
          : `${camera.display_name} was removed. What it recorded is still in the library.`,
      ),
    onError: (error) => onNotice(errorMessage(error)),
    onSettled: refresh,
  })

  return (
    <article
      aria-label={camera.display_name}
      className="flex flex-col gap-3 rounded-lg border bg-card p-4"
    >
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="font-medium">{camera.display_name}</h2>
        <span className="text-sm text-muted-foreground">{camera.device_name}</span>
        <span
          role="status"
          aria-label={`${camera.display_name} status`}
          className={`text-sm ${camera.session.state === 'FAILED' ? 'text-destructive' : ''}`}
        >
          {sessionLabel(camera.session)}
        </span>
        <div className="ml-auto flex flex-wrap gap-2">
          <Button size="sm" disabled={toggle.isPending} onClick={() => toggle.mutate()}>
            {on ? 'Stop' : 'Start'}
          </Button>
          <Link
            to={`/cameras/${camera.id}`}
            className="inline-flex h-7 items-center rounded-md border px-2.5 text-[0.8rem]"
          >
            History
          </Link>
        </div>
      </div>
      {on ? <Preview cameraId={camera.id} name={camera.display_name} /> : null}
      {on ? null : (
        <div className="flex flex-wrap gap-2">
          <ConfirmButton
            label="Remove"
            question={`Remove ${camera.display_name}? What it recorded stays in the library.`}
            confirm="Remove"
            disabled={remove.isPending}
            onConfirm={() => remove.mutate(false)}
          />
          <ConfirmButton
            label="Remove with its history"
            question={`Remove ${camera.display_name} and delete everything it recorded for good? This cannot be undone.`}
            confirm="Delete for good"
            disabled={remove.isPending}
            onConfirm={() => remove.mutate(true)}
          />
        </div>
      )}
    </article>
  )
}

/** The newest frame, refreshed while the session runs. It is never saved. */
function Preview({ cameraId, name }: { cameraId: string; name: string }) {
  const { endpoints } = useBackend()
  const picture = useQuery({
    queryKey: keys.cameraPreview(cameraId),
    queryFn: () => endpoints.cameraPreview(cameraId),
    refetchInterval: POLL_MS,
    retry: false,
    gcTime: 0,
  })
  const url = useObjectUrl(picture.data)
  return url ? (
    <img src={url} alt={`What ${name} sees now`} className="max-w-lg rounded-md border" />
  ) : (
    <p className="text-sm text-muted-foreground">Waiting for a picture…</p>
  )
}

function AddCamera({ onNotice }: { onNotice: (message: string | null) => void }) {
  const { endpoints } = useBackend()
  const queryClient = useQueryClient()
  const devices = useQuery({ queryKey: keys.cameraDevices, queryFn: endpoints.cameraDevices })
  const [chosen, setChosen] = useState('')
  const [name, setName] = useState('')
  const add = useMutation({
    mutationFn: (device: CaptureDevice) => endpoints.addCamera(name.trim() || device.name, device),
    onSuccess: () => {
      setName('')
      setChosen('')
      onNotice(null)
    },
    onError: (error) => onNotice(errorMessage(error)),
    onSettled: () => queryClient.invalidateQueries({ queryKey: keys.cameras }),
  })
  const list = devices.data ?? []
  const device = list.find((d) => (d.path ?? d.name) === chosen)

  return (
    <form
      aria-label="Add a camera"
      className="flex flex-wrap items-end gap-3 rounded-lg border border-dashed p-4"
      onSubmit={(event) => {
        event.preventDefault()
        if (device) add.mutate(device)
      }}
    >
      <label className="flex flex-col gap-1 text-sm">
        Camera
        <select
          className="h-8 rounded-md border bg-background px-2"
          value={chosen}
          onChange={(event) => setChosen(event.target.value)}
        >
          <option value="">
            {devices.isPending
              ? 'Looking for cameras…'
              : list.length
                ? 'Choose a camera'
                : 'No camera found'}
          </option>
          {list.map((d) => (
            <option key={d.path ?? d.name} value={d.path ?? d.name}>
              {d.name}
            </option>
          ))}
        </select>
      </label>
      <label className="flex flex-col gap-1 text-sm">
        Name
        <input
          className="h-8 rounded-md border bg-background px-2"
          value={name}
          maxLength={200}
          placeholder="Front door"
          onChange={(event) => setName(event.target.value)}
        />
      </label>
      <Button type="submit" size="sm" disabled={!device || add.isPending}>
        Add camera
      </Button>
      {devices.isError ? (
        <p role="alert" className="w-full text-sm text-destructive">
          Cameras could not be listed: {errorMessage(devices.error)}
        </p>
      ) : null}
    </form>
  )
}
