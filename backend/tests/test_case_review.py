from datetime import UTC, datetime
from decimal import Decimal

from caselens.agent.case_review import (
    CaseReviewStatus,
    CaseReviewTerminationReason,
    run_case_review,
)
from caselens.domain.decision import DecisionRecommendation
from caselens.domain.models import Case
from caselens.domain.policy import PolicyTimeline, PolicyVersion
from caselens.domain.policy_retrieval import PolicyClause, PolicyClauseCorpus
from caselens.model import MockModel, ModelFinishReason, ModelMessage, ModelResponse
from caselens.tools.models import (
    PaymentRecord,
    PaymentStatus,
    RefundRecord,
    RefundStatus,
)
from caselens.tools.protocol import ToolCall
from caselens.tools.source import InMemoryBusinessDataSource

OCCURRED_AT = datetime(2026, 6, 15, 13, 21, tzinfo=UTC)
COLLECTED_AT = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)


def make_case(*, refund_id: str | None = "refund-1") -> Case:
    return Case(
        case_id="CASE-006",
        case_type="refund_not_received",
        occurred_at=OCCURRED_AT,
        customer_statement="I did not receive my refund.",
        claim_amount=Decimal("50.00"),
        currency="CNY",
        order_id="order-1",
        payment_id="payment-1",
        refund_id=refund_id,
    )


def make_payment(
    *,
    refund_status: RefundStatus = RefundStatus.PROCESSING,
    refund_ids: tuple[str, ...] = ("refund-1",),
) -> PaymentRecord:
    return PaymentRecord(
        payment_id="payment-1",
        order_id="order-1",
        status=PaymentStatus.PAID,
        amount=Decimal("50.00"),
        currency="CNY",
        paid_at=OCCURRED_AT,
        refunds=tuple(
            RefundRecord(
                refund_id=refund_id,
                status=refund_status,
                amount=Decimal("50.00"),
                currency="CNY",
                requested_at=OCCURRED_AT,
                completed_at=COLLECTED_AT
                if refund_status is RefundStatus.SUCCEEDED
                else None,
            )
            for refund_id in refund_ids
        ),
    )


def make_source(
    *,
    refund_status: RefundStatus = RefundStatus.PROCESSING,
    refund_ids: tuple[str, ...] = ("refund-1",),
) -> InMemoryBusinessDataSource:
    return InMemoryBusinessDataSource(
        payments=(
            make_payment(
                refund_status=refund_status,
                refund_ids=refund_ids,
            ),
        )
    )


def make_timeline() -> PolicyTimeline:
    return PolicyTimeline(
        policy_id="refund-policy",
        versions=(
            PolicyVersion(
                policy_id="refund-policy",
                version="v1",
                effective_from=datetime(2026, 1, 1, tzinfo=UTC),
                effective_to=datetime(2026, 7, 1, tzinfo=UTC),
            ),
            PolicyVersion(
                policy_id="refund-policy",
                version="v2",
                effective_from=datetime(2026, 7, 1, tzinfo=UTC),
            ),
        ),
    )


def make_corpus(*, matching: bool = True) -> PolicyClauseCorpus:
    return PolicyClauseCorpus(
        clauses=(
            PolicyClause(
                clause_id="REFUND-V1",
                policy_id="refund-policy",
                version="v1",
                text=(
                    "Refund not received cases allow seven days."
                    if matching
                    else "Shipment tracking requires a carrier scan."
                ),
            ),
        )
    )


def make_tool_call_response(*, tool_name: str = "get_payment") -> ModelResponse:
    return ModelResponse(
        response_id="response-tool",
        finish_reason=ModelFinishReason.TOOL_CALLS,
        message=ModelMessage(
            role="assistant",
            tool_calls=(
                ToolCall(
                    call_id="call-payment",
                    tool_name=tool_name,
                    arguments={"payment_id": "payment-1"},
                ),
            ),
        ),
    )


def make_stop_response() -> ModelResponse:
    return ModelResponse(
        response_id="response-stop",
        finish_reason=ModelFinishReason.STOP,
        message=ModelMessage(role="assistant", content="Investigation complete."),
    )


def make_draft_response(
    *,
    evidence_id: str = "CASE-006:refund:refund-1:refund_received",
    policy_clause_id: str = "REFUND-V1",
) -> ModelResponse:
    return ModelResponse(
        response_id="response-draft",
        finish_reason=ModelFinishReason.STOP,
        message=ModelMessage(role="assistant"),
        structured_output={
            "case_id": "CASE-006",
            "recommendation": "approve_refund",
            "rationale": "The refund record is still processing under the effective policy.",
            "risk_level": "high",
            "evidence_references": [
                {
                    "evidence_id": evidence_id.rsplit(":refund_received", 1)[0],
                    "fact_id": evidence_id,
                }
            ],
            "policy_clause_ids": [policy_clause_id],
        },
    )


def run_review(
    model: MockModel,
    *,
    case: Case | None = None,
    source: InMemoryBusinessDataSource | None = None,
    corpus: PolicyClauseCorpus | None = None,
    timeline: PolicyTimeline | None = None,
    max_steps: int = 8,
):
    return run_case_review(
        case or make_case(),
        model,
        source or make_source(),
        timeline or make_timeline(),
        corpus or make_corpus(),
        collected_at=COLLECTED_AT,
        max_steps=max_steps,
        request_id_prefix="run-1",
    )


def test_runs_investigation_retrieves_policy_and_builds_packet() -> None:
    model = MockModel(
        (
            make_tool_call_response(),
            make_stop_response(),
            make_draft_response(),
        )
    )

    result = run_review(model)

    assert result.status is CaseReviewStatus.COMPLETED
    assert result.termination_reason is CaseReviewTerminationReason.COMPLETED
    assert result.decision_packet is not None
    assert (
        result.decision_packet.recommendation is DecisionRecommendation.APPROVE_REFUND
    )
    assert result.decision_packet.selected_policy_version.version == "v1"
    assert len(model.received_requests) == 3
    assert model.received_requests[0].messages[1].content is not None
    assert "CASE-006" in model.received_requests[0].messages[1].content
    assert model.received_requests[2].tools == ()
    assert model.received_requests[2].response_schema is not None
    assert result.draft_trace is not None


def test_missing_refund_record_returns_request_evidence_packet() -> None:
    model = MockModel((make_tool_call_response(), make_stop_response()))

    result = run_review(
        model,
        case=make_case(refund_id="refund-missing"),
        source=make_source(refund_ids=("refund-1",)),
    )

    assert result.status is CaseReviewStatus.SAFE_TERMINATED
    assert result.termination_reason is CaseReviewTerminationReason.MISSING_EVIDENCE
    assert result.decision_packet is not None
    assert (
        result.decision_packet.recommendation is DecisionRecommendation.REQUEST_EVIDENCE
    )
    assert len(model.received_requests) == 2


def test_conflicted_refund_record_returns_manual_review_packet() -> None:
    model = MockModel((make_tool_call_response(), make_stop_response()))

    result = run_review(
        model,
        source=make_source(refund_status=RefundStatus.SUCCEEDED),
    )

    assert result.status is CaseReviewStatus.SAFE_TERMINATED
    assert result.termination_reason is CaseReviewTerminationReason.EVIDENCE_CONFLICT
    assert result.decision_packet is not None
    assert result.decision_packet.recommendation is DecisionRecommendation.MANUAL_REVIEW
    assert result.decision_packet.evidence_conflicts
    assert len(model.received_requests) == 2


def test_policy_no_match_returns_manual_review_without_citation() -> None:
    model = MockModel((make_tool_call_response(), make_stop_response()))

    result = run_review(model, corpus=make_corpus(matching=False))

    assert result.status is CaseReviewStatus.SAFE_TERMINATED
    assert result.termination_reason is CaseReviewTerminationReason.POLICY_NO_MATCH
    assert result.decision_packet is not None
    assert result.decision_packet.recommendation is DecisionRecommendation.MANUAL_REVIEW
    assert result.decision_packet.policy_citations == ()


def test_policy_gap_does_not_create_packet() -> None:
    model = MockModel((make_tool_call_response(), make_stop_response()))
    gap_timeline = PolicyTimeline(
        policy_id="refund-policy",
        versions=(
            PolicyVersion(
                policy_id="refund-policy",
                version="v2",
                effective_from=datetime(2026, 7, 1, tzinfo=UTC),
            ),
        ),
    )

    result = run_review(model, timeline=gap_timeline)

    assert result.status is CaseReviewStatus.ERROR
    assert (
        result.termination_reason
        is CaseReviewTerminationReason.POLICY_VERSION_NOT_FOUND
    )
    assert result.decision_packet is None


def test_model_error_does_not_create_packet() -> None:
    result = run_review(MockModel(({"finish_reason": "tool_calls"},)))

    assert result.status is CaseReviewStatus.ERROR
    assert result.termination_reason is CaseReviewTerminationReason.MODEL_ERROR
    assert result.decision_packet is None


def test_tool_batch_error_does_not_create_packet() -> None:
    result = run_review(MockModel((make_tool_call_response(tool_name="delete_order"),)))

    assert result.status is CaseReviewStatus.SAFE_TERMINATED
    assert result.termination_reason is CaseReviewTerminationReason.TOOL_BATCH_ERROR
    assert result.decision_packet is None


def test_max_steps_does_not_create_packet() -> None:
    result = run_review(
        MockModel((make_tool_call_response(), make_stop_response())),
        max_steps=1,
    )

    assert result.status is CaseReviewStatus.SAFE_TERMINATED
    assert result.termination_reason is CaseReviewTerminationReason.MAX_STEPS
    assert result.decision_packet is None


def test_invalid_structured_draft_does_not_create_packet() -> None:
    invalid_draft = make_draft_response()
    invalid_draft = invalid_draft.model_copy(
        update={
            "structured_output": {
                "case_id": "CASE-006",
                "recommendation": "approve_refund",
                "rationale": "Approve it.",
                "risk_level": "high",
                "evidence_references": [],
                "policy_clause_ids": ["REFUND-V1"],
            }
        }
    )
    model = MockModel((make_tool_call_response(), make_stop_response(), invalid_draft))

    result = run_review(model)

    assert result.status is CaseReviewStatus.ERROR
    assert result.termination_reason is CaseReviewTerminationReason.INVALID_DRAFT
    assert result.decision_packet is None


def test_unknown_draft_reference_does_not_create_packet() -> None:
    model = MockModel(
        (
            make_tool_call_response(),
            make_stop_response(),
            make_draft_response(evidence_id="CASE-006:missing:fact"),
        )
    )

    result = run_review(model)

    assert result.status is CaseReviewStatus.ERROR
    assert result.termination_reason is CaseReviewTerminationReason.INVALID_DRAFT
    assert result.decision_packet is None
