import type {
  DecisionPacket,
  EvidenceBundle,
  ReplayTrace,
  ResolutionStatus,
} from './api/types'

export interface WorkflowStep {
  key: 'review' | 'approval' | 'action' | 'verification'
  label: string
  state: 'complete' | 'current' | 'pending' | 'failed'
}

export interface TraceEvent {
  id: string
  kind: 'model' | 'tool'
  title: string
  detail: string
  startedAt: string
  durationMs: number
  state: 'succeeded' | 'failed'
}

export interface EvidenceRow {
  id: string
  kind: string
  source: string
  facts: string[]
}

export interface DecisionSummary {
  recommendation: string
  rationale: string
  riskLevel: string
  requiresApproval: boolean
  policyVersion: string
  citations: { id: string; quote: string }[]
}

const workflowStepKeys: WorkflowStep['key'][] = [
  'review',
  'approval',
  'action',
  'verification',
]

const workflowLabels: Record<WorkflowStep['key'], string> = {
  review: 'Review',
  approval: 'Approval',
  action: 'Action',
  verification: 'Verification',
}

export function toWorkflowSteps(status: ResolutionStatus): WorkflowStep[] {
  const currentIndex = {
    waiting_approval: 1,
    approval_rejected: 1,
    ready_to_execute: 2,
    execution_failed: 2,
    ready_to_verify: 3,
    completed_verified: 4,
    verification_failed: 3,
    completed_no_action: 4,
  }[status]

  const failedIndices: Partial<Record<ResolutionStatus, number>> = {
    approval_rejected: 1,
    execution_failed: 2,
    verification_failed: 3,
  }
  const failedIndex = failedIndices[status]

  return workflowStepKeys.map((key, index) => ({
    key,
    label: workflowLabels[key],
    state:
      index === failedIndex
        ? 'failed'
        : index < currentIndex
          ? 'complete'
          : index === currentIndex
            ? 'current'
            : 'pending',
  }))
}

export function toTraceEvents(trace: ReplayTrace): TraceEvent[] {
  return [
    ...trace.model_traces.map((item) => ({
      id: item.request_id,
      kind: 'model' as const,
      title: item.implementation,
      detail: item.error_code ?? 'Model response recorded.',
      startedAt: item.started_at,
      durationMs: item.duration_ms,
      state: item.status,
    })),
    ...trace.tool_traces.map((item) => ({
      id: item.call_id,
      kind: 'tool' as const,
      title: item.tool_name,
      detail: item.error_code ?? 'Read-only tool result recorded.',
      startedAt: item.started_at,
      durationMs: item.duration_ms,
      state: item.status,
    })),
  ].sort(
    (left, right) =>
      left.startedAt.localeCompare(right.startedAt) || left.id.localeCompare(right.id),
  )
}

export function toEvidenceRows(bundle: EvidenceBundle | null | undefined): EvidenceRow[] {
  return (bundle?.evidence ?? []).map((item) => ({
    id: item.evidence_id,
    kind: item.kind.replaceAll('_', ' '),
    source: item.source_record_id,
    facts: item.facts.map((fact) => `${fact.key.replaceAll('_', ' ')}: ${String(fact.value)}`),
  }))
}

export function toDecisionSummary(
  packet: DecisionPacket | null | undefined,
): DecisionSummary | null {
  if (packet === null || packet === undefined) return null

  return {
    recommendation: packet.recommendation.replaceAll('_', ' '),
    rationale: packet.rationale,
    riskLevel: packet.risk_level,
    requiresApproval: packet.requires_approval,
    policyVersion: `${packet.selected_policy_version.policy_id} ${packet.selected_policy_version.version}`,
    citations: packet.policy_citations.map((citation) => ({
      id: citation.clause_id,
      quote: citation.quote,
    })),
  }
}
