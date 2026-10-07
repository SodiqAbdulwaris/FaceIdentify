// The operations the screens use, typed by the generated schema. One function per operation.

import type { ApiClient } from './client'
import type {
  IdentitySummary,
  ImportRequest,
  OccurrenceSummary,
  Page,
  ProcessingRun,
  Readiness,
  SourceDetail,
  SourceSummary,
} from './types'

const V1 = '/api/v1'

export const endpoints = (api: ApiClient) => ({
  readiness: () => api.get<Readiness>('/readiness'),

  listSources: (cursor?: string, state: 'ACTIVE' | 'RECYCLED' = 'ACTIVE') =>
    api.get<Page<SourceSummary>>(`${V1}/sources`, { state, cursor, limit: 50 }),
  getSource: (id: string) => api.get<SourceDetail>(`${V1}/sources/${id}`),
  importSource: (request: ImportRequest) => api.post<SourceDetail>(`${V1}/sources/import`, request),
  sourceMedia: (id: string) => api.blob(`${V1}/sources/${id}/media`),
  sourceOccurrences: (id: string, cursor?: string) =>
    api.get<Page<OccurrenceSummary>>(`${V1}/sources/${id}/occurrences`, { cursor, limit: 200 }),
  sourceRuns: (id: string, cursor?: string) =>
    api.get<Page<ProcessingRun>>(`${V1}/sources/${id}/processing-runs`, { cursor, limit: 50 }),
  processSource: (id: string) => api.post<ProcessingRun>(`${V1}/sources/${id}/process`),

  getRun: (id: string) => api.get<ProcessingRun>(`${V1}/processing-runs/${id}`),
  cancelRun: (id: string) => api.post<ProcessingRun>(`${V1}/processing-runs/${id}/cancel`),
  retryRun: (id: string) => api.post<ProcessingRun>(`${V1}/processing-runs/${id}/retry`),

  listIdentities: (cursor?: string) =>
    api.get<Page<IdentitySummary>>(`${V1}/identities`, { cursor, limit: 50 }),
  getIdentity: (id: string) => api.get<IdentitySummary>(`${V1}/identities/${id}`),
  identityOccurrences: (id: string, cursor?: string) =>
    api.get<Page<OccurrenceSummary>>(`${V1}/identities/${id}/occurrences`, { cursor, limit: 50 }),
})

export type Endpoints = ReturnType<typeof endpoints>
