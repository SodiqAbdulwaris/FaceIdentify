import { Navigate, createHashRouter, type RouteObject } from 'react-router'
import { IdentitiesPage } from '@/features/identities/IdentitiesPage'
import { IdentityPage } from '@/features/identities/IdentityPage'
import { ProcessingPage } from '@/features/processing/ProcessingPage'
import { LibraryPage } from '@/features/library/LibraryPage'
import { SearchPage } from '@/features/search/SearchPage'
import { SourcePage } from '@/features/source/SourcePage'
import { Layout } from './Layout'

// Hash routing: the app is served from a custom protocol, where a reload on a deep path would
// otherwise ask the file server for a file that does not exist.
export const routes: RouteObject[] = [
  {
    path: '/',
    element: <Layout />,
    children: [
      { index: true, element: <Navigate to="/library" replace /> },
      { path: 'library', element: <LibraryPage /> },
      { path: 'library/source/:sourceId', element: <SourcePage /> },
      { path: 'identities', element: <IdentitiesPage /> },
      { path: 'identities/:identityId', element: <IdentityPage /> },
      { path: 'search', element: <SearchPage /> },
      { path: 'processing/:runId', element: <ProcessingPage /> },
    ],
  },
]

export const createRouter = () => createHashRouter(routes)
