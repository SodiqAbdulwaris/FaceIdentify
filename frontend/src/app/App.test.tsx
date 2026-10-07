import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { App } from '@/app/App'
import { NO_SHELL_MESSAGE } from '@/native/backend'

describe('App', () => {
  it('renders in jsdom through the @ alias and explains that it needs the desktop shell', async () => {
    render(<App />)

    expect(await screen.findByRole('heading', { name: 'FaceIdentify could not start' })).toBeInTheDocument()
    expect(screen.getByText(NO_SHELL_MESSAGE)).toBeInTheDocument()
    expect(document.querySelector('main')).not.toBeNull()
  })
})
