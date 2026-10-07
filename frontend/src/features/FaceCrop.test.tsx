import { fireEvent, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { page, renderApp } from '@/test/harness'

// The crop is checked through the screen that uses it (the people list), so it has the real
// image address and the real query behind it.
const identity = {
  id: 'i1',
  state: 'ACTIVE',
  representative_observation: {
    id: 'ob1',
    source_id: 's1',
    bounding_box: { x: 0.25, y: 0.5, width: 0.25, height: 0.25 },
    face_crop: null,
  },
  occurrence_count: 1,
  source_count: 1,
  created_at: '2026-01-01T00:00:00Z',
  activated_at: null,
}

async function faceImage(box = identity.representative_observation.bounding_box) {
  renderApp('/identities', [
    {
      path: '/api/v1/identities',
      respond: page([
        {
          ...identity,
          representative_observation: { ...identity.representative_observation, bounding_box: box },
        },
      ]),
    },
    { path: '/api/v1/sources/s1/media', respond: 'bytes' },
  ])
  return screen.findByRole('img', { name: "Person I1's face" })
}

function loaded(image: HTMLElement, width: number, height: number) {
  Object.defineProperty(image, 'naturalWidth', { value: width, configurable: true })
  Object.defineProperty(image, 'naturalHeight', { value: height, configurable: true })
  fireEvent.load(image)
}

describe('FaceCrop', () => {
  it('shows the plain image, undistorted, until it knows the image size', async () => {
    const image = await faceImage()

    expect(image).toHaveStyle({ width: '96px', height: '96px', objectFit: 'cover' })
  })

  it('scales and shifts the image so the box fills the tile, in proportion', async () => {
    const image = await faceImage()

    loaded(image, 1000, 800) // the box is 250 x 200 px: the 96 px tile is filled by its longer side

    const scale = 96 / 250
    const px = (value: string) => Number.parseFloat(value)
    expect(px(image.style.width)).toBeCloseTo(1000 * scale)
    expect(px(image.style.height)).toBeCloseTo(800 * scale)
    expect(px(image.style.marginLeft)).toBeCloseTo(-(0.25 * 1000 * scale) + (96 - 250 * scale) / 2)
    expect(px(image.style.marginTop)).toBeCloseTo(-(0.5 * 800 * scale) + (96 - 200 * scale) / 2)
  })

  it('stays plain when the browser reports no size', async () => {
    const image = await faceImage()

    loaded(image, 0, 0)

    expect(image).toHaveStyle({ width: '96px', height: '96px', objectFit: 'cover' })
    expect(image.style.maxWidth).toBe('') // none of the crop's styling was applied
    expect(image.style.marginLeft).toBe('')
  })

  it('centres a face that is taller than it is wide', async () => {
    const image = await faceImage({ x: 0.5, y: 0.25, width: 0.1, height: 0.25 })

    loaded(image, 1000, 800) // the face is 100 x 200 px: the tile is filled by its height

    const scale = 96 / 200
    const px = (value: string) => Number.parseFloat(value)
    expect(px(image.style.marginLeft)).toBeCloseTo(-(0.5 * 1000 * scale) + (96 - 100 * scale) / 2)
    expect(px(image.style.marginTop)).toBeCloseTo(-(0.25 * 800 * scale))
  })
})
