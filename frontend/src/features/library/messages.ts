import { ApiError } from '@/api/client'

/** What to tell a person about a failed request: the API's own message, never a stack or an id. */
export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message
  return 'Something went wrong.'
}

export interface ImportOutcome {
  imported: number
  failed: { path: string; message: string }[]
}

export function importSummary({ imported, failed }: ImportOutcome): string {
  const done = `Imported ${imported} ${imported === 1 ? 'image' : 'images'}.`
  if (failed.length === 0) return done
  const first = failed[0]
  const name = first.path.split(/[\\/]/).pop()
  return `${done} ${failed.length} could not be imported (${name}: ${first.message}).`
}
