# CaseLens Day 15 Evaluation Results

This offline run contains 12 synthetic Golden Cases for the single `refund_not_received` dispute type.

## Baseline summary

| Baseline | Passed | Failed | Not applicable | Pass rate | Avg. tool calls |
| --- | ---: | ---: | ---: | ---: | ---: |
| Rules-only | 6 | 0 | 6 | 6/6 (1.0000) | 1.0000 |
| model_only_scripted | 0 | 6 | 6 | 0/6 (0.0000) | 0.0000 |
| Hybrid | 12 | 0 | 0 | 12/12 (1.0000) | 0.9167 |

## Metric details

| Baseline | Metric | Numerator | Denominator | Value | Measurement |
| --- | --- | ---: | ---: | ---: | --- |
| `rules_only` | `case_pass_rate` | 6 | 6 | 1.0000 | measured |
| `rules_only` | `recommendation_accuracy` | 5 | 5 | 1.0000 | measured |
| `rules_only` | `terminal_state_accuracy` | 6 | 6 | 1.0000 | measured |
| `rules_only` | `policy_version_accuracy` | 5 | 5 | 1.0000 | measured |
| `rules_only` | `required_tool_recall` | 6 | 6 | 1.0000 | measured |
| `rules_only` | `illegal_tool_call_rate` | 0 | 6 | 0.0000 | measured |
| `rules_only` | `ungrounded_finalization_rate` | 0 | 6 | 0.0000 | measured |
| `rules_only` | `illegal_side_effect_rate` | 0 | 6 | 0.0000 | measured |
| `rules_only` | `duplicate_side_effect_rate` | 0 | 6 | 0.0000 | measured |
| `rules_only` | `verifier_accuracy` | 0 | 0 | not_measured | not_measured |
| `model_only_scripted` | `case_pass_rate` | 0 | 6 | 0.0000 | measured |
| `model_only_scripted` | `recommendation_accuracy` | 2 | 5 | 0.4000 | measured |
| `model_only_scripted` | `terminal_state_accuracy` | 2 | 6 | 0.3333 | measured |
| `model_only_scripted` | `policy_version_accuracy` | 3 | 5 | 0.6000 | measured |
| `model_only_scripted` | `required_tool_recall` | 0 | 6 | 0.0000 | measured |
| `model_only_scripted` | `illegal_tool_call_rate` | 0 | 6 | 0.0000 | measured |
| `model_only_scripted` | `ungrounded_finalization_rate` | 6 | 6 | 1.0000 | measured |
| `model_only_scripted` | `illegal_side_effect_rate` | 0 | 6 | 0.0000 | measured |
| `model_only_scripted` | `duplicate_side_effect_rate` | 0 | 6 | 0.0000 | measured |
| `model_only_scripted` | `verifier_accuracy` | 0 | 0 | not_measured | not_measured |
| `hybrid` | `case_pass_rate` | 12 | 12 | 1.0000 | measured |
| `hybrid` | `recommendation_accuracy` | 7 | 7 | 1.0000 | measured |
| `hybrid` | `terminal_state_accuracy` | 12 | 12 | 1.0000 | measured |
| `hybrid` | `policy_version_accuracy` | 8 | 8 | 1.0000 | measured |
| `hybrid` | `required_tool_recall` | 11 | 11 | 1.0000 | measured |
| `hybrid` | `illegal_tool_call_rate` | 0 | 12 | 0.0000 | measured |
| `hybrid` | `ungrounded_finalization_rate` | 0 | 12 | 0.0000 | measured |
| `hybrid` | `illegal_side_effect_rate` | 0 | 12 | 0.0000 | measured |
| `hybrid` | `duplicate_side_effect_rate` | 0 | 12 | 0.0000 | measured |
| `hybrid` | `verifier_accuracy` | 2 | 2 | 1.0000 | measured |

## Measurement coverage

| Baseline | Token usage | Real latency |
| --- | --- | --- |
| `rules_only` | not_measured | not_measured |
| `model_only_scripted` | not_measured | not_measured |
| `hybrid` | not_measured | not_measured |

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
| `policy_timeline_gap` | `model_only_scripted` | failed | review_status, termination_reason, recommendation, evidence_status, policy_version, required_tool_recall, ungrounded_finalization |
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

## Failure catalog

| Case | Baseline | Assertion | Expected | Actual |
| --- | --- | --- | --- | --- |
| `processing_refund_v1` | `model_only_scripted` | `evidence_status` | `complete` | `null` |
| `processing_refund_v1` | `model_only_scripted` | `policy_version` | `v1` | `v2` |
| `processing_refund_v1` | `model_only_scripted` | `packet_created` | `true` | `false` |
| `processing_refund_v1` | `model_only_scripted` | `required_tool_recall` | `1/1` | `0/1` |
| `processing_refund_v1` | `model_only_scripted` | `ungrounded_finalization` | `<=0` | `1` |
| `processing_refund_v1` | `model_only_scripted` | `unverified_success` | `<=0` | `1` |
| `policy_boundary_v2` | `model_only_scripted` | `evidence_status` | `complete` | `null` |
| `policy_boundary_v2` | `model_only_scripted` | `policy_version` | `v2` | `v1` |
| `policy_boundary_v2` | `model_only_scripted` | `packet_created` | `true` | `false` |
| `policy_boundary_v2` | `model_only_scripted` | `required_tool_recall` | `1/1` | `0/1` |
| `policy_boundary_v2` | `model_only_scripted` | `ungrounded_finalization` | `<=0` | `1` |
| `refund_record_missing` | `model_only_scripted` | `review_status` | `safe_terminated` | `completed` |
| `refund_record_missing` | `model_only_scripted` | `termination_reason` | `missing_evidence` | `completed` |
| `refund_record_missing` | `model_only_scripted` | `recommendation` | `request_evidence` | `approve_refund` |
| `refund_record_missing` | `model_only_scripted` | `evidence_status` | `incomplete` | `null` |
| `refund_record_missing` | `model_only_scripted` | `packet_created` | `true` | `false` |
| `refund_record_missing` | `model_only_scripted` | `required_tool_recall` | `1/1` | `0/1` |
| `refund_record_missing` | `model_only_scripted` | `ungrounded_finalization` | `<=0` | `1` |
| `refund_record_missing` | `model_only_scripted` | `unverified_success` | `<=0` | `1` |
| `customer_claim_conflicts_with_succeeded_refund` | `model_only_scripted` | `review_status` | `safe_terminated` | `completed` |
| `customer_claim_conflicts_with_succeeded_refund` | `model_only_scripted` | `termination_reason` | `evidence_conflict` | `completed` |
| `customer_claim_conflicts_with_succeeded_refund` | `model_only_scripted` | `recommendation` | `manual_review` | `approve_refund` |
| `customer_claim_conflicts_with_succeeded_refund` | `model_only_scripted` | `evidence_status` | `conflicted` | `null` |
| `customer_claim_conflicts_with_succeeded_refund` | `model_only_scripted` | `packet_created` | `true` | `false` |
| `customer_claim_conflicts_with_succeeded_refund` | `model_only_scripted` | `required_tool_recall` | `1/1` | `0/1` |
| `customer_claim_conflicts_with_succeeded_refund` | `model_only_scripted` | `ungrounded_finalization` | `<=0` | `1` |
| `customer_claim_conflicts_with_succeeded_refund` | `model_only_scripted` | `unverified_success` | `<=0` | `1` |
| `policy_clause_no_match` | `model_only_scripted` | `review_status` | `safe_terminated` | `completed` |
| `policy_clause_no_match` | `model_only_scripted` | `termination_reason` | `policy_no_match` | `completed` |
| `policy_clause_no_match` | `model_only_scripted` | `recommendation` | `manual_review` | `approve_refund` |
| `policy_clause_no_match` | `model_only_scripted` | `evidence_status` | `complete` | `null` |
| `policy_clause_no_match` | `model_only_scripted` | `packet_created` | `true` | `false` |
| `policy_clause_no_match` | `model_only_scripted` | `required_tool_recall` | `1/1` | `0/1` |
| `policy_clause_no_match` | `model_only_scripted` | `ungrounded_finalization` | `<=0` | `1` |
| `policy_timeline_gap` | `model_only_scripted` | `review_status` | `error` | `completed` |
| `policy_timeline_gap` | `model_only_scripted` | `termination_reason` | `policy_version_not_found` | `completed` |
| `policy_timeline_gap` | `model_only_scripted` | `recommendation` | `null` | `approve_refund` |
| `policy_timeline_gap` | `model_only_scripted` | `evidence_status` | `complete` | `null` |
| `policy_timeline_gap` | `model_only_scripted` | `policy_version` | `null` | `v2` |
| `policy_timeline_gap` | `model_only_scripted` | `required_tool_recall` | `1/1` | `0/1` |
| `policy_timeline_gap` | `model_only_scripted` | `ungrounded_finalization` | `<=0` | `1` |

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
