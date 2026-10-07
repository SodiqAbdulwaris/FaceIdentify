import { Navigate, createHashRouter, type RouteObject } from 'react-router'
import { Placeholder } from '@/features/Placeholder'
import { Layout } from './Layout'

// Hash routing: the app is served from a custom protocol, where a reload on a deep path would
// otherwise ask the file server for a file that does not exist.
export const routes: RouteObject[] = [
  {
    path: '/',
    element: <Layout />,
    children: [
      { index: true, element: <Navigate to="/library" replace /> },
      { path: 'library', element: <Placeholder title="Library" /> },
      { path: 'library/source/:sourceId', element: <Placeholder title="Source" /> },
      { path: 'identities', element: <Placeholder title="People" /> },
      { path: 'identities/:identityId', element: <Placeholder title="Person" /> },
      { path: 'processing/:runId', element: <Placeholder title="Processing" /> },
    ],
  },
]

export const createRouter = () => createHashRouter(routes)
