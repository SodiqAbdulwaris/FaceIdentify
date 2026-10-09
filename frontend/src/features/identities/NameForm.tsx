import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { ApiError } from '@/api/client'
import { keys } from '@/api/keys'
import type { PersonReference } from '@/api/types'
import { useBackend } from '@/app/useBackend'
import { Button } from '@/components/ui/button'
import { errorMessage } from '../library/messages'

/**
 * Name an unnamed person, or rename a named one. Naming creates the person and links them in one
 * step on the backend; renaming carries the revision that was shown, so a change made elsewhere is
 * reported rather than overwritten.
 */
export function NameForm({
  identityId,
  person,
}: {
  identityId: string
  person: PersonReference | null
}) {
  const { endpoints } = useBackend()
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [name, setName] = useState('')

  const save = useMutation({
    mutationFn: (displayName: string) =>
      person
        ? endpoints.renamePerson(person.id, displayName, person.revision)
        : endpoints.nameIdentity(identityId, displayName),
    onSuccess: () => setEditing(false),
    // A name appears on every screen that shows this person, so refresh them all, win or lose.
    onSettled: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: keys.identity(identityId) }),
        queryClient.invalidateQueries({ queryKey: keys.identities }),
        queryClient.invalidateQueries({ queryKey: keys.people }),
        queryClient.invalidateQueries({ queryKey: ['source'] }),
      ]),
  })

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (name.trim()) save.mutate(name.trim())
  }

  if (!editing) {
    return (
      <Button
        variant="outline"
        className="self-start"
        onClick={() => {
          save.reset()
          setName(person?.display_name ?? '')
          setEditing(true)
        }}
      >
        {person ? 'Rename' : 'Name this person'}
      </Button>
    )
  }

  const conflict = save.error instanceof ApiError && save.error.code === 'PERSON_REVISION_CONFLICT'
  return (
    <form onSubmit={submit} className="flex flex-col gap-2">
      <label className="flex flex-col gap-1 text-sm font-medium">
        {person ? 'New name' : 'Name'}
        <input
          autoFocus
          value={name}
          maxLength={200}
          onChange={(event) => setName(event.target.value)}
          className="rounded-md border bg-background px-3 py-2 text-base font-normal"
        />
      </label>
      <div className="flex gap-2">
        <Button type="submit" disabled={save.isPending || !name.trim()}>
          {save.isPending ? 'Saving…' : 'Save name'}
        </Button>
        <Button type="button" variant="outline" onClick={() => setEditing(false)}>
          Cancel
        </Button>
      </div>
      {save.isError ? (
        <p role="alert" className="text-sm text-destructive">
          {conflict
            ? 'This name was changed somewhere else. The latest name is now shown; try again.'
            : `The name could not be saved: ${errorMessage(save.error)}`}
        </p>
      ) : null}
    </form>
  )
}
