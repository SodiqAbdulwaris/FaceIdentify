import { describe, expect, it } from 'vitest'
import type { OccurrenceSummary } from '@/api/types'
import { occurrence } from '@/test/fixtures'
import { labelFaces } from './faces'

const make = (id: string, identity: string) =>
  occurrence({ id, identity_id: identity }) as unknown as OccurrenceSummary

describe('labelFaces', () => {
  it('labels each face with its person, the same person the same way', () => {
    const faces = labelFaces([make('a', 'x1'), make('b', 'y2'), make('c', 'x1')])

    expect(faces.map((f) => f.label)).toEqual(['Person X1', 'Person Y2', 'Person X1'])
    expect(faces.map((f) => f.occurrence.id)).toEqual(['a', 'b', 'c'])
  })

  it('has nobody to label when there are no faces', () => {
    expect(labelFaces([])).toEqual([])
  })
})
