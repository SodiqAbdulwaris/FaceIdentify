import { useQuery } from '@tanstack/react-query'
import { NavLink, Outlet } from 'react-router'
import { keys } from '@/api/keys'
import { PolicyNotice } from '@/features/PolicyNotice'
import { useUi } from '@/state/ui'
import { useBackend } from './useBackend'

const link = ({ isActive }: { isActive: boolean }) =>
  `rounded-md px-3 py-1.5 text-sm ${
    isActive ? 'bg-accent font-medium' : 'text-muted-foreground hover:bg-accent/50'
  }`

export function Layout() {
  const eventsStatus = useUi((state) => state.eventsStatus)
  const { endpoints } = useBackend()
  // The newest run says which policy the results on screen come from.
  const latest = useQuery({
    queryKey: keys.latestRun,
    queryFn: () => endpoints.listRuns(undefined, 1),
  })
  return (
    <div className="flex min-h-screen flex-col">
      <header className="flex items-center gap-4 border-b px-4 py-2">
        <span className="font-semibold">FaceIdentify</span>
        <nav className="flex gap-1" aria-label="Main">
          <NavLink to="/library" className={link}>
            Library
          </NavLink>
          <NavLink to="/identities" className={link}>
            People
          </NavLink>
        </nav>
        <span className="ml-auto text-xs text-muted-foreground" role="status" aria-label="Live updates">
          {eventsStatus === 'open' ? 'Live' : 'Reconnecting…'}
        </span>
      </header>
      <main className="flex flex-1 flex-col gap-4 p-4">
        <PolicyNotice policy={latest.data?.items[0]?.policy} />
        <Outlet />
      </main>
    </div>
  )
}
