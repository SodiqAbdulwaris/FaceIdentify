import type { OccurrenceSummary } from '@/api/types'

export interface Face {
  occurrence: OccurrenceSummary
  /** A stable, human label for the person within this screen ("Person 1"). */
  label: string
}

/**
 * Number the people on one image in the order they first appear, so the same identity has the
 * same label on every face and in the list beside the image.
 */
export function labelFaces(occurrences: OccurrenceSummary[]): Face[] {
  const numbers = new Map<string, number>()
  return occurrences.map((occurrence) => {
    if (!numbers.has(occurrence.identity_id)) numbers.set(occurrence.identity_id, numbers.size + 1)
    return { occurrence, label: `Person ${numbers.get(occurrence.identity_id)}` }
  })
}
