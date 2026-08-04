from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from caselens.agent.case_review import (
    CaseReviewResult,
    CaseReviewStatus,
    CaseReviewTerminationReason,
)
from caselens.agent.protocol import (
    InvestigationResult,
    InvestigationStatus,
    InvestigationTerminationReason,
)
from caselens.domain.decision import (
    DecisionDraft,
    DecisionPacket,
    DecisionRecommendation,
    build_decision_packet,
)
from caselens.domain.investigation import Evidence, EvidenceBundle, Fact
from caselens.domain.models import Case
from caselens.domain.policy import PolicyVersion
from caselens.domain.policy_retrieval import (
    PolicyCitation,
    PolicyRetrievalResult,
)
from caselens.model.protocol import (
    ModelFinishReason,
    ModelMessage,
    ModelResponse,
)
from caselens.resolution.models import (
    ActionReceipt,
    ApprovalRequest,
    RefundActionCommand,
    ResolutionRun,
    ResolutionStatus,
)
from caselens.resolution.planning import (
    ResolutionPlanningError,
    packet_fingerprint,
    plan_refund_action,
)

OCCURRED_AT = datetime(2026, 6, 15, 13, 21, tzinfo=UTC)
CREATED_AT = datetime(2026, 8, 4, 13, 0, tzinfo=UTC)


def make_case(*, case_id: str = "CASE-006") -> Case:
    return Case(
        case_id=case_id,
        case_type="refund_not_received",
        occurred_at=OCCURRED_AT,
        customer_statement="I did not receive my refund.",
        claim_amount=Decimal("50.00"),
        currency="CNY",
        order_id="order-1",
        payment_id="payment-1",
        refund_id="refund-1",
    )


def make_bundle(*, case_id: str = "CASE-006") -> EvidenceBundle:
    return EvidenceBundle(
        case_id=case_id,
        evidence=(
            Evidence(
                evidence_id=f"{case_id}:refund:refund-1",
                kind="refund_record",
                source_record_id="refund-1",
                collected_at=CREATED_AT,
                facts=(
                    Fact(
                        fact_id=f"{case_id}:refund:refund-1:refund_received",
                        key="refund_received",
                        value=False,
                    ),
                    Fact(
                        fact_id=f"{case_id}:refund:refund-1:refund_amount",
                        key="refund_amount",
                        value=Decimal("50.00"),
                    ),
                ),
            ),
        ),
    )


def make_policy_result() -> PolicyRetrievalResult:
    version = PolicyVersion(
        policy_id="refund-policy",
        version="v1",
        effective_from=datetime(2026, 1, 1, tzinfo=UTC),
        effective_to=datetime(2026, 7, 1, tzinfo=UTC),
    )
    return PolicyRetrievalResult(
        query="refund not received",
        selected_version=version,
        citations=(
            PolicyCitation(
                clause_id="REFUND-V1",
                policy_id="refund-policy",
                version="v1",
                effective_from=version.effective_from,
                effective_to=version.effective_to,
                score=1.0,
                quote="Refund not received cases allow seven days.",
            ),
        ),
    )


def make_packet(
    *,
    case_id: str = "CASE-006",
    recommendation: DecisionRecommendation = DecisionRecommendation.APPROVE_REFUND,
    risk_level: str | None = None,
) -> tuple[EvidenceBundle, PolicyRetrievalResult, DecisionDraft, DecisionPacket]:
    bundle = make_bundle(case_id=case_id)
    policy_result = make_policy_result()
    selected_risk = risk_level or (
        "high" if recommendation is DecisionRecommendation.APPROVE_REFUND else "low"
    )
    draft = DecisionDraft(
        case_id=case_id,
        recommendation=recommendation,
        rationale="The trusted refund record supports this recommendation.",
        risk_level=selected_risk,
        evidence_references=(
            {
                "evidence_id": f"{case_id}:refund:refund-1",
                "fact_id": f"{case_id}:refund:refund-1:refund_received",
            },
        ),
        policy_clause_ids=("REFUND-V1",),
    )
    return (
        bundle,
        policy_result,
        draft,
        build_decision_packet(bundle, policy_result, draft),
    )


def make_review(
    *,
    case_id: str = "CASE-006",
    recommendation: DecisionRecommendation = DecisionRecommendation.APPROVE_REFUND,
    risk_level: str | None = None,
) -> CaseReviewResult:
    bundle, policy_result, draft, packet = make_packet(
        case_id=case_id,
        recommendation=recommendation,
        risk_level=risk_level,
    )
    final_response = ModelResponse(
        response_id="response-stop",
        finish_reason=ModelFinishReason.STOP,
        message=ModelMessage(role="assistant", content="Complete."),
    )
    investigation = InvestigationResult(
        status=InvestigationStatus.COMPLETED,
        termination_reason=InvestigationTerminationReason.COMPLETED,
        steps=1,
        final_response=final_response,
    )
    return CaseReviewResult(
        case_id=case_id,
        status=CaseReviewStatus.COMPLETED,
        termination_reason=CaseReviewTerminationReason.COMPLETED,
        investigation=investigation,
        evidence_bundle=bundle,
        policy_result=policy_result,
        decision_draft=draft,
        decision_packet=packet,
    )


def test_packet_fingerprint_is_stable_for_equivalent_packets() -> None:
    packet = make_packet()[3]
    reconstructed = DecisionPacket.model_validate(packet.model_dump(mode="json"))

    assert packet_fingerprint(packet) == packet_fingerprint(reconstructed)
    assert len(packet_fingerprint(packet)) == 64


def test_plans_refund_completion_from_trusted_review() -> None:
    command = plan_refund_action(
        make_case(),
        make_review(),
        workflow_id="run-1",
    )

    assert command is not None
    assert command.refund_id == "refund-1"
    assert command.idempotency_key == "complete_refund:payment-1:refund-1"
    assert command.amount == Decimal("50.00")
    assert command.currency == "CNY"


def test_non_action_recommendation_has_no_refund_command() -> None:
    command = plan_refund_action(
        make_case(),
        make_review(recommendation=DecisionRecommendation.DENY_REFUND),
        workflow_id="run-1",
    )

    assert command is None


def test_planner_rejects_review_for_another_case() -> None:
    with pytest.raises(ResolutionPlanningError, match="same case"):
        plan_refund_action(
            make_case(),
            make_review(case_id="CASE-OTHER"),
            workflow_id="run-1",
        )


def test_planner_rejects_action_from_non_completed_review() -> None:
    review = make_review().model_copy(
        update={
            "status": CaseReviewStatus.SAFE_TERMINATED,
            "termination_reason": CaseReviewTerminationReason.MISSING_EVIDENCE,
        }
    )

    with pytest.raises(ResolutionPlanningError, match="completed review"):
        plan_refund_action(make_case(), review, workflow_id="run-1")


def test_successful_action_receipt_rejects_error_fields() -> None:
    with pytest.raises(ValidationError, match="error"):
        ActionReceipt(
            receipt_id="receipt-1",
            action_id="action-1",
            workflow_id="run-1",
            idempotency_key="complete_refund:payment-1:refund-1",
            status="succeeded",
            completed_at=CREATED_AT,
            error_code="refund_not_found",
        )


def test_resolution_run_rejects_verified_state_without_verification() -> None:
    packet = make_packet()[3]

    with pytest.raises(ValidationError, match="verification"):
        ResolutionRun(
            workflow_id="run-1",
            review_id="review-1",
            case_id="CASE-006",
            packet=packet,
            packet_fingerprint=packet_fingerprint(packet),
            status=ResolutionStatus.COMPLETED_VERIFIED,
            created_at=CREATED_AT,
            updated_at=CREATED_AT,
        )


def test_resolution_run_rejects_fingerprint_not_derived_from_packet() -> None:
    packet = make_packet()[3]
    wrong_fingerprint = "0" * 64

    with pytest.raises(ValidationError, match="fingerprint"):
        ResolutionRun(
            workflow_id="run-1",
            review_id="review-1",
            case_id="CASE-006",
            packet=packet,
            packet_fingerprint=wrong_fingerprint,
            status=ResolutionStatus.WAITING_APPROVAL,
            created_at=CREATED_AT,
            updated_at=CREATED_AT,
            approval_request=ApprovalRequest(
                approval_id="run-1:approval",
                workflow_id="run-1",
                case_id="CASE-006",
                packet_fingerprint=wrong_fingerprint,
                requested_at=CREATED_AT,
            ),
        )


def test_refund_command_rejects_non_resource_idempotency_key() -> None:
    command = plan_refund_action(make_case(), make_review(), workflow_id="run-1")
    assert command is not None
    payload = command.model_dump()
    payload["idempotency_key"] = "complete_refund:another-payment:refund-1"

    with pytest.raises(ValidationError, match="idempotency"):
        RefundActionCommand.model_validate(payload)
