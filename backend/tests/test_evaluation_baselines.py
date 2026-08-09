from pathlib import Path

import pytest

from caselens.evaluation.baselines import (
    ModelOnlyScriptedBaseline,
    RulesOnlyBaseline,
)
from caselens.evaluation.dataset import load_golden_cases
from caselens.evaluation.models import Applicability, BaselineId

DATASET = Path(__file__).parents[1] / "evals" / "golden_cases.json"
CASES = {case.case_id: case for case in load_golden_cases(DATASET)}


@pytest.mark.parametrize(
    ("case_id", "recommendation", "policy_version", "packet_created"),
    [
        ("processing_refund_v1", "approve_refund", "v1", True),
        ("policy_boundary_v2", "approve_refund", "v2", True),
        ("refund_record_missing", "request_evidence", "v1", True),
        (
            "customer_claim_conflicts_with_succeeded_refund",
            "manual_review",
            "v1",
            True,
        ),
        ("policy_clause_no_match", "manual_review", "v1", True),
        ("policy_timeline_gap", None, None, False),
    ],
)
def test_rules_only_uses_existing_evidence_and_policy_boundaries(
    case_id: str,
    recommendation: str | None,
    policy_version: str | None,
    packet_created: bool,
) -> None:
    outcome = RulesOnlyBaseline().run(CASES[case_id])

    assert outcome.applicability is Applicability.APPLICABLE
    assert outcome.recommendation == recommendation
    assert outcome.policy_version == policy_version
    assert outcome.packet_created is packet_created
    assert outcome.tool_calls == ("get_payment",)
    assert outcome.ungrounded_finalization_count == 0


def test_scripted_model_only_exposes_ungrounded_claims_without_executing() -> None:
    outcome = ModelOnlyScriptedBaseline().run(CASES["processing_refund_v1"])

    assert outcome.baseline_id is BaselineId.MODEL_ONLY_SCRIPTED
    assert outcome.recommendation == "approve_refund"
    assert outcome.policy_version == "v2"
    assert outcome.packet_created is False
    assert outcome.tool_calls == ()
    assert outcome.ungrounded_finalization_count == 1
    assert outcome.unverified_success_count == 1
    assert outcome.state_change_count == 0


def test_excluded_baseline_returns_an_explicit_non_applicable_row() -> None:
    outcome = RulesOnlyBaseline().run(CASES["payment_tool_timeout"])

    assert outcome.applicability is Applicability.NOT_APPLICABLE
    assert outcome.packet_created is False
