import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router'
import { ApiError } from '@/api/client'
import { keys } from '@/api/keys'
import type { IdentitySummary } from '@/api/types'
import { useBackend } from '@/app/useBackend'
import { Button } from '@/components/ui/button'
import { errorMessage } from '../library/messages'

/**
 * "These faces are someone else": split the chosen faces off into a new person. A face can rest on
 * evidence that other faces share; if the choice would cut one in two, nothing is done and the
 * faces involved are offered so the choice can be completed.
 */
export function SplitControl({
  identity,
  selected,
  onAdd,
  onDone,
}: {
  identity: IdentitySummary
  selected: string[]
  onAdd: (ids: string[]) => void
  onDone: () => void
}) {
  const { endpoints } = useBackend()
  const queryClient = useQueryClient()
  const navigate = useNavigate()

  const split = useMutation({
    mutationFn: () => endpoints.splitFaces(identity, selected),
    onSuccess: (created) => {
      onDone()
      navigate(`/identities/${created.id}`)
    },
    onSettled: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: keys.identities }),
        queryClient.invalidateQueries({ queryKey: keys.people }),
        queryClient.invalidateQueries({ queryKey: ['identity'] }),
        queryClient.invalidateQueries({ queryKey: ['source'] }),
      ]),
  })

  if (selected.length === 0) return null
  const conflict = split.error instanceof ApiError && split.error.code === 'SPLIT_CONFLICT'
  const involved = conflict
    ? ((split.error as ApiError).details?.occurrence_ids as string[] | undefined) ?? []
    : []

  return (
    <div role="group" aria-label="Split off" className="flex flex-col gap-2 rounded-md border p-3">
      <p className="text-sm">
        {selected.length} {selected.length === 1 ? 'face' : 'faces'} chosen.
      </p>
      <div className="flex gap-2">
        <Button disabled={split.isPending} onClick={() => split.mutate()}>
          {split.isPending ? 'Splitting…' : 'These are someone else'}
        </Button>
        <Button variant="outline" onClick={onDone}>
          Clear
        </Button>
      </div>
      {conflict ? (
        <div role="alert" className="flex flex-col gap-2 text-sm text-destructive">
          <p>
            Some faces share what they rest on with {involved.length}{' '}
            {involved.length === 1 ? 'face' : 'faces'} you did not choose, so they cannot be split
            apart. Nothing was changed.
          </p>
          <Button
            size="sm"
            variant="outline"
            className="self-start"
            onClick={() => {
              split.reset()
              onAdd(involved)
            }}
          >
            Choose {involved.length === 1 ? 'that face' : 'those faces'} too
          </Button>
        </div>
      ) : split.isError ? (
        <p role="alert" className="text-sm text-destructive">
          They could not be split off: {errorMessage(split.error)}
        </p>
      ) : null}
    </div>
  )
}
