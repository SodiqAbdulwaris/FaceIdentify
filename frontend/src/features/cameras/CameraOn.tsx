import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router'
import { keys } from '@/api/keys'
import { useBackend } from '@/app/useBackend'
import { isOn } from './session'

const CHECK_MS = 5000

/**
 * "Camera on", on every screen while a camera session runs (M7 plan C4): the visible counterpart of
 * cameras being off by default. Events refresh it at once; the slow check is a backstop.
 */
export function CameraOn() {
  const { endpoints } = useBackend()
  const cameras = useQuery({
    queryKey: keys.cameras,
    queryFn: endpoints.listCameras,
    refetchInterval: CHECK_MS,
    retry: false,
  })
  const on = (cameras.data ?? []).filter((camera) => isOn(camera.session))
  if (on.length === 0) return null
  return (
    <Link
      to="/cameras"
      role="status"
      aria-label="Camera on"
      className="flex items-center gap-1.5 rounded-full bg-destructive/10 px-2.5 py-0.5 text-xs font-medium text-destructive"
    >
      <span aria-hidden="true" className="size-2 rounded-full bg-destructive" />
      Camera on: {on.map((camera) => camera.display_name).join(', ')}
    </Link>
  )
}
