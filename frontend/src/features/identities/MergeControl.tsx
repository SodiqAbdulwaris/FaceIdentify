import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useNavigate } from 'react-router'
import { ApiError } from '@/api/client'
import { keys } from '@/api/keys'
import type { IdentitySummary } from '@/api/types'
import { useBackend } from '@/app/useBackend'
import { Button } from '@/components/ui/button'
import { errorMessage } from '../library/messages'
import { usePeopleChoices } from '../source/usePeopleChoices'
import { personLabel } from './label'

/**
 * "This is the same person as ...": merge this person into another one. This person disappears and
 * every face moves to the one chosen; if both are named, the chosen one's name stays. It asks for
 * confirmation first because it cannot be undone from here.
 */
export function MergeControl({ identity }: { identity: IdentitySummary }) {
  const { endpoints } = useBackend()
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const [targetId, setTargetId] = useState('')
  const { choices, query: others } = usePeopleChoices(open, identity.id)
  const target = choices.find((choice) => choice.id === targetId)
  const mine = personLabel(identity.id, identity.person)

  const merge = useMutation({
    mutationFn: (survivor: IdentitySummary) => endpoints.mergeIdentities(identity, survivor),
    onSuccess: (survivor) => navigate(`/identities/${survivor.id}`),
    onSettled: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: keys.identities }),
        queryClient.invalidateQueries({ queryKey: keys.people }),
        queryClient.invalidateQueries({ queryKey: ['identity'] }),
        queryClient.invalidateQueries({ queryKey: ['source'] }),
      ]),
  })

  if (!open) {
    return (
      <Button
        variant="outline"
        className="self-start"
        onClick={() => {
          merge.reset()
          setOpen(true)
        }}
      >
        This is the same person as…
      </Button>
    )
  }

  const changed = merge.error instanceof ApiError && merge.error.code === 'IDENTITY_CHANGED'
  return (
    <div role="group" aria-label="Merge this person" className="flex flex-col gap-2 rounded-md border p-3">
      <label className="flex flex-col gap-1 text-sm">
        The same person as
        <select
          value={targetId}
          onChange={(event) => setTargetId(event.target.value)}
          className="rounded-md border bg-background px-2 py-1"
        >
          <option value="">Choose a person…</option>
          {choices.map((choice) => (
            <option key={choice.id} value={choice.id}>
              {personLabel(choice.id, choice.person)}
            </option>
          ))}
        </select>
      </label>
      {others.hasNextPage ? (
        <Button
          size="sm"
          variant="outline"
          className="self-start"
          disabled={others.isFetchingNextPage}
          onClick={() => void others.fetchNextPage()}
        >
          {others.isFetchingNextPage ? 'Loading…' : 'Show more people'}
        </Button>
      ) : null}
      {target ? (
        <p className="text-sm">
          {mine} will be merged into <strong>{personLabel(target.id, target.person)}</strong>: every
          face moves there and {mine} goes.
          {identity.person && target.person
            ? ` Both are named, so the name ${target.person.display_name} is kept.`
            : ''}
        </p>
      ) : null}
      <div className="flex gap-2">
        <Button
          disabled={!target || merge.isPending}
          onClick={() => target && merge.mutate(target)}
        >
          {merge.isPending ? 'Merging…' : 'Merge'}
        </Button>
        <Button variant="outline" onClick={() => setOpen(false)}>
          Cancel
        </Button>
      </div>
      {merge.isError ? (
        <p role="alert" className="text-sm text-destructive">
          {changed
            ? 'One of these people changed since you looked. The page has been refreshed; try again.'
            : `They could not be merged: ${errorMessage(merge.error)}`}
        </p>
      ) : null}
    </div>
  )
}
