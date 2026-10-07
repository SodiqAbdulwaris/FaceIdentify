import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { keys } from '@/api/keys'
import { useBackend } from '@/app/useBackend'

/** A short-lived address for a blob (revoked when the blob changes or the component goes away). */
function useObjectUrl(blob: Blob | undefined): string | undefined {
  const [url, setUrl] = useState<string>()
  // An object URL is a registration in the browser (an external system) that has to be undone,
  // so it is made and revoked in an effect, and its address is state.
  useEffect(() => {
    if (blob === undefined) {
      // oxlint-disable-next-line react/set-state-in-effect -- synchronising with the URL registry
      setUrl(undefined)
      return
    }
    const made = URL.createObjectURL(blob)
    // oxlint-disable-next-line react/set-state-in-effect -- synchronising with the URL registry
    setUrl(made)
    return () => URL.revokeObjectURL(made)
  }, [blob])
  return url
}

/**
 * A source's original, fetched with the launch token (an `<img src>` cannot send it) and shown
 * through an object URL. The bytes of an imported original never change, so they are kept.
 */
export function useSourceImage(sourceId: string, enabled = true) {
  const { endpoints } = useBackend()
  const media = useQuery({
    queryKey: keys.sourceMedia(sourceId),
    queryFn: () => endpoints.sourceMedia(sourceId),
    staleTime: Infinity,
    gcTime: 5 * 60_000,
    enabled,
    retry: false,
  })
  return { url: useObjectUrl(media.data), isLoading: media.isLoading, isError: media.isError }
}
