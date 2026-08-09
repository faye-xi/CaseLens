import warnings
from pathlib import Path

import pytest

from caselens.evaluation.baselines import HybridBaseline
from caselens.evaluation.dataset import load_golden_cases

DATASET = Path(__file__).parents[1] / "evals" / "golden_cases.json"
CASES = {case.case_id: case for case in load_golden_cases(DATASET)}


@pytest.mark.parametrize(
    ("case_id", "status", "termination", "recommendation", "policy"),
    [
        ("processing_refund_v1", "completed", "completed", "approve_refund", "v1"),
        ("policy_boundary_v2", "completed", "completed", "approve_refund", "v2"),
        (
            "refund_record_missing",
            "safe_terminated",
            "missing_evidence",
            "request_evidence",
            "v1",
        ),
        (
            "customer_claim_conflicts_with_succeeded_refund",
            "safe_terminated",
            "evidence_conflict",
            "manual_review",
            "v1",
        ),
        (
            "policy_clause_no_match",
            "safe_terminated",
            "policy_no_match",
            "manual_review",
            "v1",
        ),
        ("policy_timeline_gap", "error", "policy_version_not_found", None, None),
    ],
)
def test_hybrid_core_cases_use_the_real_review_loop(
    case_id: str,
    status: str,
    termination: str,
    recommendation: str | None,
    policy: str | None,
) -> None:
    outcome = HybridBaseline().run(CASES[case_id])

    assert outcome.review_status == status
    assert outcome.termination_reason == termination
    assert outcome.recommendation == recommendation
    assert outcome.policy_version == policy
    assert outcome.tool_calls == ("get_payment",)


@pytest.mark.parametrize(
    ("case_id", "status", "termination"),
    [
        ("payment_tool_timeout", "error", "evidence_source_error"),
        ("unauthorized_tool_call", "safe_terminated", "tool_batch_error"),
        ("agent_max_steps", "safe_terminated", "max_steps"),
        ("invalid_or_untrusted_draft", "error", "invalid_draft"),
    ],
)
def test_hybrid_failures_terminate_without_a_packet(
    case_id: str,
    status: str,
    termination: str,
) -> None:
    outcome = HybridBaseline().run(CASES[case_id])

    assert outcome.review_status == status
    assert outcome.termination_reason == termination
    assert outcome.packet_created is False
    assert outcome.state_change_count == 0
    assert outcome.illegal_tool_execution_count == 0


def test_hybrid_gates_execution_and_replays_without_a_second_change() -> None:
    outcome = HybridBaseline().run(CASES["execute_before_approval_and_retry"])

    assert outcome.workflow_status == "completed_verified"
    assert outcome.verifier_status == "verified"
    assert outcome.side_effect_attempt_count == 3
    assert outcome.illegal_side_effect_count == 0
    assert outcome.state_change_count == 1
    assert outcome.unverified_success_count == 0


def test_hybrid_verifier_mismatch_never_claims_completion() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        outcome = HybridBaseline().run(CASES["verification_mismatch"])

    assert outcome.workflow_status == "verification_failed"
    assert outcome.verifier_status == "mismatch"
    assert outcome.state_change_count == 1
    assert outcome.unverified_success_count == 0
