import { useMutation, useQueryClient } from '@tanstack/react-query'
import { keys } from '@/api/keys'
import type { SourceDetail } from '@/api/types'
import { useBackend } from '@/app/useBackend'
import { Button } from '@/components/ui/button'
import { choosePicture, inShell } from '@/native/backend'
import { errorMessage } from '../library/messages'
import { missingReason } from './missing'

/**
 * Bring a missing original back (issue #179): "Recheck file" looks again where it was, and, for an
 * image kept where the user keeps it, "Locate original" points it at the file they find. Only the
 * very same file is accepted; anything else leaves the image missing and says why.
 */
export function MissingOriginal({
  source,
  onNotice,
}: {
  source: Pick<SourceDetail, 'id' | 'storage_mode' | 'availability_reason'>
  onNotice: (message: string | null) => void
}) {
  const { endpoints } = useBackend()
  const queryClient = useQueryClient()

  const settle = (detail: SourceDetail) => {
    queryClient.setQueryData(keys.source(source.id), detail)
    void queryClient.invalidateQueries({ queryKey: keys.sources })
    onNotice(
      detail.availability === 'AVAILABLE'
        ? 'The file is back.'
        : `Still missing. ${missingReason(detail.availability_reason)}`,
    )
  }
  const recheck = useMutation({
    mutationFn: () => endpoints.recheckSource(source.id),
    onSuccess: settle,
    onError: (error) => onNotice(errorMessage(error)),
  })
  const locate = useMutation({
    mutationFn: async (): Promise<SourceDetail | null> => {
      const path = await choosePicture()
      return path === null ? null : endpoints.relinkSource(source.id, path)
    },
    onSuccess: (detail) => (detail === null ? undefined : settle(detail)),
    onError: (error) => onNotice(errorMessage(error)),
  })
  const busy = recheck.isPending || locate.isPending

  return (
    <div className="flex flex-wrap gap-2">
      <Button variant="outline" disabled={busy} onClick={() => recheck.mutate()}>
        {recheck.isPending ? 'Checking…' : 'Recheck file'}
      </Button>
      {source.storage_mode === 'REFERENCED' && inShell() ? (
        <Button variant="outline" disabled={busy} onClick={() => locate.mutate()}>
          Locate original…
        </Button>
      ) : null}
    </div>
  )
}
