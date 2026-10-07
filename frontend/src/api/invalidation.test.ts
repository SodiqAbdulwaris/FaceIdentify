import { describe, expect, it } from 'vitest'
import type { EventEnvelope } from './events'
import { staleBecauseOf } from './invalidation'
import { keys } from './keys'

const event = (type: string, id: string, data: Record<string, unknown> = {}): EventEnvelope => ({
  version: 1,
  event_id: 'e',
  sequence: 1,
  type,
  occurred_at: '2026-01-01T00:00:00Z',
  resource: { type: type.split('.')[0], id },
  data,
})

describe('staleBecauseOf', () => {
  it('a new source makes the library list and that source stale', () => {
    expect(staleBecauseOf(event('source.created', 's1'))).toEqual([keys.sources, keys.source('s1')])
  })

  it('a run change makes the run, its source, the library and the people stale', () => {
    const stale = staleBecauseOf(
      event('processing_run.updated', 'r1', { source_id: 's1', state: 'COMPLETED' }),
    )

    expect(stale).toEqual([
      keys.run('r1'),
      keys.runs,
      keys.source('s1'),
      keys.sources,
      keys.identities,
      ['identity'],
    ])
  })

  it('a run change without a source id still refreshes what it can', () => {
    expect(staleBecauseOf(event('processing_run.created', 'r1'))).toEqual([
      keys.run('r1'),
      keys.runs,
      keys.sources,
      keys.identities,
      ['identity'],
    ])
  })

  it('an event it does not know makes nothing stale', () => {
    expect(staleBecauseOf(event('camera.frame', 'c1'))).toEqual([])
  })

  it('the keys it names are prefixes of the keys the screens read', () => {
    expect(keys.source('s1')).toEqual(['source', 's1'])
    expect(keys.latestRun.slice(0, 1)).toEqual(keys.runs)
    expect(keys.sourceRuns('s1').slice(0, 2)).toEqual(keys.source('s1'))
    expect(keys.sourceOccurrences('s1').slice(0, 2)).toEqual(keys.source('s1'))
    expect(keys.identityOccurrences('p1').slice(0, 2)).toEqual(keys.identity('p1'))
  })
})
