import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { App } from '@/app/App'

describe('App', () => {
  it('renders in jsdom through the @ alias', () => {
    render(<App />)
    expect(screen.getByRole('heading', { name: 'FaceIdentify' })).toBeInTheDocument()
    expect(document.querySelector('main')).not.toBeNull()
  })
})
