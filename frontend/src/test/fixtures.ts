// More shapes the API returns, for the screens that show them.

export const detail = (over: Record<string, unknown> = {}) => ({
  id: 's1',
  type: 'IMAGE',
  display_name: 'beach.png',
  availability: 'AVAILABLE',
  processing_status: 'NOT_PROCESSED',
  thumbnail: null,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  state: 'ACTIVE',
  storage_mode: 'MANAGED',
  original: {
    id: 's1',
    kind: 'ORIGINAL',
    url: '/api/v1/sources/s1/media',
    content_type: 'image/png',
  },
  width: 800,
  height: 600,
  mime_type: 'image/png',
  size_bytes: 20480,
  original_filename: 'beach.png',
  latest_processing_run: null,
  recycled_at: null,
  ...over,
})

export const occurrence = (over: Record<string, unknown> = {}) => ({
  id: 'o1',
  source_id: 's1',
  source_display_name: 'beach.png',
  identity_id: 'i1',
  kind: 'IMAGE',
  representative_observation: {
    id: 'ob1',
    source_id: 's1',
    bounding_box: { x: 0.2, y: 0.1, width: 0.4, height: 0.5 },
    face_crop: null,
  },
  person: null,
  source_recycled: false,
  created_at: '2026-01-01T00:00:00Z',
  ...over,
})

export const identity = (over: Record<string, unknown> = {}) => ({
  id: 'i1',
  state: 'ACTIVE',
  revision: 1,
  person: null,
  representative_observation: null,
  occurrence_count: 1,
  source_count: 1,
  created_at: '2026-01-01T00:00:00Z',
  activated_at: '2026-01-01T00:00:00Z',
  ...over,
})
