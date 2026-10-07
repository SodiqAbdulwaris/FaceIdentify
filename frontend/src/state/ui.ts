// Client-only UI state (decision 5): nothing here is server data, which lives in the query cache.

import { create } from 'zustand'
import type { EventsStatus } from '@/api/events'

interface UiState {
  eventsStatus: EventsStatus
  setEventsStatus: (status: EventsStatus) => void
}

export const useUi = create<UiState>((set) => ({
  eventsStatus: 'connecting',
  setEventsStatus: (eventsStatus) => set({ eventsStatus }),
}))
