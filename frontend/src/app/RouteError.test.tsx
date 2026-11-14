import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { page, renderApp } from '@/test/harness'

describe('an address or a screen that fails', () => {
  it('shows the app’s own words and a way back for an address it does not know', async () => {
    renderApp('/nowhere', [{ path: '/api/v1/sources', respond: page([]) }])

    expect(
      await screen.findByRole('heading', { name: 'That page does not exist' }),
    ).toBeInTheDocument()
    expect(screen.queryByText(/Hey developer/)).toBeNull()
    expect(screen.getByRole('link', { name: 'Back to the library' })).toHaveAttribute(
      'href',
      '/library',
    )
  })
})
