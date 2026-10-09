import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { keys } from '@/api/keys'
import { useBackend } from '@/app/useBackend'
import { Button } from '@/components/ui/button'
import { errorMessage } from '../library/messages'

/**
 * Delete an image in the recycle bin for good. It asks first, in place: this removes the image,
 * its faces and their stored vectors, and cannot be undone. People you named stay.
 */
export function PermanentDelete({
  sourceId,
  name,
  onNotice,
  compact = false,
}: {
  sourceId: string
  name: string
  onNotice: (message: string | null) => void
  compact?: boolean
}) {
  const { endpoints } = useBackend()
  const queryClient = useQueryClient()
  const [asking, setAsking] = useState(false)
  const remove = useMutation({
    mutationFn: () => endpoints.deleteSourcePermanently(sourceId),
    onSuccess: (result) =>
      onNotice(
        result.status === 202
          ? 'Part of the deletion could not finish yet. It is tried again the next time the app starts.'
          : null,
      ),
    onError: (error) => onNotice(errorMessage(error)),
    onSettled: () => {
      setAsking(false)
      return Promise.all([
        queryClient.invalidateQueries({ queryKey: keys.sources }),
        queryClient.invalidateQueries({ queryKey: keys.source(sourceId) }),
        queryClient.invalidateQueries({ queryKey: keys.identities }),
        queryClient.invalidateQueries({ queryKey: ['identity'] }),
      ])
    },
  })
  const size = compact ? 'sm' : 'default'

  if (!asking) {
    return (
      <Button
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
    <div role="alertdialog" aria-label={`Delete ${name} permanently?`} className="flex flex-col gap-2">
      <p className="text-sm">
        Delete {name} for good? The image and its faces are removed and cannot be brought back. People
        you have named stay.
      </p>
      <div className="flex gap-2">
        <Button size={size} variant="destructive" disabled={remove.isPending} onClick={() => remove.mutate()}>
          Yes, delete it
        </Button>
        <Button size={size} variant="outline" disabled={remove.isPending} onClick={() => setAsking(false)}>
          Keep it
        </Button>
      </div>
    </div>
  )
}
