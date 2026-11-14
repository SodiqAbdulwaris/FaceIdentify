import { render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { page, renderApp } from '@/test/harness'
import { RouteError } from './RouteError'

afterEach(() => vi.restoreAllMocks())

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

  it('shows the same way back, and says nothing was changed, when a screen throws', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {}) // (React reports the error it caught)
    const Broken = () => {
      throw new Error('a screen failed')
    }
    const router = createMemoryRouter(
      [
        { path: '/library', element: <p>the library</p> },
        { path: '/boom', element: <Broken />, errorElement: <RouteError /> },
      ],
      { initialEntries: ['/boom'] },
    )

    render(<RouterProvider router={router} />)

    expect(await screen.findByRole('heading', { name: 'Something went wrong' })).toBeInTheDocument()
    expect(screen.getByText(/Nothing in your library was changed/)).toBeInTheDocument()
    expect(screen.queryByText(/a screen failed/)).toBeNull() // (no stack for the person)
    expect(screen.getByRole('link', { name: 'Back to the library' })).toHaveAttribute(
      'href',
      '/library',
    )
  })
})
