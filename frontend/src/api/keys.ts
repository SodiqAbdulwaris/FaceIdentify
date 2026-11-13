// One place for query keys, so what an event invalidates and what a screen reads cannot drift.

export const keys = {
  readiness: ['readiness'] as const,
  models: ['runtime', 'models'] as const,
  recognitionMode: ['runtime', 'recognition-mode'] as const,
  sources: ['sources'] as const,
  recycledSources: ['sources', 'recycled'] as const, // under `sources`: one invalidation covers both
  source: (id: string) => ['source', id] as const,
  sourceRuns: (id: string) => ['source', id, 'runs'] as const,
  sourceUnresolved: (id: string) => ['source', id, 'unresolved'] as const,
  sourceReviews: (id: string) => ['source', id, 'reviews'] as const,
  sourceOccurrences: (id: string) => ['source', id, 'occurrences'] as const,
  sourceMedia: (id: string) => ['source', id, 'media'] as const,
  run: (id: string) => ['run', id] as const,
  runs: ['runs'] as const,
  latestRun: ['runs', 'latest'] as const,
  identities: ['identities'] as const,
  people: ['people'] as const,
  faceSearch: (id: number) => ['search', 'face', id] as const, // (under `search`: events refresh it)
  search: (q: string, recycled: string) => ['search', q, recycled] as const,
  identity: (id: string) => ['identity', id] as const,
  identityOccurrences: (id: string) => ['identity', id, 'occurrences'] as const,
  cameras: ['cameras'] as const,
  cameraDevices: ['cameras', 'devices'] as const,
  cameraPreview: (id: string) => ['cameras', id, 'preview'] as const,
  cameraFace: (id: string, observationId: string) =>
    ['cameras', id, 'face', observationId] as const,
}
