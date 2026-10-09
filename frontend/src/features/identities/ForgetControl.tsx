import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useEffect, useId, useRef, useState } from 'react'
import { useNavigate } from 'react-router'
import { keys } from '@/api/keys'
import type { IdentitySummary } from '@/api/types'
import { useBackend } from '@/app/useBackend'
import { Button } from '@/components/ui/button'
import { errorMessage } from '../library/messages'

type Scope = 'face' | 'person'

const OWED =
  'Part of the cleanup could not finish yet. It is tried again the next time the app starts.'

/**
 * Forget what the app remembers of how a person looks. It asks first, in place: the stored face
 * "fingerprints" are erased and cannot be brought back, the images stay, and a named person keeps
 * their name. For a named person there are two scopes: this one remembered face, or every face
 * remembered for them.
 *
 * Keyboard: asking moves focus to "Keep it" (the safe answer); Escape or "Keep it" gives focus back
 * to the button that opened the question.
 */
export function ForgetControl({ identity }: { identity: IdentitySummary }) {
  const { endpoints } = useBackend()
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [asking, setAsking] = useState<Scope | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const opener = useRef<HTMLElement | null>(null)
  const keep = useRef<HTMLButtonElement>(null)
  const cancelled = useRef(false)
  const warning = useId()
  const person = identity.person ?? null

  const forget = useMutation({
    mutationFn: (scope: Scope) =>
      scope === 'person' && person
        ? endpoints.forgetPerson(person.id)
        : endpoints.forgetIdentity(identity),
    onSuccess: async (result) => {
      // Nothing of the person may stay on screen or in memory: drop what was fetched for any
      // identity (a whole-person forget reaches several) and every cached list of faces.
      const faces = (query: { queryKey: readonly unknown[] }) =>
        query.queryKey[0] === 'identity' ||
        query.queryKey[0] === 'identities' ||
        query.queryKey[0] === 'search' ||
        (query.queryKey[0] === 'source' && query.queryKey[2] === 'occurrences')
      await queryClient.cancelQueries({ predicate: faces })
      queryClient.removeQueries({ predicate: faces })
      void navigate('/identities', { state: { notice: result.status === 202 ? OWED : null } })
    },
    onError: (error) => setNotice(errorMessage(error)),
    onSettled: () => {
      setAsking(null)
      return Promise.all([
        queryClient.invalidateQueries({ queryKey: keys.identities }),
        queryClient.invalidateQueries({ queryKey: keys.people }),
        queryClient.invalidateQueries({ queryKey: ['source'] }),
      ])
    },
  })

  useEffect(() => {
    if (asking) keep.current?.focus()
    else if (cancelled.current) {
      cancelled.current = false
      opener.current?.focus()
    }
  }, [asking])

  const cancel = () => {
    cancelled.current = true
    setAsking(null)
  }

  const name = person?.display_name ?? 'this person'
  if (!asking) {
    return (
      <div className="flex flex-col gap-2">
        {notice ? (
          <p role="status" aria-label="Forget notice" className="text-sm text-destructive">
            {notice}
          </p>
        ) : null}
        <div className="flex flex-wrap gap-2">
          <Button
            variant="ghost"
            onClick={(event) => {
              opener.current = event.currentTarget
              setAsking('face')
            }}
            aria-label={`Forget how ${name} looks`}
          >
            Forget how {name} looks
          </Button>
          {person ? (
            <Button
              variant="ghost"
              onClick={(event) => {
                opener.current = event.currentTarget
                setAsking('person')
              }}
              aria-label={`Forget every face of ${person.display_name}`}
            >
              Forget every face of {person.display_name}
            </Button>
          ) : null}
        </div>
      </div>
    )
  }
  return (
    <div
      role="alertdialog"
      aria-label={`Forget ${name}?`}
      aria-describedby={warning}
      className="flex flex-col gap-2"
      onKeyDown={(event) => {
        if (event.key === 'Escape' && !forget.isPending) cancel()
      }}
    >
      <p id={warning} className="text-sm">
        {asking === 'person'
          ? `Forget every face the app remembers of ${name}?`
          : `Forget how ${name} looks?`}{' '}
        The stored faces are erased and cannot be brought back. Your images stay
        {person ? `, and ${person.display_name} stays in your people with their name` : ''}.
        {asking === 'face' && person
          ? ` Other faces remembered for ${person.display_name} are kept, so the app can still recognise them from those.`
          : ` If ${person ? 'they appear' : 'this person appears'} in an image later, the app treats them as someone new.`}
      </p>
      <div className="flex gap-2">
        <Button
          variant="destructive"
          disabled={forget.isPending}
          onClick={() => forget.mutate(asking)}
        >
          Yes, forget
        </Button>
        <Button ref={keep} variant="outline" disabled={forget.isPending} onClick={cancel}>
          Keep it
        </Button>
      </div>
    </div>
  )
}
