import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { keys } from '@/api/keys'
import type { UnresolvedFace } from '@/api/types'
import { useBackend } from '@/app/useBackend'
import { Button } from '@/components/ui/button'
import { FaceCrop } from '../FaceCrop'
import { personLabel } from '../identities/label'
import { errorMessage } from '../library/messages'
import { usePeopleChoices } from './usePeopleChoices'

/**
 * Faces the system found but would not place: it was not sure enough to say who they are, and it
 * does not guess. Each is shown with the people it resembled most; a person decides: one of those,
 * someone new, or anyone in the library.
 */
export function UnresolvedFaces({ sourceId }: { sourceId: string }) {
  const { endpoints } = useBackend()
  const faces = useQuery({
    queryKey: keys.sourceUnresolved(sourceId),
    queryFn: () => endpoints.unresolvedFaces(sourceId),
  })
  const items = faces.data?.items ?? []
  if (faces.isError) {
    return (
      <p role="alert" className="text-sm text-destructive">
        The faces still to place could not be loaded: {errorMessage(faces.error)}
      </p>
    )
  }
  if (items.length === 0) return null
  return (
    <div>
      <h2 className="mb-1 font-medium">Faces to place</h2>
      <p className="mb-2 text-sm text-muted-foreground">
        These faces were not matched to anyone with enough confidence. Say who they are.
      </p>
      <ul className="flex flex-col gap-3">
        {items.map((face) => (
          <li key={face.representation_id}>
            <Unresolved sourceId={sourceId} face={face} />
          </li>
        ))}
      </ul>
    </div>
  )
}

function Unresolved({ sourceId, face }: { sourceId: string; face: UnresolvedFace }) {
  const { endpoints } = useBackend()
  const queryClient = useQueryClient()
  const [target, setTarget] = useState('')
  const [picking, setPicking] = useState(false)
  const { choices, query: others } = usePeopleChoices(picking)

  const resolve = useMutation({
    mutationFn: (identityId: string | null) =>
      endpoints.resolveFace(face.representation_id, identityId),
    onSettled: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: keys.sourceUnresolved(sourceId) }),
        queryClient.invalidateQueries({ queryKey: keys.identities }),
        queryClient.invalidateQueries({ queryKey: ['identity'] }),
        queryClient.invalidateQueries({ queryKey: ['source'] }),
      ]),
  })

  return (
    <div className="flex flex-col gap-2 rounded-md border p-3">
      <div className="flex items-center gap-3">
        <FaceCrop sourceId={sourceId} box={face.bounding_box} label="A face to place" />
        <div className="flex flex-col gap-1">
          {face.likely.map((likely) => {
            const label = personLabel(likely.identity_id, likely.person)
            return (
              <Button
                key={likely.identity_id}
                size="sm"
                variant="outline"
                disabled={resolve.isPending}
                onClick={() => resolve.mutate(likely.identity_id)}
              >
                This is {label} ({Math.round(likely.similarity * 100)}% alike)
              </Button>
            )
          })}
          <Button
            size="sm"
            variant="outline"
            disabled={resolve.isPending}
            onClick={() => resolve.mutate(null)}
          >
            This is someone new
          </Button>
          {picking ? null : (
            <Button size="sm" variant="outline" onClick={() => setPicking(true)}>
              Someone else in the library…
            </Button>
          )}
        </div>
      </div>
      {picking && choices.length > 0 ? (
        <div className="flex flex-wrap items-end gap-2">
          <label className="flex flex-col gap-1 text-sm">
            Choose a person
            <select
              value={target}
              onChange={(event) => setTarget(event.target.value)}
              className="rounded-md border bg-background px-2 py-1"
            >
              <option value="">Choose a person…</option>
              {choices.map((identity) => (
                <option key={identity.id} value={identity.id}>
                  {personLabel(identity.id, identity.person)}
                </option>
              ))}
            </select>
          </label>
          <Button
            size="sm"
            variant="outline"
            disabled={resolve.isPending || !target}
            onClick={() => resolve.mutate(target)}
          >
            Place this face
          </Button>
          {others.hasNextPage ? (
            <Button
              size="sm"
              variant="outline"
              disabled={others.isFetchingNextPage}
              onClick={() => void others.fetchNextPage()}
            >
              {others.isFetchingNextPage ? 'Loading…' : 'Show more people'}
            </Button>
          ) : null}
        </div>
      ) : null}
      {resolve.isError ? (
        <p role="alert" className="text-sm text-destructive">
          The face could not be placed: {errorMessage(resolve.error)}
        </p>
      ) : null}
    </div>
  )
}
