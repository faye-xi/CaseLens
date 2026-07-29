from decimal import Decimal

import pytest
from pydantic import ValidationError

from caselens.domain.models import Case, CaseType


def test_accepts_valid_refund_not_received_case() -> None:
    case = Case.model_validate(
        {
            "case_id": "CASE-001",
            "case_type": "refund_not_received",
            "occurred_at": "2026-07-28T21:21:00+08:00",
            "customer_statement": "I did not receive my refund",
            "claim_amount": 50,
            "currency": "CNY",
            "order_id": "ORDER-001",
            "payment_id": "PAYMENT001",
            "refund_id": None,
        }
    )

    assert case.case_type is CaseType.REFUND_NOT_RECEIVED
    assert case.claim_amount == Decimal(50)
    assert case.occurred_at.utcoffset() is not None
    assert case.refund_id is None


def test_rejects_occurred_at_without_timezone() -> None:
    with pytest.raises(ValidationError):
        Case.model_validate(
            {
                "case_id": "CASE-002",
                "case_type": "refund_not_received",
                "occurred_at": "2026-07-28T21:21:00",
                "customer_statement": "I did not receive my refund",
                "claim_amount": 50,
                "currency": "CNY",
                "order_id": "ORDER-002",
                "payment_id": "PAYMENT002",
                "refund_id": None,
            }
        )


def test_rejects_non_positive_claim_amount() -> None:
    with pytest.raises(ValidationError):
        Case.model_validate(
            {
                "case_id": "CASE-002",
                "case_type": "refund_not_received",
                "occurred_at": "2026-07-28T21:21:00+08:00",
                "customer_statement": "I did not receive my refund",
                "claim_amount": 0,
                "currency": "CNY",
                "order_id": "ORDER-002",
                "payment_id": "PAYMENT002",
                "refund_id": None,
            }
        )


def test_rejects_case_without_order_id() -> None:
    with pytest.raises(ValidationError):
        Case.model_validate(
            {
                "case_id": "CASE-003",
                "case_type": "refund_not_received",
                "occurred_at": "2026-07-28T21:21:00+08:00",
                "customer_statement": "I did not receive my refund",
                "claim_amount": 50,
                "currency": "CNY",
                "payment_id": "PAYMENT002",
                "refund_id": None,
            }
        )


def test_accepts_case_without_refund_id() -> None:
    case = Case.model_validate(
        {
            "case_id": "CASE-002",
            "case_type": "refund_not_received",
            "occurred_at": "2026-07-28T21:21:00+08:00",
            "customer_statement": "I did not receive my refund",
            "claim_amount": 50,
            "currency": "CNY",
            "order_id": "ORDER-002",
            "payment_id": "PAYMENT002",
        }
    )

    assert case.refund_id is None
