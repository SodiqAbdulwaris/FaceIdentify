import { useInfiniteQuery } from '@tanstack/react-query'
import { keys } from '@/api/keys'
import { useBackend } from '@/app/useBackend'

/** The people a face can be given to, a page at a time (the one it already has can be left out). */
export function usePeopleChoices(enabled: boolean, exceptIdentityId?: string) {
  const { endpoints } = useBackend()
  const query = useInfiniteQuery({
    queryKey: keys.identities,
    queryFn: ({ pageParam }) => endpoints.listIdentities(pageParam),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (page) => page.page.next_cursor ?? undefined,
    enabled,
  })
  const choices = (query.data?.pages.flatMap((page) => page.items) ?? []).filter(
    (identity) => identity.id !== exceptIdentityId,
  )
  return { choices, query }
}
