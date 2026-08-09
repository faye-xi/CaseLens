import { useEffect, useRef, useState } from 'react'

import { api, ApiRequestError } from '../api/client'
import type {
  ApiCase,
  ResolutionRun,
  StoredCaseReview,
  WorkflowReplay,
} from '../api/types'

export interface ReviewWorkspace {
  cases: readonly ApiCase[]
  selectedCase: ApiCase | null
  review: StoredCaseReview | null
  replay: WorkflowReplay | null
  workflow: ResolutionRun | null
  reviewerId: string
  isLoadingCases: boolean
  error: ApiRequestError | null
  setReviewerId: (value: string) => void
  startReview: () => Promise<void>
  approve: () => Promise<void>
  reject: () => Promise<void>
  execute: () => Promise<void>
  verify: () => Promise<void>
}

export function useReviewWorkspace(): ReviewWorkspace {
  const [cases, setCases] = useState<readonly ApiCase[]>([])
  const [selectedCase, setSelectedCase] = useState<ApiCase | null>(null)
  const [review, setReview] = useState<StoredCaseReview | null>(null)
  const [replay, setReplay] = useState<WorkflowReplay | null>(null)
  const [workflow, setWorkflow] = useState<ResolutionRun | null>(null)
  const [reviewerId, setReviewerId] = useState('')
  const [isLoadingCases, setIsLoadingCases] = useState(true)
  const [error, setError] = useState<ApiRequestError | null>(null)
  const startCommand = useRef<{
    caseId: string
    reviewId: string
    workflowId: string
  } | null>(null)

  useEffect(() => {
    let active = true

    void api
      .listCases()
      .then((loadedCases) => {
        if (!active) return
        setCases(loadedCases)
        setSelectedCase(loadedCases[0] ?? null)
      })
      .catch((requestError: unknown) => {
        if (active && requestError instanceof ApiRequestError) {
          setError(requestError)
        }
      })
      .finally(() => {
        if (active) setIsLoadingCases(false)
      })

    return () => {
      active = false
    }
  }, [])

  async function decideApproval(decision: 'approved' | 'rejected'): Promise<void> {
    if (!reviewerId.trim()) {
      setError(
        new ApiRequestError(
          422,
          'invalid_reviewer',
          'Enter a reviewer identity before approving a workflow.',
        ),
      )
      return
    }

    if (workflow === null) return
    try {
      setError(null)
      setWorkflow(
        await api.decideApproval(workflow.workflow_id, {
          decision,
          decidedBy: reviewerId.trim(),
        }),
      )
    } catch (requestError) {
      if (requestError instanceof ApiRequestError) setError(requestError)
    }
  }

  async function approve(): Promise<void> {
    await decideApproval('approved')
  }

  async function reject(): Promise<void> {
    await decideApproval('rejected')
  }

  async function startReview(): Promise<void> {
    if (selectedCase === null) return

    if (startCommand.current?.caseId !== selectedCase.case_id) {
      startCommand.current = {
        caseId: selectedCase.case_id,
        reviewId: crypto.randomUUID(),
        workflowId: crypto.randomUUID(),
      }
    }

    const command = startCommand.current
    try {
      setError(null)
      const result = await api.startReview(selectedCase.case_id, command)
      setReview(result.review)
      setWorkflow(result.workflow)
      if (result.workflow !== null) {
        const nextReplay = await api.getReplay(result.workflow.workflow_id)
        setReplay(nextReplay)
        setReview(nextReplay.review)
        setWorkflow(nextReplay.resolution)
      }
    } catch (requestError) {
      if (requestError instanceof ApiRequestError) setError(requestError)
    }
  }

  async function execute(): Promise<void> {
    if (workflow?.status !== 'ready_to_execute') return
    try {
      setError(null)
      setWorkflow(await api.executeAction(workflow.workflow_id))
    } catch (requestError) {
      if (requestError instanceof ApiRequestError) setError(requestError)
    }
  }

  async function verify(): Promise<void> {
    if (workflow?.status !== 'ready_to_verify') return
    try {
      setError(null)
      setWorkflow(await api.verifyAction(workflow.workflow_id))
    } catch (requestError) {
      if (requestError instanceof ApiRequestError) setError(requestError)
    }
  }

  return {
    cases,
    selectedCase,
    review,
    replay,
    workflow,
    reviewerId,
    isLoadingCases,
    error,
    setReviewerId,
    startReview,
    approve,
    reject,
    execute,
    verify,
  }
}
