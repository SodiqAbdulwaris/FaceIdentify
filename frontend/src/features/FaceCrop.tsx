import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import type { BoundingBox, ObservationBrief } from '@/api/types'
import { useBackend } from '@/app/useBackend'
import { useObjectUrl, useSourceImage } from './useSourceImage'

/**
 * One face, cut out of its image for display. The backend stores no face crops yet, so the crop is
 * made here: the original is shown scaled and shifted so that the box fills a square tile (kept
 * in proportion, with the rest hidden). Until the image's own size is known the tile shows the
 * plain image, never a distorted one.
 */
export function FaceCrop({
  sourceId,
  box,
  size = 96,
  label,
}: {
  sourceId: string
  box: BoundingBox
  size?: number
  label: string
}) {
  const { url } = useSourceImage(sourceId)
  return <CroppedImage url={url} box={box} size={size} label={label} />
}

/**
 * A face the library holds, as a square tile: its kept crop when it has one (a camera face: there
 * is no picture to cut it from), else cut out of its image.
 */
export function ObservationFace({
  face,
  size = 96,
  label,
}: {
  face: ObservationBrief
  size?: number
  label: string
}) {
  return face.face_crop ? (
    <KeptCrop url={face.face_crop.url} size={size} label={label} />
  ) : (
    <FaceCrop sourceId={face.source_id} box={face.bounding_box} size={size} label={label} />
  )
}

function KeptCrop({ url, size, label }: { url: string; size: number; label: string }) {
  const { endpoints } = useBackend()
  const picture = useQuery({
    queryKey: ['media', url],
    queryFn: () => endpoints.media(url),
    staleTime: Infinity,
    retry: false,
  })
  const shown = useObjectUrl(picture.data)
  return (
    <div
      className="shrink-0 overflow-hidden rounded-md bg-muted"
      style={{ width: size, height: size }}
    >
      {shown ? <img src={shown} alt={label} className="size-full object-cover" /> : null}
    </div>
  )
}

/** The same tile for a picture that is not in the library (the one a face search was made with). */
export function CroppedImage({
  url,
  box,
  size = 96,
  label,
}: {
  url: string | undefined
  box: BoundingBox
  size?: number
  label: string
}) {
  const [measured, setMeasured] = useState<{ url: string; width: number; height: number } | null>(
    null,
  )
  // a size measured on another image (this tile was reused) is not this image's size
  const natural = measured && measured.url === url ? measured : null

  const style = (() => {
    if (!natural) return { width: size, height: size, objectFit: 'cover' as const }
    const faceWidth = box.width * natural.width
    const faceHeight = box.height * natural.height
    const scale = size / Math.max(faceWidth, faceHeight)
    return {
      width: natural.width * scale,
      height: natural.height * scale,
      // centre the box in the tile, whichever side is shorter
      marginLeft: -(box.x * natural.width * scale) + (size - faceWidth * scale) / 2,
      marginTop: -(box.y * natural.height * scale) + (size - faceHeight * scale) / 2,
      maxWidth: 'none' as const,
    }
  })()

  return (
    <div
      className="relative shrink-0 overflow-hidden rounded-md bg-muted"
      style={{ width: size, height: size }}
    >
      {url ? (
        <img
          src={url}
          alt={label}
          style={style}
          onLoad={(event) => {
            const image = event.currentTarget
            if (image.naturalWidth > 0 && image.naturalHeight > 0) {
              setMeasured({
                url: image.src,
                width: image.naturalWidth,
                height: image.naturalHeight,
              })
            }
          }}
        />
      ) : null}
    </div>
  )
}
