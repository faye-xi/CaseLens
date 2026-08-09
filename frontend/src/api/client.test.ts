import { afterEach, describe, expect, it, vi } from 'vitest'

import { api, ApiRequestError } from './client'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('CaseLens API client', () => {
  it('starts a review with caller-owned identifiers', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        created: true,
        review: { review_id: 'review-1' },
        workflow: { workflow_id: 'workflow-1', status: 'waiting_approval' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    await api.startReview('CASE-DEMO-001', {
      reviewId: 'review-1',
      workflowId: 'workflow-1',
    })

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/cases/CASE-DEMO-001/reviews',
      expect.objectContaining({
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          review_id: 'review-1',
          workflow_id: 'workflow-1',
        }),
      }),
    )
  })

  it('exposes the stable API error envelope', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse(
          {
            error: {
              code: 'illegal_transition',
              message: 'The operation is not legal from the current workflow state.',
            },
          },
          409,
        ),
      ),
    )

    const request = api.executeAction('workflow-1')

    await expect(request).rejects.toBeInstanceOf(ApiRequestError)
    await expect(request).rejects.toMatchObject({
      status: 409,
      code: 'illegal_transition',
      message: 'The operation is not legal from the current workflow state.',
    })
  })
})
