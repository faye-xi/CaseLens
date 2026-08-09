import { AuditOutlined, SafetyCertificateOutlined } from '@ant-design/icons'
import { Button, ConfigProvider, Divider, Drawer, Input, Steps, Tag } from 'antd'
import { useState } from 'react'

import { useReviewWorkspace } from './hooks/useReviewWorkspace'
import { toDecisionSummary, toEvidenceRows, toTraceEvents, toWorkflowSteps } from './view-models'
import './styles.css'

function LegacyApp() {
  const workspace = useReviewWorkspace()
  const status = workspace.workflow?.status ?? 'not_started'

  return (
    <ConfigProvider
      theme={{
        token: {
          colorPrimary: '#0d8f87',
          colorText: '#152238',
          colorBgContainer: '#ffffff',
        },
      }}
    >
      <div className="workspace-shell">
        <header className="docket-header">
          <div className="brand-lockup" aria-label="CaseLens">
            <span className="brand-mark">
              <AuditOutlined />
            </span>
            <div>
              <strong>CASELENS</strong>
              <span>Auditable dispute review</span>
            </div>
          </div>

          <div className="run-overview">
            <div className="run-kicker">Live review workspace</div>
            <div className="run-title-row">
              <h1>Refund not received</h1>
              <Tag className="mode-tag">Local API</Tag>
            </div>
          </div>

          <div className="run-state">
            <div>
              <span>Workflow status</span>
              <strong>{status}</strong>
            </div>
          </div>
        </header>

        <main className="review-grid">
          <aside className="case-rail" aria-label="Case queue">
            <div className="section-heading"><span>Review queue</span><b>{workspace.cases.length}</b></div>
            <p className="section-intro">Cases available from the local demo API.</p>
            {workspace.cases.map((item) => <div className="case-ticket selected" key={item.case_id}><code>{item.case_id}</code><strong>{item.case_type.replaceAll('_', ' ')}</strong></div>)}
          </aside>
          <section className="evidence-board">
            <span className="eyebrow">Case dossier</span>
            <h2>{workspace.selectedCase?.case_id ?? 'Loading case'}</h2>
            {workspace.selectedCase && <div className="claim-callout"><span>Customer claim</span><blockquote>“{workspace.selectedCase.customer_statement}”</blockquote><p>Order: {workspace.selectedCase.order_id} · Payment: {workspace.selectedCase.payment_id}</p><p>Claim: {workspace.selectedCase.claim_amount} {workspace.selectedCase.currency}</p></div>}
            {workspace.error && <div role="alert" className="claim-callout">{workspace.error.message}</div>}
          </section>
          <aside className="decision-column"><section className="decision-card"><div className="decision-card-topline"><span><SafetyCertificateOutlined /> Resolution workflow</span></div><h2>{status.replaceAll('_', ' ')}</h2>{workspace.workflow === null ? <Button type="primary" onClick={() => void workspace.startReview()}>Start review</Button> : <><Input aria-label="Reviewer identity" value={workspace.reviewerId} onChange={(event) => workspace.setReviewerId(event.target.value)} placeholder="Reviewer identity" />{status === 'waiting_approval' && <Button type="primary" onClick={() => void workspace.approve()}>Approve workflow</Button>}{status === 'ready_to_execute' && <Button type="primary" onClick={() => void workspace.execute()}>Execute approved refund</Button>}{status === 'ready_to_verify' && <Button type="primary" onClick={() => void workspace.verify()}>Verify final state</Button>}</>}</section></aside>
        </main>
      </div>
    </ConfigProvider>
  )
}

void LegacyApp

function App() {
  const workspace = useReviewWorkspace()
  const [traceOpen, setTraceOpen] = useState(false)
  const status = workspace.workflow?.status ?? 'not_started'
  const reviewResult = workspace.review?.result
  const bundle = reviewResult?.evidence_bundle
  const decision = toDecisionSummary(reviewResult?.decision_packet)
  const evidenceRows = toEvidenceRows(bundle)
  const traceEvents = toTraceEvents(workspace.replay?.trace ?? {
    model_traces: [],
    tool_traces: [],
  })
  const steps = workspace.workflow ? toWorkflowSteps(workspace.workflow.status) : []

  return (
    <ConfigProvider theme={{ token: { colorPrimary: '#0d8f87', colorText: '#152238' } }}>
      <div className="workspace-shell">
        <header className="docket-header">
          <div className="brand-lockup" aria-label="CaseLens"><span className="brand-mark"><AuditOutlined /></span><div><strong>CASELENS</strong><span>Auditable dispute review</span></div></div>
          <div className="run-overview"><div className="run-kicker">Live review workspace</div><div className="run-title-row"><h1>Refund not received</h1><Tag className="mode-tag">Local API</Tag></div></div>
          <div className="run-state"><div><span>Workflow status</span><strong>{status}</strong></div></div>
        </header>

        <main className="review-grid">
          <aside className="case-rail" aria-label="Case queue">
            <div className="section-heading"><span>Review queue</span><b>{workspace.cases.length}</b></div>
            <p className="section-intro">Cases available from the local demo API.</p>
            {workspace.cases.map((item) => <div className="case-ticket selected" key={item.case_id}><code>{item.case_id}</code><strong>{item.case_type.replaceAll('_', ' ')}</strong></div>)}
          </aside>

          <section className="evidence-board">
            <span className="eyebrow">Case dossier</span><h2>{workspace.selectedCase?.case_id ?? 'Loading case'}</h2>
            {workspace.selectedCase && <div className="claim-callout"><span>Customer claim</span><blockquote>{workspace.selectedCase.customer_statement}</blockquote><p>Order: {workspace.selectedCase.order_id} · Payment: {workspace.selectedCase.payment_id}</p><p>Claim: {workspace.selectedCase.claim_amount} {workspace.selectedCase.currency}</p></div>}
            {workspace.isLoadingCases && <p>Loading the case queue…</p>}
            {reviewResult && <><Divider /><div className="evidence-summary"><span className="eyebrow">Trusted evidence</span><Tag color={bundle?.status === 'complete' ? 'green' : 'gold'}>{bundle?.status ?? reviewResult.status}</Tag>{evidenceRows.map((item) => <article className="evidence-row" key={item.id}><strong>{item.kind}</strong><span>{item.source}</span>{item.facts.map((fact) => <p key={fact}>{fact}</p>)}</article>)}{(bundle?.missing_evidence ?? []).map((item) => <p key={`${item.kind}-${item.reason}`}>Missing {item.kind.replaceAll('_', ' ')}: {item.reason}</p>)}{(bundle?.conflicts ?? []).map((item) => <p key={item.key}>Conflict: {item.key.replaceAll('_', ' ')}</p>)}</div></>}
            {workspace.error && <div role="alert" className="claim-callout">{workspace.error.message}</div>}
          </section>

          <aside className="decision-column"><section className="decision-card">
            <div className="decision-card-topline"><span><SafetyCertificateOutlined /> Decision packet</span></div>
            {decision ? <><h2>{decision.recommendation}</h2><p>{decision.rationale}</p><p>Risk: <Tag color={decision.riskLevel === 'high' ? 'red' : 'blue'}>{decision.riskLevel}</Tag></p><p>Policy: {decision.policyVersion}</p>{decision.citations.map((citation) => <blockquote className="policy-citation" key={citation.id}><strong>{citation.id}</strong>{citation.quote}</blockquote>)}</> : <p>Start a review to create a durable DecisionPacket.</p>}
            <Divider /><div className="decision-card-topline"><span>Resolution workflow</span><Button size="small" onClick={() => setTraceOpen(true)}>View trace</Button></div><h2>{status.replaceAll('_', ' ')}</h2>
            {workspace.workflow === null ? <Button type="primary" onClick={() => void workspace.startReview()}>Start review</Button> : <><Steps size="small" current={steps.findIndex((step) => step.state === 'current')} status={steps.some((step) => step.state === 'failed') ? 'error' : 'process'} items={steps.map((step) => ({ title: step.label, status: step.state === 'complete' ? 'finish' : step.state === 'failed' ? 'error' : step.state === 'pending' ? 'wait' : 'process' }))} /><Input aria-label="Reviewer identity" value={workspace.reviewerId} onChange={(event) => workspace.setReviewerId(event.target.value)} placeholder="Reviewer identity" />{status === 'waiting_approval' && <div className="workflow-actions"><Button type="primary" onClick={() => void workspace.approve()}>Approve workflow</Button><Button onClick={() => void workspace.reject()}>Reject workflow</Button></div>}{status === 'ready_to_execute' && <Button type="primary" onClick={() => void workspace.execute()}>Execute approved refund</Button>}{status === 'ready_to_verify' && <Button type="primary" onClick={() => void workspace.verify()}>Verify final state</Button>}</>}
          </section></aside>
        </main>
        <Drawer title="Auditable execution trace" open={traceOpen} onClose={() => setTraceOpen(false)}><p>Ordered model and tool calls from the durable replay record.</p>{traceEvents.length === 0 ? <p>No trace is available until a review finishes.</p> : traceEvents.map((event) => <article className="trace-event" key={`${event.kind}-${event.id}`}><Tag color={event.state === 'succeeded' ? 'green' : 'red'}>{event.kind}</Tag><strong>{event.title}</strong><p>{event.detail}</p><small>{event.startedAt} · {event.durationMs} ms</small></article>)}</Drawer>
      </div>
    </ConfigProvider>
  )
}

export default App
