// Friendly names for the generated schema (schema.d.ts is generated from the backend; never edit it).

import type { components } from './schema'

type Schemas = components['schemas']

export type SourceSummary = Schemas['SourceSummary']
export type SourceDetail = Schemas['SourceDetail']
export type DeletionPending = Schemas['DeletionPending']
export type ForgetPending = Schemas['ForgetPending']
export type ProcessingRun = Schemas['ProcessingRunDetail']
export type JobBrief = Schemas['JobBrief']
export type PolicyProvenance = Schemas['PolicyProvenance']
export type IdentitySummary = Schemas['IdentitySummary']
export type PersonSummary = Schemas['PersonSummary']
export type PersonReference = Schemas['PersonReference']
export type UnresolvedFace = Schemas['UnresolvedFace']
export type OccurrenceSummary = Schemas['OccurrenceSummary']
export type ObservationBrief = Schemas['ObservationBrief']
export type BoundingBox = Schemas['BoundingBox']
export type SearchResponse = Schemas['SearchResponse']
export type ImportRequest = Schemas['ImportRequest']

export interface Page<T> {
  items: T[]
  page: { next_cursor: string | null; has_more: boolean }
}

export interface Readiness {
  state: string
  capabilities?: Record<string, string>
  failure?: string
}

/** The one error shape every failing request returns (`ErrorEnvelope`). */
export interface ErrorBody {
  code: string
  message: string
  details: Record<string, unknown> | null
  retryable: boolean
  diagnostic_id: string | null
}
