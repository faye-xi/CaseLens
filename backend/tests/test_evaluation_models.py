from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from caselens.domain.models import Case
from caselens.domain.policy import PolicyVersion
from caselens.domain.policy_retrieval import PolicyClause
from caselens.evaluation.models import (
    Applicability,
    BaselineId,
    EvaluationInput,
    EvaluationOutcome,
    GoldenCase,
    GoldenExpectation,
    MeasurementState,
    ScenarioId,
    ScriptedCandidate,
)
from caselens.tools.models import PaymentRecord, PaymentStatus

NOW = datetime(2026, 6, 15, tzinfo=UTC)


def valid_golden_case() -> GoldenCase:
    return GoldenCase(
        case_id="processing_refund_v1",
        scenario=ScenarioId.PROCESSING_REFUND_V1,
        description="A processing refund uses policy v1.",
        applicable_baselines=tuple(BaselineId),
        input=EvaluationInput(
            case=Case(
                case_id="CASE-EVAL-001",
                case_type="refund_not_received",
                occurred_at=NOW,
                customer_statement="The refund has not arrived.",
                claim_amount=Decimal("50.00"),
                currency="CNY",
                order_id="order-1",
                payment_id="payment-1",
                refund_id="refund-1",
            ),
            payments=(
                PaymentRecord(
                    payment_id="payment-1",
                    order_id="order-1",
                    status=PaymentStatus.PAID,
                    amount=Decimal("50.00"),
                    currency="CNY",
                    paid_at=NOW,
                ),
            ),
            policy_versions=(
                PolicyVersion(
                    policy_id="refund-policy",
                    version="v1",
                    effective_from=datetime(2026, 1, 1, tzinfo=UTC),
                ),
            ),
            policy_clauses=(
                PolicyClause(
                    clause_id="REFUND-V1",
                    policy_id="refund-policy",
                    version="v1",
                    text="Refund not received cases permit completion.",
                ),
            ),
            model_only_candidate=ScriptedCandidate(
                recommendation="approve_refund",
                policy_version="v2",
                claims_action_succeeded=True,
            ),
        ),
        expectation=GoldenExpectation(
            review_status="completed",
            termination_reason="completed",
            recommendation="approve_refund",
            evidence_status="complete",
            policy_version="v1",
            packet_expected=True,
            required_tools=("get_payment",),
        ),
    )


def test_golden_case_is_strict_and_immutable() -> None:
    case = valid_golden_case()

    assert case.case_id == "processing_refund_v1"
    with pytest.raises(ValidationError):
        GoldenCase.model_validate({**case.model_dump(), "unknown": True})
    with pytest.raises(ValidationError):
        case.description = "changed"  # type: ignore[misc]


def test_golden_case_rejects_overlapping_tool_expectations() -> None:
    payload = valid_golden_case().model_dump()
    payload["expectation"]["forbidden_tools"] = ["get_payment"]

    with pytest.raises(ValidationError, match="required and forbidden"):
        GoldenCase.model_validate(payload)


def test_unmeasured_token_cost_rejects_a_numeric_value() -> None:
    with pytest.raises(ValidationError, match="token_count"):
        EvaluationOutcome(
            case_id="processing_refund_v1",
            baseline_id=BaselineId.HYBRID,
            applicability=Applicability.APPLICABLE,
            packet_created=False,
            token_measurement=MeasurementState.NOT_MEASURED,
            token_count=0,
        )


def test_non_applicable_outcome_cannot_claim_a_decision() -> None:
    with pytest.raises(ValidationError, match="Non-applicable"):
        EvaluationOutcome(
            case_id="processing_refund_v1",
            baseline_id=BaselineId.RULES_ONLY,
            applicability=Applicability.NOT_APPLICABLE,
            recommendation="approve_refund",
            packet_created=False,
        )
