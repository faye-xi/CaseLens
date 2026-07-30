from caselens.domain.contracts import (
    InvestigationReadiness,
    assess_refund_not_received,
)
from caselens.domain.models import Case


def make_case(*, refund_id: str | None) -> Case:
    return Case.model_validate(
        {
            "case_id": "CASE-006",
            "case_type": "refund_not_received",
            "occurred_at": "2026-07-28T21:21:00+08:00",
            "customer_statement": "I did not receive my refund",
            "claim_amount": 50,
            "currency": "CNY",
            "order_id": "ORDER-006",
            "payment_id": "PAYMENT-006",
            "refund_id": refund_id,
        }
    )


def test_missing_refund_reference_requests_refund_record() -> None:
    assessment = assess_refund_not_received(make_case(refund_id=None))

    assert assessment.case_id == "CASE-006"
    assert assessment.readiness is InvestigationReadiness.NEEDS_EVIDENCE
    assert assessment.missing_evidence == ("refund_record",)


def test_refund_reference_makes_case_ready_for_investigation() -> None:
    assessment = assess_refund_not_received(make_case(refund_id="REFUND-006"))

    assert assessment.case_id == "CASE-006"
    assert assessment.readiness is InvestigationReadiness.READY
    assert assessment.missing_evidence == ()
