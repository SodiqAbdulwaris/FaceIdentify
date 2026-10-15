/** Why the file is not available, in words (the API's `availability_reason`). */
export function missingReason(reason: string | null | undefined): string {
  if (reason === 'REFERENCED_CONTENT_CHANGED')
    return 'A different file is now where this image was, so it is not the original any more.'
  return 'The file for this image is missing. Put it back where it was to see it again.'
}
