import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router'
import { keys } from '@/api/keys'
import { useBackend } from '@/app/useBackend'
import { Button } from '@/components/ui/button'
import type { SourceSummary } from '@/api/types'
import { StatusBadge } from '../StatusBadge'
import { canProcess } from '../status'
import { useSourceImage } from '../useSourceImage'
import { errorMessage } from './messages'

interface Props {
  source: SourceSummary
  /** The card is in the recycle bin: it offers Restore, and no processing. */
  recycled?: boolean
  /** What to tell the person: a message when a request failed, null to clear it. */
  onNotice: (message: string | null) => void
}

export function SourceCard({ source, recycled = false, onNotice }: Props) {
  const { endpoints } = useBackend()
  const queryClient = useQueryClient()
  const missing = source.availability !== 'AVAILABLE'
  const image = useSourceImage(source.id, !missing)
  // One request per card, so a second click elsewhere cannot make this button look idle again.
  const process = useMutation({
    mutationFn: () => endpoints.processSource(source.id),
    onSuccess: () => onNotice(null),
    onError: (error) => onNotice(errorMessage(error)),
    onSettled: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: keys.sources }),
        queryClient.invalidateQueries({ queryKey: keys.runs }),
      ]),
  })

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
    <li className="flex flex-col overflow-hidden rounded-lg border bg-card">
      <Link to={`/library/source/${source.id}`} className="block aspect-[4/3] bg-muted">
        {image.url ? (
          <img src={image.url} alt={source.display_name} className="size-full object-cover" />
        ) : (
          <span className="flex size-full items-center justify-center p-2 text-center text-xs text-muted-foreground">
            {missing ? 'The file is missing' : image.isError ? 'Could not load' : 'Loading…'}
          </span>
        )}
      </Link>
      <div className="flex flex-1 flex-col gap-2 p-3">
        <Link
          to={`/library/source/${source.id}`}
          className="truncate text-sm font-medium hover:underline"
          title={source.display_name}
        >
          {source.display_name}
        </Link>
        <div className="mt-auto flex items-center justify-between gap-2">
          <StatusBadge state={source.processing_status} />
          {recycled ? (
            <Button
              size="sm"
              variant="outline"
              disabled={move.isPending}
              onClick={() => move.mutate()}
              aria-label={`Restore ${source.display_name}`}
            >
              Restore
            </Button>
          ) : canProcess(source.processing_status) && !missing ? (
            <Button
              size="sm"
              variant="outline"
              disabled={process.isPending}
              onClick={() => process.mutate()}
              aria-label={`Process ${source.display_name}`}
            >
              Process
            </Button>
          ) : null}
          {recycled ? null : (
            <Button
              size="sm"
              variant="ghost"
              disabled={move.isPending}
              onClick={() => move.mutate()}
              aria-label={`Move ${source.display_name} to the recycle bin`}
            >
              Recycle
            </Button>
          )}
        </div>
      </div>
    </li>
  )
}
