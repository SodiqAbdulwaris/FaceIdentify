import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { ApiError } from '@/api/client'
import { keys } from '@/api/keys'
import { useBackend } from '@/app/useBackend'
import { Button } from '@/components/ui/button'
import { personLabel } from '../identities/label'
import { errorMessage } from '../library/messages'
import type { Face } from './faces'
import { usePeopleChoices } from './usePeopleChoices'

/** How the face got to this person, said plainly: an automatic match is not a confirmed one. */
function Placement({ face }: { face: Face }) {
  const { placement, match_similarity: similarity, match_margin: margin } = face.occurrence
  if (placement === 'AUTOMATIC_MATCH') {
    return (
      <p className="text-sm text-muted-foreground">
        Matched automatically
        {similarity === null
          ? ''
          : ` (similarity score ${similarity.toFixed(2)}${margin === null ? '' : `, lead ${margin.toFixed(2)}`})`}
        . Check it, and move it if it is wrong.
      </p>
    )
  }
  if (placement === 'AUTOMATIC_NEW') {
    return (
      <p className="text-sm text-muted-foreground">
        Created automatically as a new identity. Check it, and move it if it is wrong.
      </p>
    )
  }
  return placement === 'USER' ? (
    <p className="text-sm text-muted-foreground">Checked by you.</p>
  ) : null
}

/**
 * Check one face: say it is right, or say it is someone else (a new person, or a person already
 * in the library). The backend keeps every correction as history and refuses one made from an out
 * of date view, so a face that has moved since this page loaded is reported, not overwritten.
 */
export function FaceCorrection({ face }: { face: Face }) {
  const { endpoints } = useBackend()
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const [target, setTarget] = useState('')
  const { occurrence, label } = face

  const { choices, query: others } = usePeopleChoices(open, occurrence.identity_id)

  const change = useMutation({
    mutationFn: (action: 'confirm' | 'new' | 'existing') =>
      action === 'confirm'
        ? endpoints.confirmFace(occurrence.id, occurrence.identity_id)
        : endpoints.moveFace(
            occurrence.id,
            occurrence.identity_id,
            action === 'new' ? null : target,
          ),
    onSuccess: () => setOpen(false),
    // The face may now be under someone else, and a name or a count changed: refresh it all.
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
      <div className="flex flex-col items-start gap-1">
        <Placement face={face} />
        <Button
          variant="outline"
          size="sm"
          onClick={() => {
            change.reset()
            setOpen(true)
          }}
        >
          Check this face
        </Button>
      </div>
    )
  }

  const moved = change.error instanceof ApiError && change.error.code === 'OCCURRENCE_MOVED'
  return (
    <div role="group" aria-label={`Check ${label}`} className="flex flex-col gap-2 rounded-md border p-3">
      <p className="text-sm">
        This face was {occurrence.placement === 'AUTOMATIC_MATCH' ? 'matched automatically to' : 'recognised as'}{' '}
        <strong>{label}</strong>.
      </p>
      <div className="flex flex-wrap gap-2">
        <Button size="sm" disabled={change.isPending} onClick={() => change.mutate('confirm')}>
          Yes, this is {label}
        </Button>
        <Button
          size="sm"
          variant="outline"
          disabled={change.isPending}
          onClick={() => change.mutate('new')}
        >
          This is someone new
        </Button>
        <Button size="sm" variant="outline" onClick={() => setOpen(false)}>
          Close
        </Button>
      </div>
      {choices.length > 0 ? (
        <div className="flex flex-wrap items-end gap-2">
          <label className="flex flex-col gap-1 text-sm">
            This is someone already in the library
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
            disabled={change.isPending || !target}
            onClick={() => change.mutate('existing')}
          >
            Move this face
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
      {change.isError ? (
        <p role="alert" className="text-sm text-destructive">
          {moved
            ? 'This face now belongs to someone else. The page has been refreshed; check it again.'
            : `The correction could not be saved: ${errorMessage(change.error)}`}
        </p>
      ) : null}
    </div>
  )
}
