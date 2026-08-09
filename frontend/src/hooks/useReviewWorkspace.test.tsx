import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const { apiMock } = vi.hoisted(() => ({
  apiMock: {
  listCases: vi.fn(),
  startReview: vi.fn(),
  getReplay: vi.fn(),
  decideApproval: vi.fn(),
  executeAction: vi.fn(),
  verifyAction: vi.fn(),
  },
}))

vi.mock('../api/client', () => ({
  api: apiMock,
  ApiRequestError: class ApiRequestError extends Error {
    readonly status: number
    readonly code: string

    constructor(status: number, code: string, message: string) {
      super(message)
      this.status = status
      this.code = code
    }
  },
}))

import { useReviewWorkspace } from './useReviewWorkspace'

const caseItem = {
  case_id: 'CASE-DEMO-001',
  case_type: 'refund_not_received' as const,
  occurred_at: '2026-08-04T10:00:00Z',
  customer_statement: 'My refund has not arrived.',
  claim_amount: '12.50',
  currency: 'CNY',
  order_id: 'ORDER-001',
  payment_id: 'PAYMENT-001',
  refund_id: 'REFUND-001',
}

beforeEach(() => {
  vi.clearAllMocks()
  apiMock.listCases.mockResolvedValue([caseItem])
})

describe('useReviewWorkspace', () => {
  it('loads and selects the first API case', async () => {
    const { result } = renderHook(() => useReviewWorkspace())

    await waitFor(() => expect(result.current.isLoadingCases).toBe(false))

    expect(result.current.selectedCase?.case_id).toBe('CASE-DEMO-001')
  })

  it('does not approve a workflow without a reviewer identity', async () => {
    const { result } = renderHook(() => useReviewWorkspace())

    await waitFor(() => expect(result.current.selectedCase).not.toBeNull())
    await act(async () => result.current.approve())

    expect(apiMock.decideApproval).not.toHaveBeenCalled()
    expect(result.current.error).toMatchObject({ code: 'invalid_reviewer' })
  })

  it('starts a review then refreshes its durable replay', async () => {
    apiMock.startReview.mockResolvedValue({
      created: true,
      review: { review_id: 'review-1', case_id: 'CASE-DEMO-001' },
      workflow: {
        workflow_id: 'workflow-1',
        review_id: 'review-1',
        case_id: 'CASE-DEMO-001',
        status: 'waiting_approval',
        updated_at: '2026-08-04T10:00:00Z',
      },
    })
    apiMock.getReplay.mockResolvedValue({
      case: caseItem,
      review: { review_id: 'review-1', case_id: 'CASE-DEMO-001' },
      resolution: {
        workflow_id: 'workflow-1',
        review_id: 'review-1',
        case_id: 'CASE-DEMO-001',
        status: 'waiting_approval',
        updated_at: '2026-08-04T10:00:00Z',
      },
      trace: { model_traces: [], tool_traces: [] },
    })
    const { result } = renderHook(() => useReviewWorkspace())

    await waitFor(() => expect(result.current.selectedCase).not.toBeNull())
    await act(async () => result.current.startReview())

    expect(apiMock.startReview).toHaveBeenCalledWith(
      'CASE-DEMO-001',
      expect.objectContaining({ reviewId: expect.any(String), workflowId: expect.any(String) }),
    )
    expect(apiMock.getReplay).toHaveBeenCalledWith('workflow-1')
    expect(result.current.workflow?.status).toBe('waiting_approval')
  })

  it('only exposes an executable workflow after the API confirms approval', async () => {
    apiMock.startReview.mockResolvedValue({
      created: true,
      review: { review_id: 'review-1', case_id: 'CASE-DEMO-001' },
      workflow: {
        workflow_id: 'workflow-1',
        review_id: 'review-1',
        case_id: 'CASE-DEMO-001',
        status: 'waiting_approval',
        updated_at: '2026-08-04T10:00:00Z',
      },
    })
    apiMock.getReplay.mockResolvedValue({
      case: caseItem,
      review: { review_id: 'review-1', case_id: 'CASE-DEMO-001' },
      resolution: {
        workflow_id: 'workflow-1',
        review_id: 'review-1',
        case_id: 'CASE-DEMO-001',
        status: 'waiting_approval',
        updated_at: '2026-08-04T10:00:00Z',
      },
      trace: { model_traces: [], tool_traces: [] },
    })
    apiMock.decideApproval.mockResolvedValue({
      workflow_id: 'workflow-1',
      review_id: 'review-1',
      case_id: 'CASE-DEMO-001',
      status: 'ready_to_execute',
      updated_at: '2026-08-04T10:01:00Z',
    })
    const { result } = renderHook(() => useReviewWorkspace())

    await waitFor(() => expect(result.current.selectedCase).not.toBeNull())
    await act(async () => result.current.startReview())
    act(() => result.current.setReviewerId('demo-reviewer'))
    await act(async () => result.current.approve())

    expect(apiMock.decideApproval).toHaveBeenCalledWith('workflow-1', {
      decision: 'approved',
      decidedBy: 'demo-reviewer',
    })
    expect(result.current.workflow?.status).toBe('ready_to_execute')
  })

  it('keeps execution separate from verified completion', async () => {
    apiMock.startReview.mockResolvedValue({
      created: true,
      review: { review_id: 'review-1', case_id: 'CASE-DEMO-001' },
      workflow: {
        workflow_id: 'workflow-1', review_id: 'review-1', case_id: 'CASE-DEMO-001',
        status: 'waiting_approval', updated_at: '2026-08-04T10:00:00Z',
      },
    })
    apiMock.getReplay.mockResolvedValue({
      case: caseItem, review: { review_id: 'review-1', case_id: 'CASE-DEMO-001' },
      resolution: {
        workflow_id: 'workflow-1', review_id: 'review-1', case_id: 'CASE-DEMO-001',
        status: 'waiting_approval', updated_at: '2026-08-04T10:00:00Z',
      }, trace: { model_traces: [], tool_traces: [] },
    })
    apiMock.decideApproval.mockResolvedValue({
      workflow_id: 'workflow-1', review_id: 'review-1', case_id: 'CASE-DEMO-001',
      status: 'ready_to_execute', updated_at: '2026-08-04T10:01:00Z',
    })
    apiMock.executeAction.mockResolvedValue({
      workflow_id: 'workflow-1', review_id: 'review-1', case_id: 'CASE-DEMO-001',
      status: 'ready_to_verify', updated_at: '2026-08-04T10:02:00Z',
    })
    apiMock.verifyAction.mockResolvedValue({
      workflow_id: 'workflow-1', review_id: 'review-1', case_id: 'CASE-DEMO-001',
      status: 'completed_verified', updated_at: '2026-08-04T10:03:00Z',
    })
    const { result } = renderHook(() => useReviewWorkspace())

    await waitFor(() => expect(result.current.selectedCase).not.toBeNull())
    await act(async () => result.current.startReview())
    act(() => result.current.setReviewerId('demo-reviewer'))
    await act(async () => result.current.approve())
    await act(async () => result.current.execute())
    expect(result.current.workflow?.status).toBe('ready_to_verify')
    await act(async () => result.current.verify())
    expect(result.current.workflow?.status).toBe('completed_verified')
  })
})
