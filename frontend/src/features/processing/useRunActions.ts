import { useMutation, useQueryClient, type QueryKey } from '@tanstack/react-query'
import { keys } from '@/api/keys'
import type { ProcessingRun } from '@/api/types'
import { useBackend } from '@/app/useBackend'
import { errorMessage } from '../library/messages'

/**
 * Start, stop and retry processing. Every action says what to tell the person when it fails and
 * refreshes what it changed (the events do the same, but this does not wait for them).
 */
export function useRunActions(onNotice: (message: string | null) => void) {
  const { endpoints } = useBackend()
  const queryClient = useQueryClient()

  const refresh = (run: ProcessingRun | undefined, sourceId: string | undefined) => {
    const stale: QueryKey[] = [keys.runs, keys.sources, keys.identities]
    if (sourceId) stale.push(keys.source(sourceId))
    if (run) stale.push(keys.run(run.id))
    return Promise.all(stale.map((queryKey) => queryClient.invalidateQueries({ queryKey })))
  }

  const settle = {
    onSuccess: () => onNotice(null),
    onError: (error: unknown) => onNotice(errorMessage(error)),
  }

  const process = useMutation({
    mutationFn: (sourceId: string) => endpoints.processSource(sourceId),
    ...settle,
    onSettled: (run, _error, sourceId) => refresh(run, sourceId),
  })
  const cancel = useMutation({
    mutationFn: (run: ProcessingRun) => endpoints.cancelRun(run.id),
    ...settle,
    onSettled: (run, _error, requested) => refresh(run ?? requested, requested.source_id),
  })
  const retry = useMutation({
    mutationFn: (run: ProcessingRun) => endpoints.retryRun(run.id),
    ...settle,
    onSettled: (run, _error, requested) => refresh(run ?? requested, requested.source_id),
  })

  return { process, cancel, retry, busy: process.isPending || cancel.isPending || retry.isPending }
}
