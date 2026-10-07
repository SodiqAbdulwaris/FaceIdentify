// One place for query keys, so what an event invalidates and what a screen reads cannot drift.

export const keys = {
  readiness: ['readiness'] as const,
  sources: ['sources'] as const,
  source: (id: string) => ['source', id] as const,
  sourceRuns: (id: string) => ['source', id, 'runs'] as const,
  sourceOccurrences: (id: string) => ['source', id, 'occurrences'] as const,
  sourceMedia: (id: string) => ['source', id, 'media'] as const,
  run: (id: string) => ['run', id] as const,
  identities: ['identities'] as const,
  identity: (id: string) => ['identity', id] as const,
  identityOccurrences: (id: string) => ['identity', id, 'occurrences'] as const,
}
