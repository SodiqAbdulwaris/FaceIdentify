import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useState } from 'react'
import { RouterProvider } from 'react-router'
import { BackendGate } from './BackendGate'
import { createRouter } from './routes'

export function App() {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: { queries: { staleTime: 5_000, refetchOnWindowFocus: false } },
      }),
  )
  const [router] = useState(createRouter)
  return (
    <QueryClientProvider client={queryClient}>
      <BackendGate>
        <RouterProvider router={router} />
      </BackendGate>
    </QueryClientProvider>
  )
}
