import { describe, expect, it } from 'vitest'
import { appearanceLink, personLabel } from './label'

describe('personLabel', () => {
  it('is the start of the identity id, in capitals, without dashes', () => {
    expect(personLabel('3f9a2c1d-0000-4000-8000-000000000000')).toBe('Person 3F9A2C')
    expect(personLabel('i1')).toBe('Person I1')
  })

  it('is the name once the person has one, whatever the id', () => {
    expect(personLabel('i1', { display_name: 'Alice' })).toBe('Alice')
    expect(personLabel('i1', null)).toBe('Person I1')
  })

  it('differs between identities and is the same for the same identity', () => {
    const a = '3f9a2c1d-0000-4000-8000-000000000000'
    const b = '8e11b0aa-0000-4000-8000-000000000000'

    expect(personLabel(a)).toBe(personLabel(a))
    expect(personLabel(a)).not.toBe(personLabel(b))
  })
})

describe('appearanceLink', () => {
  it('leads to the image, or to the camera for a face that has its own kept picture', () => {
    expect(appearanceLink('s1', { face_crop: null })).toBe('/library/source/s1')
    expect(appearanceLink('s1', null)).toBe('/library/source/s1')
    expect(appearanceLink('cam1', { face_crop: { url: '/x' } })).toBe('/cameras/cam1')
  })
})
