import { Link } from 'react-router'
import { Button } from '@/components/ui/button'
import type { SourceSummary } from '@/api/types'
import { StatusBadge } from '../StatusBadge'
import { canProcess } from '../status'
import { useSourceImage } from '../useSourceImage'

interface Props {
  source: SourceSummary
  onProcess: (sourceId: string) => void
  processing: boolean
}

export function SourceCard({ source, onProcess, processing }: Props) {
  const missing = source.availability !== 'AVAILABLE'
  const image = useSourceImage(source.id, !missing)

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
          {canProcess(source.processing_status) && !missing ? (
            <Button
              size="sm"
              variant="outline"
              disabled={processing}
              onClick={() => onProcess(source.id)}
              aria-label={`Process ${source.display_name}`}
            >
              Process
            </Button>
          ) : null}
        </div>
      </div>
    </li>
  )
}
