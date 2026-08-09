import type {
  ApiCase,
  ApiErrorPayload,
  ApprovalCommand,
  ResolutionRun,
  ReviewStartResult,
  StartReviewCommand,
  WorkflowReplay,
} from './types'

export class ApiRequestError extends Error {
  readonly status: number
  readonly code: string

  constructor(status: number, code: string, message: string) {
    super(message)
    this.name = 'ApiRequestError'
    this.status = status
    this.code = code
  }
}

function post(body?: unknown): RequestInit {
  return {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(path, init)
  } catch {
    throw new ApiRequestError(
      0,
      'network_error',
      'The request could not reach the local API.',
    )
  }

  const payload: unknown = await response.json().catch(() => null)
  if (!response.ok) {
    const error = errorPayload(payload)
    throw new ApiRequestError(
      response.status,
      error?.code ?? 'unexpected_response',
      error?.message ?? 'The API returned an unexpected error response.',
    )
  }

  return payload as T
}

function errorPayload(payload: unknown): ApiErrorPayload['error'] | null {
  if (
    typeof payload !== 'object' ||
    payload === null ||
    !('error' in payload) ||
    typeof payload.error !== 'object' ||
    payload.error === null ||
    !('code' in payload.error) ||
    !('message' in payload.error) ||
    typeof payload.error.code !== 'string' ||
    typeof payload.error.message !== 'string'
  ) {
    return null
  }
  return payload.error as ApiErrorPayload['error']
}

export const api = {
  listCases: (): Promise<ApiCase[]> => request('/api/v1/cases'),
  startReview: (
    caseId: string,
    command: StartReviewCommand,
  ): Promise<ReviewStartResult> =>
    request(
      `/api/v1/cases/${encodeURIComponent(caseId)}/reviews`,
      post({
        review_id: command.reviewId,
        workflow_id: command.workflowId,
      }),
    ),
  getReplay: (workflowId: string): Promise<WorkflowReplay> =>
    request(`/api/v1/workflows/${encodeURIComponent(workflowId)}/replay`),
  decideApproval: (
    workflowId: string,
    command: ApprovalCommand,
  ): Promise<ResolutionRun> =>
    request(
      `/api/v1/workflows/${encodeURIComponent(workflowId)}/approval`,
      post({ decision: command.decision, decided_by: command.decidedBy }),
    ),
  executeAction: (workflowId: string): Promise<ResolutionRun> =>
    request(
      `/api/v1/workflows/${encodeURIComponent(workflowId)}/execute`,
      post(),
    ),
  verifyAction: (workflowId: string): Promise<ResolutionRun> =>
    request(
      `/api/v1/workflows/${encodeURIComponent(workflowId)}/verify`,
      post(),
    ),
}
