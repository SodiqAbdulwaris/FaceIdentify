// Shows the user what the backend is doing until it is ready: the shell starting it, then the
// library opening (the backend opens it after it is already serving). Children render only when
// the library can be used.

import { useQuery } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { keys } from '@/api/keys'
import { backendStatus } from '@/native/backend'
import { BackendProvider } from './BackendProvider'
import { useBackend } from './useBackend'
import { EventsBridge } from './EventsBridge'

const POLL_MS = 500

function Notice({ title, detail }: { title: string; detail?: string }) {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-2 p-8 text-center">
      <h1 className="text-2xl font-semibold">{title}</h1>
      {detail ? <p className="max-w-xl text-muted-foreground">{detail}</p> : null}
    </main>
  )
}

export function BackendGate({ children }: { children: ReactNode }) {
  const status = useQuery({
    queryKey: ['backend-status'],
    queryFn: backendStatus,
    refetchInterval: (query) => (query.state.data?.state === 'starting' ? POLL_MS : false),
    retry: false,
  })

  if (status.isError) {
    return <Notice title="FaceIdentify could not start" detail={String(status.error)} />
  }
  if (status.data === undefined || status.data.state === 'starting') {
    return <Notice title="Starting FaceIdentify…" />
  }
  if (status.data.state === 'failed') {
    return <Notice title="FaceIdentify could not start" detail={status.data.error} />
  }
  return (
    <BackendProvider connection={status.data.connection}>
      <LibraryGate>{children}</LibraryGate>
    </BackendProvider>
  )
}

function LibraryGate({ children }: { children: ReactNode }) {
  const { endpoints } = useBackend()
  const readiness = useQuery({
    queryKey: keys.readiness,
    queryFn: endpoints.readiness,
    refetchInterval: (query) =>
      query.state.data?.state === 'INITIALIZING' || query.state.status === 'error'
        ? POLL_MS
        : false,
    retry: true,
    retryDelay: POLL_MS,
  })

  const state = readiness.data?.state
  if (state === 'READY' || state === 'DEGRADED') {
    const capabilities = readiness.data?.capabilities ?? {}
    // Only the real profile reports these; a missing one is not a reason to show the notice.
    const unfinished =
      capabilities.runtime_package === 'UNAVAILABLE' ||
      capabilities.processing_policy === 'UNAVAILABLE'
    return (
      <>
        <EventsBridge />
        {unfinished ? (
          <p role="note" className="border-b bg-amber-50 px-4 py-2 text-sm text-amber-950">
            Recognition is not set up yet, so pictures are not processed.{' '}
            <a className="underline" href="#/setup">
              Finish setting it up
            </a>
          </p>
        ) : null}
        {children}
      </>
    )
  }
  if (state === 'FAILED') {
    return (
      <Notice
        title="Your library could not be opened"
        detail={readiness.data?.failure ? `Reason: ${readiness.data.failure}` : undefined}
      />
    )
  }
  return <Notice title="Opening your library…" />
}
