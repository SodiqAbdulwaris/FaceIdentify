import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router'
import { keys } from '@/api/keys'
import type { SourceDetail } from '@/api/types'
import { useBackend } from '@/app/useBackend'
import { Button } from '@/components/ui/button'
import { errorMessage } from '../library/messages'
import { PermanentDelete } from './PermanentDelete'

/**
 * Move an image to the recycle bin and back. Recycling only hides it from the library: its faces
 * stay in the people it was recognised in (marked as coming from a recycled image), and restoring
 * brings it straight back without processing it again.
 */
export function RecycleControl({
  source,
  onNotice,
}: {
  source: Pick<SourceDetail, 'id' | 'display_name' | 'state'>
  onNotice: (message: string | null) => void
}) {
  const { endpoints } = useBackend()
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const recycled = source.state === 'RECYCLED'
  const move = useMutation({
    mutationFn: async () => {
      if (recycled) await endpoints.restoreSource(source.id)
      else await endpoints.recycleSource(source.id)
    },
    onSuccess: () => onNotice(null),
    onError: (error) => onNotice(errorMessage(error)),
    onSettled: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: keys.sources }),
        queryClient.invalidateQueries({ queryKey: keys.source(source.id) }),
        queryClient.invalidateQueries({ queryKey: ['identity'] }),
      ]),
  })

  return (
    <div className="flex flex-col gap-2">
      {recycled ? (
        <p role="note" className="rounded-md border px-3 py-2 text-sm">
          This image is in the recycle bin. Its faces stay in your memory, marked as recycled.
        </p>
      ) : null}
      <Button variant="outline" disabled={move.isPending} onClick={() => move.mutate()}>
        {recycled ? 'Restore from the recycle bin' : 'Move to the recycle bin'}
      </Button>
      {recycled ? (
        <PermanentDelete
          sourceId={source.id}
          name={source.display_name}
          onNotice={onNotice}
          onGone={() => void navigate('/library')}
        />
      ) : null}
    </div>
  )
}
