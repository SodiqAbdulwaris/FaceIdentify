// The backend connection as the rest of the app sees it: one client and its operations.

import { useMemo, type ReactNode } from 'react'
import { ApiClient } from '@/api/client'
import { endpoints } from '@/api/endpoints'
import type { Connection } from '@/native/backend'
import { BackendContext } from './useBackend'

export function BackendProvider({
  connection,
  children,
}: {
  connection: Connection
  children: ReactNode
}) {
  const value = useMemo(() => {
    const api = new ApiClient(connection)
    return { connection, api, endpoints: endpoints(api) }
  }, [connection])
  return <BackendContext.Provider value={value}>{children}</BackendContext.Provider>
}
