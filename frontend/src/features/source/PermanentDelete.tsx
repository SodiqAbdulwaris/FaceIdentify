import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useEffect, useId, useRef, useState } from 'react'
import { keys } from '@/api/keys'
import { useBackend } from '@/app/useBackend'
import { Button } from '@/components/ui/button'
import { errorMessage } from '../library/messages'

/**
 * Delete an image in the recycle bin for good. It asks first, in place: this removes the image,
 * its faces and their stored vectors, and cannot be undone. People you named stay.
 *
 * Keyboard: asking moves focus to "Keep it" (the safe answer), Escape or "Keep it" gives focus back
 * to the button that opened the question.
 */
export function PermanentDelete({
  sourceId,
  name,
  onNotice,
  compact = false,
  onGone,
}: {
  sourceId: string
  name: string
  onNotice: (message: string | null) => void
  compact?: boolean
  /** The image is gone (or going): leave any screen that still shows it. */
  onGone?: (notice: string | null) => void
}) {
  const { endpoints } = useBackend()
  const queryClient = useQueryClient()
  const [asking, setAsking] = useState(false)
  const trigger = useRef<HTMLButtonElement>(null)
  const keep = useRef<HTMLButtonElement>(null)
  const cancelled = useRef(false)
  const warning = useId()
  const remove = useMutation({
    mutationFn: () => endpoints.deleteSourcePermanently(sourceId),
    onSuccess: async (result) => {
      // Nothing of the image may stay on screen: drop what was fetched for it (its bytes included).
      await queryClient.cancelQueries({ queryKey: keys.source(sourceId) })
      queryClient.removeQueries({ queryKey: keys.source(sourceId) })
      const notice =
        result.status === 202
          ? 'Part of the deletion could not finish yet. It is tried again the next time the app starts.'
          : null
      onNotice(notice)
      onGone?.(notice) // (the screen that showed it may be about to go, so it is told too)
    },
    onError: (error) => {
      cancelled.current = true // the question closes: focus goes back to its button
      onNotice(errorMessage(error))
    },
    onSettled: () => {
      setAsking(false)
      return Promise.all([
        queryClient.invalidateQueries({ queryKey: keys.sources }),
        queryClient.invalidateQueries({ queryKey: keys.identities }),
        queryClient.invalidateQueries({ queryKey: keys.people }),
        queryClient.invalidateQueries({ queryKey: ['identity'] }),
        queryClient.invalidateQueries({ queryKey: keys.runs }),
        queryClient.invalidateQueries({ queryKey: ['run'] }),
      ])
    },
  })
  const size = compact ? 'sm' : 'default'

  useEffect(() => {
    if (asking) keep.current?.focus()
    else if (cancelled.current) {
      cancelled.current = false
      trigger.current?.focus()
    }
  }, [asking])

  const cancel = () => {
    cancelled.current = true
    setAsking(false)
  }

  if (!asking) {
    return (
      <Button
        ref={trigger}
        size={size}
        variant="ghost"
        onClick={() => setAsking(true)}
        aria-label={`Delete ${name} permanently`}
      >
        Delete permanently
      </Button>
    )
  }
  return (
    <div
      role="alertdialog"
      aria-label={`Delete ${name} permanently?`}
      aria-describedby={warning}
      className="flex flex-col gap-2"
      onKeyDown={(event) => {
        if (event.key === 'Escape' && !remove.isPending) cancel()
      }}
    >
      <p id={warning} className="text-sm">
        Delete {name} for good? The image and its faces are removed and cannot be brought back. People
        you have named stay.
      </p>
      <div className="flex gap-2">
        <Button
          size={size}
          variant="destructive"
          disabled={remove.isPending}
          onClick={() => remove.mutate()}
        >
          Yes, delete it
        </Button>
        <Button ref={keep} size={size} variant="outline" disabled={remove.isPending} onClick={cancel}>
          Keep it
        </Button>
      </div>
    </div>
  )
}
