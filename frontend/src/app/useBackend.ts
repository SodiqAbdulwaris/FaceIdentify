import { createContext, useContext } from 'react'
import type { ApiClient } from '@/api/client'
import type { Endpoints } from '@/api/endpoints'
import type { Connection } from '@/native/backend'

export interface BackendValue {
  connection: Connection
  api: ApiClient
  endpoints: Endpoints
}

export const BackendContext = createContext<BackendValue | null>(null)

/** The backend client and its operations (inside the gate, so the backend is ready). */
export function useBackend(): BackendValue {
  const value = useContext(BackendContext)
  if (value === null) throw new Error('useBackend is used outside a BackendProvider')
  return value
}
