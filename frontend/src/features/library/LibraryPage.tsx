import { useInfiniteQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useLocation } from 'react-router'
import { keys } from '@/api/keys'
import { useBackend } from '@/app/useBackend'
import { Button } from '@/components/ui/button'
import { chooseImages } from '@/native/backend'
import { SourceCard } from './SourceCard'
import { errorMessage, importSummary, type ImportOutcome } from './messages'

export function LibraryPage() {
  const { endpoints } = useBackend()
  const queryClient = useQueryClient()
  // A screen that sent us here (a deleted image's page) may have something to tell.
  const arrived = (useLocation().state as { notice?: string | null } | null)?.notice ?? null
  const [notice, setNotice] = useState<string | null>(arrived)
  const [view, setView] = useState<'library' | 'bin'>('library')
  const bin = view === 'bin'

  const sources = useInfiniteQuery({
    queryKey: bin ? keys.recycledSources : keys.sources,
    queryFn: ({ pageParam }) => endpoints.listSources(pageParam, bin ? 'RECYCLED' : 'ACTIVE'),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (page) => page.page.next_cursor ?? undefined,
  })

  const importImages = useMutation({
    mutationFn: async (): Promise<ImportOutcome | null> => {
      const paths = await chooseImages()
      if (paths.length === 0) return null // the user cancelled the dialog
      const outcome: ImportOutcome = { imported: 0, failed: [] }
      for (const path of paths) {
        try {
          await endpoints.importSource({ path, storage_mode: 'MANAGED' })
          outcome.imported += 1
        } catch (error) {
          outcome.failed.push({ path, message: errorMessage(error) })
        }
      }
      return outcome
    },
    onSuccess: (outcome) => {
      if (outcome !== null) setNotice(importSummary(outcome))
      void queryClient.invalidateQueries({ queryKey: keys.sources })
    },
    onError: (error) => setNotice(errorMessage(error)),
  })

  const items = sources.data?.pages.flatMap((page) => page.items) ?? []

  return (
    <section className="flex flex-col gap-4">
      <div className="flex items-center gap-3">
        <h1 className="text-xl font-semibold">{bin ? 'Recycle bin' : 'Library'}</h1>
        <div role="group" aria-label="Library view" className="flex gap-1">
          <Button
            size="sm"
            variant={bin ? 'outline' : 'secondary'}
            aria-pressed={!bin}
            onClick={() => setView('library')}
          >
            Library
          </Button>
          <Button
            size="sm"
            variant={bin ? 'secondary' : 'outline'}
            aria-pressed={bin}
            onClick={() => setView('bin')}
          >
            Recycle bin
          </Button>
        </div>
        {bin ? null : (
          <Button
            className="ml-auto"
            disabled={importImages.isPending}
            onClick={() => importImages.mutate()}
          >
            {importImages.isPending ? 'Importing…' : 'Import images'}
          </Button>
        )}
      </div>

      {notice ? (
        <p
          role="status"
          aria-label="Library notice"
          className="rounded-md bg-muted px-3 py-2 text-sm"
        >
          {notice}
        </p>
      ) : null}

      {sources.isPending ? <p className="text-muted-foreground">Loading your library…</p> : null}
      {sources.isError ? (
        <p role="alert" className="text-destructive">
          Your library could not be loaded: {errorMessage(sources.error)}
        </p>
      ) : null}
      {sources.isSuccess && items.length === 0 ? (
        <div className="rounded-lg border border-dashed p-10 text-center text-muted-foreground">
          {bin ? (
            <>
              <p className="font-medium text-foreground">The recycle bin is empty</p>
              <p>Images you recycle wait here until you restore them.</p>
            </>
          ) : (
            <>
              <p className="font-medium text-foreground">No images yet</p>
              <p>Import images to find and group the people in them.</p>
            </>
          )}
        </div>
      ) : null}

      {items.length > 0 ? (
        <ul className="grid grid-cols-[repeat(auto-fill,minmax(12rem,1fr))] gap-4">
          {items.map((source) => (
            <SourceCard key={source.id} source={source} recycled={bin} onNotice={setNotice} />
          ))}
        </ul>
      ) : null}

      {sources.hasNextPage ? (
        <Button
          variant="outline"
          className="self-center"
          disabled={sources.isFetchingNextPage}
          onClick={() => void sources.fetchNextPage()}
        >
          {sources.isFetchingNextPage ? 'Loading…' : 'Load more'}
        </Button>
      ) : null}
    </section>
  )
}
