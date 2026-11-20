import { describe, expect, it } from 'vitest'
import { formatReview } from './Study'

describe('formatReview', () => {
  const now = new Date('2026-11-20T09:00:00Z')

  it('says plainly when nothing is scheduled', () => {
    expect(formatReview(null, now)).toBe('—')
  })

  it('counts whole days ahead', () => {
    expect(formatReview('2026-11-20T15:00:00Z', now)).toBe('today')
    expect(formatReview('2026-11-21T09:00:00Z', now)).toBe('tomorrow')
    expect(formatReview('2026-11-26T09:00:00Z', now)).toBe('in 6 days')
  })

  it('treats an overdue date as today', () => {
    expect(formatReview('2026-11-10T09:00:00Z', now)).toBe('today')
  })
})
