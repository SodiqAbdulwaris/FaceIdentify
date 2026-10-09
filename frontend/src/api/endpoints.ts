// The operations the screens use, typed by the generated schema. One function per operation.

import type { ApiClient } from './client'
import type {
  DeletionPending,
  ForgetPending,
  IdentitySummary,
  ImportRequest,
  OccurrenceSummary,
  Page,
  SearchResponse,
  UnresolvedFace,
  PersonSummary,
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
  recycleSource: (id: string) => api.delete(`${V1}/sources/${id}`),
  restoreSource: (id: string) => api.post<SourceDetail>(`${V1}/sources/${id}/restore`),
  deleteSourcePermanently: (id: string) =>
    api.command<DeletionPending>(`${V1}/sources/${id}/permanent-delete`),
  importSource: (request: ImportRequest) => api.post<SourceDetail>(`${V1}/sources/import`, request),
  sourceMedia: (id: string) => api.blob(`${V1}/sources/${id}/media`),
  sourceOccurrences: (id: string, cursor?: string) =>
    api.get<Page<OccurrenceSummary>>(`${V1}/sources/${id}/occurrences`, { cursor, limit: 200 }),
  sourceRuns: (id: string, cursor?: string) =>
    api.get<Page<ProcessingRun>>(`${V1}/sources/${id}/processing-runs`, { cursor, limit: 50 }),
  processSource: (id: string) => api.post<ProcessingRun>(`${V1}/sources/${id}/process`),

  search: (q: string, recycled: 'include' | 'exclude' = 'exclude') =>
    api.get<SearchResponse>(`${V1}/search`, { q, recycled }),

  listRuns: (cursor?: string, limit = 50) =>
    api.get<Page<ProcessingRun>>(`${V1}/processing-runs`, { cursor, limit }),
  getRun: (id: string) => api.get<ProcessingRun>(`${V1}/processing-runs/${id}`),
  cancelRun: (id: string) => api.post<ProcessingRun>(`${V1}/processing-runs/${id}/cancel`),
  retryRun: (id: string) => api.post<ProcessingRun>(`${V1}/processing-runs/${id}/retry`),

  listIdentities: (cursor?: string) =>
    api.get<Page<IdentitySummary>>(`${V1}/identities`, { cursor, limit: 50 }),
  getIdentity: (id: string) => api.get<IdentitySummary>(`${V1}/identities/${id}`),
  unresolvedFaces: (sourceId: string) =>
    api.get<{ items: UnresolvedFace[] }>(`${V1}/sources/${sourceId}/unresolved-faces`),
  resolveFace: (representationId: string, identityId: string | null) =>
    api.post<OccurrenceSummary>(`${V1}/representations/${representationId}/resolve`, {
      identity_id: identityId,
    }),
  mergeIdentities: (loser: IdentitySummary, survivor: IdentitySummary) =>
    api.post<IdentitySummary>(`${V1}/identities/merge`, {
      identities: [
        { id: loser.id, revision: loser.revision },
        { id: survivor.id, revision: survivor.revision },
      ],
      preferred_identity_id: survivor.id,
    }),
  splitFaces: (identity: IdentitySummary, occurrenceIds: string[]) =>
    api.post<IdentitySummary>(`${V1}/identities/${identity.id}/split`, {
      occurrence_ids: occurrenceIds,
      expected_revision: identity.revision,
    }),
  forgetIdentity: (identity: IdentitySummary) =>
    api.command<ForgetPending>(`${V1}/identities/${identity.id}/forget`, {
      expected_revision: identity.revision,
    }),
  forgetPerson: (personId: string) => api.command<ForgetPending>(`${V1}/people/${personId}/forget`),
  confirmFace: (occurrenceId: string, expectedIdentityId: string) =>
    api.post<OccurrenceSummary>(`${V1}/occurrences/${occurrenceId}/confirm`, {
      expected_identity_id: expectedIdentityId,
    }),
  moveFace: (occurrenceId: string, expectedIdentityId: string, identityId: string | null) =>
    api.post<OccurrenceSummary>(`${V1}/occurrences/${occurrenceId}/reassign`, {
      expected_identity_id: expectedIdentityId,
      identity_id: identityId,
    }),
  listPeople: (cursor?: string) =>
    api.get<Page<PersonSummary>>(`${V1}/people`, { cursor, limit: 50 }),
  nameIdentity: (identityId: string, displayName: string) =>
    api.post<PersonSummary>(`${V1}/people`, { display_name: displayName, identity_id: identityId }),
  renamePerson: (personId: string, displayName: string, expectedRevision: number) =>
    api.patch<PersonSummary>(`${V1}/people/${personId}`, {
      display_name: displayName,
      expected_revision: expectedRevision,
    }),
  identityOccurrences: (id: string, cursor?: string) =>
    api.get<Page<OccurrenceSummary>>(`${V1}/identities/${id}/occurrences`, { cursor, limit: 50 }),
})

export type Endpoints = ReturnType<typeof endpoints>
