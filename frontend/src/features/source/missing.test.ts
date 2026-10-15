import { describe, expect, it } from 'vitest'
import { missingReason } from './missing'

describe('why an original is missing', () => {
  it('says the file changed when something else is in its place', () => {
    expect(missingReason('REFERENCED_CONTENT_CHANGED')).toMatch(/A different file is now where/)
    expect(missingReason('MANAGED_CONTENT_CHANGED')).toMatch(/kept in your library has changed/)
  })

  it('asks for the file back otherwise', () => {
    for (const reason of ['REFERENCED_FILE_MISSING', 'MANAGED_FILE_MISSING', null, undefined])
      expect(missingReason(reason)).toMatch(/Put it back where it was/)
  })
})
