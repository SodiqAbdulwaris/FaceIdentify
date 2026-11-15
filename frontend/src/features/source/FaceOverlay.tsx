import { useState } from 'react'
import { Link } from 'react-router'
import type { Face } from './faces'

/**
 * The image with a box on each face found (the boxes are fractions of the image, so they scale).
 * The frame is given the image's own proportions once they are known, so it is exactly as wide as
 * the picture drawn in it: a tall picture shrunk to the height limit would otherwise leave the
 * frame wider than the picture, and every box would be placed against the frame.
 */
export function FaceOverlay({ url, alt, faces }: { url: string; alt: string; faces: Face[] }) {
  const [measured, setMeasured] = useState<{ url: string; ratio: number } | null>(null)
  const ratio = measured && measured.url === url ? measured.ratio : null
  return (
    <div
      className="relative inline-block max-w-full"
      style={ratio ? { aspectRatio: ratio, width: `min(100%, calc(70vh * ${ratio}))` } : undefined}
    >
      <img
        src={url}
        alt={alt}
        className={ratio ? 'block size-full' : 'block max-h-[70vh] max-w-full'}
        onLoad={(event) => {
          const image = event.currentTarget
          if (image.naturalWidth > 0 && image.naturalHeight > 0) {
            setMeasured({ url, ratio: image.naturalWidth / image.naturalHeight })
          }
        }}
      />
      {faces.map(({ occurrence, label }) => {
        const box = occurrence.representative_observation?.bounding_box
        if (!box) return null
        return (
          <Link
            key={occurrence.id}
            to={`/identities/${occurrence.identity_id}`}
            aria-label={`${label}: open`}
            title={label}
            className="absolute rounded-sm border-2 border-amber-400 hover:bg-amber-400/20 focus-visible:outline-2"
            style={{
              left: `${box.x * 100}%`,
              top: `${box.y * 100}%`,
              width: `${box.width * 100}%`,
              height: `${box.height * 100}%`,
            }}
          />
        )
      })}
    </div>
  )
}
