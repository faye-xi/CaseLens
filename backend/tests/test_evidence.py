from caselens.domain.evidence import find_missing_evidence
from caselens.domain.models import Case


def test_reports_missing_refund_record() -> None:
    case = Case.model_validate(
        {
            "case_id": "CASE-004",
            "case_type": "refund_not_received",
            "occurred_at": "2026-07-28T21:21:00+08:00",
            "customer_statement": "I did not receive my refund",
            "claim_amount": 50,
            "currency": "CNY",
            "order_id": "ORDER-004",
            "payment_id": "PAYMENT004",
            "refund_id": None,
        }
    )

    missing_evidence = find_missing_evidence(case)

    assert missing_evidence == ["refund_record"]


def test_reports_no_missing_evidence_when_refund_id_exists() -> None:
    case = Case.model_validate(
        {
            "case_id": "CASE-005",
            "case_type": "refund_not_received",
            "occurred_at": "2026-07-28T21:21:00+08:00",
            "customer_statement": "I did not receive my refund",
            "claim_amount": 50,
            "currency": "CNY",
            "order_id": "ORDER-005",
            "payment_id": "PAYMENT005",
            "refund_id": "REFUND-005",
        }
    )

    missing_evidence = find_missing_evidence(case)

    assert missing_evidence == []
