import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router'
import { keys } from '@/api/keys'
import type { ReprocessReview } from '@/api/types'
import { useBackend } from '@/app/useBackend'
import { errorMessage } from '../library/messages'

const REASONS: Record<string, string> = {
  NO_CORRESPONDENCE: 'the face was not found again in the same place',
  AMBIGUOUS: 'more than one face could be it',
  SPACE_CHANGED: 'the new model describes faces differently, so they cannot be compared',
  MISSING_VECTOR: 'the earlier face no longer has a description to compare',
}

/**
 * After the image was processed again, faces a person had named or corrected that could not be
 * matched safely to the new result. Nothing was decided on their behalf: the person, their name
 * and their other faces are unchanged, and the face can be placed again here or on the person's
 * page.
 */
export function ReprocessReviews({ sourceId }: { sourceId: string }) {
  const { endpoints } = useBackend()
  const reviews = useQuery({
    queryKey: keys.sourceReviews(sourceId),
    queryFn: () => endpoints.reprocessReviews(sourceId),
  })
  if (reviews.isError) {
    return (
      <p role="alert" className="text-sm text-destructive">
        The faces to check after reprocessing could not be loaded: {errorMessage(reviews.error)}
      </p>
    )
  }
  const items = reviews.data?.items ?? []
  if (items.length === 0) return null
  return (
    <div>
      <h2 className="mb-1 font-medium">Check after reprocessing</h2>
      <p className="mb-2 text-sm text-muted-foreground">
        These faces were named or corrected before this image was processed again, and could not be
        matched safely to the new result. Nothing was changed for them.
      </p>
      <ul className="flex flex-col gap-1">
        {items.map((item) => (
          <li key={item.id} className="text-sm">
            <Review item={item} />
          </li>
        ))}
      </ul>
    </div>
  )
}

function Review({ item }: { item: ReprocessReview }) {
  const who = item.person ?? 'A person you corrected'
  return (
    <>
      <Link to={`/identities/${item.identity_id}`} className="text-primary underline">
        {who}
      </Link>
      : {REASONS[item.reason] ?? 'the face could not be matched'}.
    </>
  )
}
