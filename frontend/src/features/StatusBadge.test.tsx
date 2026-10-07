import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { StatusBadge } from './StatusBadge'
import { canCancel, canProcess, canRetry, isActive, statusLabel, statusTone } from './status'

describe('StatusBadge', () => {
  it.each([
    ['NOT_PROCESSED', 'Not processed', 'bg-muted'],
    ['PENDING', 'Queued', 'bg-blue-100'],
    ['RUNNING', 'Processing', 'bg-blue-100'],
    ['COMPLETED', 'Done', 'bg-green-100'],
    ['FAILED', 'Failed', 'bg-red-100'],
    ['NOT_RESUMABLE', 'Failed', 'bg-red-100'],
    ['INTERRUPTED', 'Interrupted', 'bg-red-100'],
    ['CANCELLED', 'Cancelled', 'bg-muted'],
  ])('shows %s as "%s" in its own colour', (state, label, colour) => {
    render(<StatusBadge state={state} />)

    expect(screen.getByText(label).className).toContain(colour)
  })

  it('shows a state it does not know as it is, in a neutral colour', () => {
    expect(statusLabel('SOMETHING_NEW')).toBe('SOMETHING_NEW')
    expect(statusTone('SOMETHING_NEW')).toBe('neutral')
  })
})

describe('what a person can do in each state', () => {
  it('can process what is idle or failed, never what is under way or done', () => {
    expect(['NOT_PROCESSED', 'CANCELLED', 'FAILED', 'INTERRUPTED'].every(canProcess)).toBe(true)
    expect(['PENDING', 'RUNNING', 'CANCELLING', 'FINALIZING', 'COMPLETED'].some(canProcess)).toBe(
      false,
    )
  })

  it('can cancel only what has not yet been made authoritative', () => {
    expect(['PENDING', 'RUNNING'].every(canCancel)).toBe(true)
    expect(['FINALIZING', 'CANCELLING', 'COMPLETED', 'FAILED', 'CANCELLED'].some(canCancel)).toBe(
      false,
    )
  })

  it('can retry only what ended without a result', () => {
    expect(['FAILED', 'INTERRUPTED', 'NOT_RESUMABLE'].every(canRetry)).toBe(true)
    expect(['PENDING', 'COMPLETED', 'CANCELLED', 'RUNNING'].some(canRetry)).toBe(false)
  })

  it('knows which states change by themselves', () => {
    expect(
      ['PENDING', 'RUNNING', 'PAUSING', 'PAUSED', 'CANCELLING', 'FINALIZING'].every(isActive),
    ).toBe(true)
    expect(['COMPLETED', 'FAILED', 'CANCELLED', 'NOT_PROCESSED'].some(isActive)).toBe(false)
  })
})
