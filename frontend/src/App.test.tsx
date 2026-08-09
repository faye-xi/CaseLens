import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

const startReview = vi.fn()

vi.mock('./hooks/useReviewWorkspace', () => ({
  useReviewWorkspace: () => ({
    cases: [{ case_id: 'CASE-DEMO-001', case_type: 'refund_not_received' }],
    selectedCase: {
      case_id: 'CASE-DEMO-001',
      case_type: 'refund_not_received',
      occurred_at: '2026-08-04T10:00:00Z',
      customer_statement: 'My refund has not arrived.',
      claim_amount: '12.50', currency: 'CNY', order_id: 'ORDER-001',
      payment_id: 'PAYMENT-001', refund_id: 'REFUND-001',
    },
    review: null, replay: null, workflow: null, reviewerId: '',
    isLoadingCases: false, error: null, setReviewerId: vi.fn(),
    startReview, approve: vi.fn(), execute: vi.fn(), verify: vi.fn(),
  }),
}))

import App from './App'

describe('CaseLens review workspace', () => {
  it('shows a real API case and starts its review', () => {
    render(<App />)

    expect(screen.getAllByText('CASE-DEMO-001')).not.toHaveLength(0)
    fireEvent.click(screen.getByRole('button', { name: 'Start review' }))
    expect(startReview).toHaveBeenCalledOnce()
  })
})
