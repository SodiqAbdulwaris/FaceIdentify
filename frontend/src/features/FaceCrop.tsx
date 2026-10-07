import { useState } from 'react'
import type { BoundingBox } from '@/api/types'
import { useSourceImage } from './useSourceImage'

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
  const [natural, setNatural] = useState<{ width: number; height: number } | null>(null)

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
              setNatural({ width: image.naturalWidth, height: image.naturalHeight })
            }
          }}
        />
      ) : null}
    </div>
  )
}
