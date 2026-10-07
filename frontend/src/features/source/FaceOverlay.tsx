import { Link } from 'react-router'
import type { Face } from './faces'

/** The image with a box on each face found (the boxes are fractions of the image, so they scale). */
export function FaceOverlay({ url, alt, faces }: { url: string; alt: string; faces: Face[] }) {
  return (
    <div className="relative inline-block max-w-full">
      <img src={url} alt={alt} className="block max-h-[70vh] max-w-full" />
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
