import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach, vi } from 'vitest'

// jsdom does not implement object URLs (the app shows fetched images through them).
let counter = 0
URL.createObjectURL = vi.fn(() => `blob:test/${(counter += 1)}`)
URL.revokeObjectURL = vi.fn()

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})
