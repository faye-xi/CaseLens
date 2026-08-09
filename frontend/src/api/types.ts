export type ResolutionStatus =
  | 'waiting_approval'
  | 'approval_rejected'
  | 'ready_to_execute'
  | 'execution_failed'
  | 'ready_to_verify'
  | 'completed_verified'
  | 'verification_failed'
  | 'completed_no_action'

export interface ApiCase {
  case_id: string
  case_type: 'refund_not_received'
  occurred_at: string
  customer_statement: string
  claim_amount: string
  currency: string
  order_id: string
  payment_id: string
  refund_id: string | null
}

export interface StartReviewCommand {
  reviewId: string
  workflowId: string
}

export interface ApprovalCommand {
  decision: 'approved' | 'rejected'
  decidedBy: string
}

export interface StoredCaseReview {
  review_id: string
  case_id: string
  created_at: string
  result: CaseReviewResult
}

export interface CaseReviewResult {
  status: string
  termination_reason: string
  evidence_bundle: EvidenceBundle | null
  decision_packet: DecisionPacket | null
}

export interface EvidenceBundle {
  case_id: string
  evidence: Evidence[]
  missing_evidence: MissingEvidence[]
  conflicts: EvidenceConflict[]
  status: 'complete' | 'incomplete' | 'conflicted'
}

export interface Evidence {
  evidence_id: string
  kind: string
  source_record_id: string
  collected_at: string
  facts: EvidenceFact[]
}

export interface EvidenceFact {
  fact_id: string
  key: string
  value: string | boolean | number
}

export interface MissingEvidence {
  kind: string
  reason: string
}

export interface FactReference {
  evidence_id: string
  fact_id: string
}

export interface EvidenceConflict {
  key: string
  left: FactReference
  right: FactReference
}

export interface DecisionPacket {
  case_id: string
  recommendation: string
  rationale: string
  risk_level: string
  requires_approval: boolean
  evidence_status: 'complete' | 'incomplete' | 'conflicted'
  evidence_references: FactReference[]
  missing_evidence: MissingEvidence[]
  evidence_conflicts: EvidenceConflict[]
  selected_policy_version: PolicyVersion
  policy_citations: PolicyCitation[]
}

export interface PolicyVersion {
  policy_id: string
  version: string
  effective_from: string
  effective_to: string | null
}

export interface PolicyCitation extends PolicyVersion {
  clause_id: string
  quote: string
  score: number
}

export interface ResolutionRun {
  workflow_id: string
  review_id: string
  case_id: string
  status: ResolutionStatus
  updated_at: string
  [key: string]: unknown
}

export interface ReviewStartResult {
  created: boolean
  review: StoredCaseReview
  workflow: ResolutionRun | null
}

export interface WorkflowReplay {
  case: ApiCase
  review: StoredCaseReview
  resolution: ResolutionRun
  trace: ReplayTrace
}

export interface ModelTrace {
  request_id: string
  implementation: string
  started_at: string
  completed_at: string
  duration_ms: number
  status: 'succeeded' | 'failed'
  error_code?: string | null
}

export interface ToolTrace {
  call_id: string
  tool_name: string
  started_at: string
  completed_at: string
  duration_ms: number
  status: 'succeeded' | 'failed'
  error_code?: string | null
}

export interface ReplayTrace {
  model_traces: ModelTrace[]
  tool_traces: ToolTrace[]
}

export interface ApiErrorPayload {
  error: {
    code: string
    message: string
  }
}
