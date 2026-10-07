import { NavLink, Outlet } from 'react-router'
import { useUi } from '@/state/ui'

const link = ({ isActive }: { isActive: boolean }) =>
  `rounded-md px-3 py-1.5 text-sm ${
    isActive ? 'bg-accent font-medium' : 'text-muted-foreground hover:bg-accent/50'
  }`

export function Layout() {
  const eventsStatus = useUi((state) => state.eventsStatus)
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
      <main className="flex-1 p-4">
        <Outlet />
      </main>
    </div>
  )
}
