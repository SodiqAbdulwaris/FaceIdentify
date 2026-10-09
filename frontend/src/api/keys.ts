// One place for query keys, so what an event invalidates and what a screen reads cannot drift.

export const keys = {
  readiness: ['readiness'] as const,
  sources: ['sources'] as const,
  recycledSources: ['sources', 'recycled'] as const, // under `sources`: one invalidation covers both
  source: (id: string) => ['source', id] as const,
  sourceRuns: (id: string) => ['source', id, 'runs'] as const,
  sourceUnresolved: (id: string) => ['source', id, 'unresolved'] as const,
  sourceOccurrences: (id: string) => ['source', id, 'occurrences'] as const,
  sourceMedia: (id: string) => ['source', id, 'media'] as const,
  run: (id: string) => ['run', id] as const,
  runs: ['runs'] as const,
  latestRun: ['runs', 'latest'] as const,
  identities: ['identities'] as const,
  people: ['people'] as const,
  identity: (id: string) => ['identity', id] as const,
  identityOccurrences: (id: string) => ['identity', id, 'occurrences'] as const,
}
