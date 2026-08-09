import { describe, expect, it } from 'vitest'

import {
  toDecisionSummary,
  toEvidenceRows,
  toTraceEvents,
  toWorkflowSteps,
} from './view-models'

describe('review workspace view models', () => {
  it('does not mark verification complete before the verifier succeeds', () => {
    expect(toWorkflowSteps('ready_to_verify')[3]).toMatchObject({
      key: 'verification',
      state: 'current',
    })
    expect(toWorkflowSteps('completed_verified')[3]).toMatchObject({
      key: 'verification',
      state: 'complete',
    })
  })

  it('orders model and tool trace records by started time', () => {
    const events = toTraceEvents({
      model_traces: [
        {
          request_id: 'model-later',
          implementation: 'MockModel',
          started_at: '2026-08-04T10:00:03Z',
          completed_at: '2026-08-04T10:00:04Z',
          duration_ms: 1000,
          status: 'succeeded',
        },
      ],
      tool_traces: [
        {
          call_id: 'tool-first',
          tool_name: 'get_payment',
          started_at: '2026-08-04T10:00:01Z',
          completed_at: '2026-08-04T10:00:02Z',
          duration_ms: 1000,
          status: 'succeeded',
        },
      ],
    })

    expect(events.map((event) => event.id)).toEqual([
      'tool-first',
      'model-later',
    ])
  })

  it('renders audit evidence and policy text without inventing a confidence score', () => {
    expect(toEvidenceRows({
      case_id: 'CASE-1',
      status: 'complete',
      missing_evidence: [],
      conflicts: [],
      evidence: [{
        evidence_id: 'evidence-1',
        kind: 'refund_record',
        source_record_id: 'REFUND-1',
        collected_at: '2026-08-04T10:00:00Z',
        facts: [{ fact_id: 'fact-1', key: 'refund_received', value: false }],
      }],
    })).toEqual([{
      id: 'evidence-1',
      kind: 'refund record',
      source: 'REFUND-1',
      facts: ['refund received: false'],
    }])

    expect(toDecisionSummary({
      case_id: 'CASE-1',
      recommendation: 'approve_refund',
      rationale: 'The refund has not been received.',
      risk_level: 'high',
      requires_approval: true,
      evidence_status: 'complete',
      evidence_references: [],
      missing_evidence: [],
      evidence_conflicts: [],
      selected_policy_version: {
        policy_id: 'refund-policy', version: '2026-08', effective_from: '2026-08-01T00:00:00Z', effective_to: null,
      },
      policy_citations: [{
        clause_id: 'refund-2.1', policy_id: 'refund-policy', version: '2026-08', effective_from: '2026-08-01T00:00:00Z', effective_to: null, quote: 'Issue a refund when it is not received.', score: 1,
      }],
    })).toMatchObject({
      recommendation: 'approve refund',
      policyVersion: 'refund-policy 2026-08',
      citations: [{ id: 'refund-2.1' }],
    })
  })
})
