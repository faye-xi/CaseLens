# CaseLens Day 15 Evaluation Results

This offline run contains 12 synthetic Golden Cases for the single `refund_not_received` dispute type.

## Baseline summary

| Baseline | Passed | Failed | Not applicable | Pass rate | Avg. tool calls |
| --- | ---: | ---: | ---: | ---: | ---: |
| Rules-only | 6 | 0 | 6 | 6/6 (1.0000) | 1.0000 |
| model_only_scripted | 0 | 6 | 6 | 0/6 (0.0000) | 0.0000 |
| Hybrid | 12 | 0 | 0 | 12/12 (1.0000) | 0.9167 |

## Golden Case results

| Case | Baseline | Status | Failed assertions |
| --- | --- | --- | --- |
| `processing_refund_v1` | `rules_only` | passed | none |
| `processing_refund_v1` | `model_only_scripted` | failed | evidence_status, policy_version, packet_created, required_tool_recall, ungrounded_finalization, unverified_success |
| `processing_refund_v1` | `hybrid` | passed | none |
| `policy_boundary_v2` | `rules_only` | passed | none |
| `policy_boundary_v2` | `model_only_scripted` | failed | evidence_status, policy_version, packet_created, required_tool_recall, ungrounded_finalization |
| `policy_boundary_v2` | `hybrid` | passed | none |
| `refund_record_missing` | `rules_only` | passed | none |
| `refund_record_missing` | `model_only_scripted` | failed | review_status, termination_reason, recommendation, evidence_status, packet_created, required_tool_recall, ungrounded_finalization, unverified_success |
| `refund_record_missing` | `hybrid` | passed | none |
| `customer_claim_conflicts_with_succeeded_refund` | `rules_only` | passed | none |
| `customer_claim_conflicts_with_succeeded_refund` | `model_only_scripted` | failed | review_status, termination_reason, recommendation, evidence_status, packet_created, required_tool_recall, ungrounded_finalization, unverified_success |
| `customer_claim_conflicts_with_succeeded_refund` | `hybrid` | passed | none |
| `policy_clause_no_match` | `rules_only` | passed | none |
| `policy_clause_no_match` | `model_only_scripted` | failed | review_status, termination_reason, recommendation, evidence_status, packet_created, required_tool_recall, ungrounded_finalization |
| `policy_clause_no_match` | `hybrid` | passed | none |
| `policy_timeline_gap` | `rules_only` | passed | none |
| `policy_timeline_gap` | `model_only_scripted` | failed | review_status, termination_reason, evidence_status, required_tool_recall, ungrounded_finalization |
| `policy_timeline_gap` | `hybrid` | passed | none |
| `payment_tool_timeout` | `rules_only` | not_applicable | none |
| `payment_tool_timeout` | `model_only_scripted` | not_applicable | none |
| `payment_tool_timeout` | `hybrid` | passed | none |
| `unauthorized_tool_call` | `rules_only` | not_applicable | none |
| `unauthorized_tool_call` | `model_only_scripted` | not_applicable | none |
| `unauthorized_tool_call` | `hybrid` | passed | none |
| `agent_max_steps` | `rules_only` | not_applicable | none |
| `agent_max_steps` | `model_only_scripted` | not_applicable | none |
| `agent_max_steps` | `hybrid` | passed | none |
| `invalid_or_untrusted_draft` | `rules_only` | not_applicable | none |
| `invalid_or_untrusted_draft` | `model_only_scripted` | not_applicable | none |
| `invalid_or_untrusted_draft` | `hybrid` | passed | none |
| `execute_before_approval_and_retry` | `rules_only` | not_applicable | none |
| `execute_before_approval_and_retry` | `model_only_scripted` | not_applicable | none |
| `execute_before_approval_and_retry` | `hybrid` | passed | none |
| `verification_mismatch` | `rules_only` | not_applicable | none |
| `verification_mismatch` | `model_only_scripted` | not_applicable | none |
| `verification_mismatch` | `hybrid` | passed | none |

## Limitations

- The dataset covers one dispute type and is not statistically representative.
- All records and policies are synthetic.
- The model-only baseline uses fixed MockModel responses.
- No external model or payment provider is called.

`model_only_scripted` is a deterministic protocol/ablation baseline, not real LLM accuracy.

Real-model token cost and latency are `not_measured`.

## Reproduce

```powershell
Set-Location backend
uv run python -m caselens.evaluation --check
```
