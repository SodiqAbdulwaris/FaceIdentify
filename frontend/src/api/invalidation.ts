// What an event makes stale. Events carry ids, never state: the screen refetches from REST.

import type { QueryKey } from '@tanstack/react-query'
import type { EventEnvelope } from './events'
import { keys } from './keys'

export function staleBecauseOf(event: EventEnvelope): QueryKey[] {
  if (event.type.startsWith('source.')) {
    // ['identity']: a face of a recycled image carries a marker on every open person page
    return [keys.sources, keys.source(event.resource.id), ['identity']]
  }
  if (event.type.startsWith('processing_run.')) {
    const sourceId = event.data.source_id
    return [
      keys.run(event.resource.id),
      keys.runs, // the newest run (its policy is shown on every screen) and any list of runs
      ...(typeof sourceId === 'string' ? [keys.source(sourceId)] : []),
      keys.sources, // a source's processing status is part of the library list
      keys.identities, // an accepted run creates and grows identities
      keys.people, // a person's identity count follows
      ['identity'], // every open identity page (their counts and faces change)
    ]
  }
  if (
    event.type.startsWith('person.') ||
    event.type.startsWith('occurrence.') ||
    event.type.startsWith('identity.')
  ) {
    // A name or a corrected face shows on the people list, every person page and every source.
    return [keys.identities, keys.people, ['identity'], ['source']]
  }
  return []
}
