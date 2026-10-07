import { describe, expect, it } from 'vitest'
import type { OccurrenceSummary } from '@/api/types'
import { occurrence } from '@/test/fixtures'
import { labelFaces } from './faces'

const make = (id: string, identity: string) =>
  occurrence({ id, identity_id: identity }) as unknown as OccurrenceSummary

describe('labelFaces', () => {
  it('numbers people in the order they first appear and gives one person one label', () => {
    const faces = labelFaces([make('a', 'x'), make('b', 'y'), make('c', 'x'), make('d', 'z')])

    expect(faces.map((f) => f.label)).toEqual(['Person 1', 'Person 2', 'Person 1', 'Person 3'])
    expect(faces.map((f) => f.occurrence.id)).toEqual(['a', 'b', 'c', 'd'])
  })

  it('has nobody to label when there are no faces', () => {
    expect(labelFaces([])).toEqual([])
  })
})
