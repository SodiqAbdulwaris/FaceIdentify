// What an event makes stale. Events carry ids, never state: the screen refetches from REST.

import type { QueryKey } from '@tanstack/react-query'
import type { EventEnvelope } from './events'
import { keys } from './keys'

export function staleBecauseOf(event: EventEnvelope): QueryKey[] {
  if (event.type.startsWith('source.')) {
    return [keys.sources, keys.source(event.resource.id)]
  }
  if (event.type.startsWith('processing_run.')) {
    const sourceId = event.data.source_id
    return [
      keys.run(event.resource.id),
      keys.runs, // the newest run (its policy is shown on every screen) and any list of runs
      ...(typeof sourceId === 'string' ? [keys.source(sourceId)] : []),
      keys.sources, // a source's processing status is part of the library list
      keys.identities, // an accepted run creates and grows identities
      ['identity'], // every open identity page (their counts and faces change)
    ]
  }
  if (event.type.startsWith('person.')) {
    // A name shows on the people list, on every person page and on the faces of every source.
    return [keys.identities, ['identity'], ['source']]
  }
  return []
}
