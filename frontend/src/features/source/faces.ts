import type { OccurrenceSummary } from '@/api/types'
import { personLabel } from '../identities/label'

export interface Face {
  occurrence: OccurrenceSummary
  /** What to call this person (the same on every screen). */
  label: string
}

export const labelFaces = (occurrences: OccurrenceSummary[]): Face[] =>
  occurrences.map((occurrence) => ({ occurrence, label: personLabel(occurrence.identity_id) }))
