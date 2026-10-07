// Keeps the screens fresh: each event invalidates what it makes stale; a gap or a (re)connection
// refetches everything on screen. Renders nothing.

import { useQueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'
import { EventsClient } from '@/api/events'
import { staleBecauseOf } from '@/api/invalidation'
import { useUi } from '@/state/ui'
import { useBackend } from './useBackend'

export function EventsBridge() {
  const { connection } = useBackend()
  const queryClient = useQueryClient()
  const setEventsStatus = useUi((state) => state.setEventsStatus)

  useEffect(() => {
    const client = new EventsClient(connection.events_url, connection.token, {
      onEvent: (event) => {
        for (const queryKey of staleBecauseOf(event)) {
          void queryClient.invalidateQueries({ queryKey })
        }
      },
      onResync: () => void queryClient.invalidateQueries(),
      onStatus: setEventsStatus,
    })
    client.start()
    return () => client.stop()
  }, [connection, queryClient, setEventsStatus])

  return null
}
