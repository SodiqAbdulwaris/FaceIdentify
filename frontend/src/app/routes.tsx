import { Navigate, createHashRouter, type RouteObject } from 'react-router'
import { CameraHistoryPage } from '@/features/cameras/CameraHistoryPage'
import { CamerasPage } from '@/features/cameras/CamerasPage'
import { IdentitiesPage } from '@/features/identities/IdentitiesPage'
import { IdentityPage } from '@/features/identities/IdentityPage'
import { ProcessingPage } from '@/features/processing/ProcessingPage'
import { LibraryPage } from '@/features/library/LibraryPage'
import { SearchPage } from '@/features/search/SearchPage'
import { SetupPage } from '@/features/setup/SetupPage'
import { SourcePage } from '@/features/source/SourcePage'
import { Layout } from './Layout'
import { RouteError } from './RouteError'

// Hash routing: the app is served from a custom protocol, where a reload on a deep path would
// otherwise ask the file server for a file that does not exist.
export const routes: RouteObject[] = [
  {
    path: '/',
    element: <Layout />,
    errorElement: <RouteError />,
    children: [
      { index: true, element: <Navigate to="/library" replace /> },
      { path: 'library', element: <LibraryPage /> },
      { path: 'library/source/:sourceId', element: <SourcePage /> },
      { path: 'identities', element: <IdentitiesPage /> },
      { path: 'identities/:identityId', element: <IdentityPage /> },
      { path: 'search', element: <SearchPage /> },
      { path: 'cameras', element: <CamerasPage /> },
      { path: 'cameras/:cameraId', element: <CameraHistoryPage /> },
      { path: 'setup', element: <SetupPage /> },
      { path: 'processing/:runId', element: <ProcessingPage /> },
    ],
  },
]

export const createRouter = () => createHashRouter(routes)
