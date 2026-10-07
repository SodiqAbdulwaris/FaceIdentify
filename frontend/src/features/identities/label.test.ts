import { describe, expect, it } from 'vitest'
import { personLabel } from './label'

describe('personLabel', () => {
  it('is the start of the identity id, in capitals, without dashes', () => {
    expect(personLabel('3f9a2c1d-0000-4000-8000-000000000000')).toBe('Person 3F9A2C')
    expect(personLabel('i1')).toBe('Person I1')
  })

  it('differs between identities and is the same for the same identity', () => {
    const a = '3f9a2c1d-0000-4000-8000-000000000000'
    const b = '8e11b0aa-0000-4000-8000-000000000000'

    expect(personLabel(a)).toBe(personLabel(a))
    expect(personLabel(a)).not.toBe(personLabel(b))
  })
})
