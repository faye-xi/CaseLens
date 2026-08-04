from datetime import UTC, datetime
from decimal import Decimal

import pytest

from caselens.domain.evidence_assembly import (
    EvidenceAssemblyError,
    assemble_refund_not_received_evidence,
)
from caselens.domain.investigation import EvidenceKind, EvidenceStatus, FactKey
from caselens.domain.models import Case
from caselens.tools.execution import execute_tool
from caselens.tools.models import (
    PaymentRecord,
    PaymentStatus,
    RefundRecord,
    RefundStatus,
)
from caselens.tools.protocol import ToolCall, ToolErrorCode
from caselens.tools.source import InMemoryBusinessDataSource

OCCURRED_AT = datetime(2026, 7, 28, 13, 21, tzinfo=UTC)
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


def payment_result(payment: PaymentRecord):
    return execute_tool(
        InMemoryBusinessDataSource(payments=(payment,)),
        ToolCall(
            call_id="call-payment",
            tool_name="get_payment",
            arguments={"payment_id": "payment-1"},
        ),
    )


def test_assembles_customer_and_successful_refund_facts() -> None:
    result = assemble_refund_not_received_evidence(
        make_case(),
        (payment_result(make_payment(refund_status=RefundStatus.SUCCEEDED)),),
        collected_at=COLLECTED_AT,
    )

    assert result.status is EvidenceStatus.CONFLICTED
    assert [evidence.kind for evidence in result.evidence] == [
        EvidenceKind.CUSTOMER_STATEMENT,
        EvidenceKind.REFUND_RECORD,
    ]
    assert result.conflicts[0].key is FactKey.REFUND_RECEIVED


def test_non_succeeded_refund_is_complete_without_conflict() -> None:
    result = assemble_refund_not_received_evidence(
        make_case(),
        (payment_result(make_payment()),),
        collected_at=COLLECTED_AT,
    )

    assert result.status is EvidenceStatus.COMPLETE
    refund_facts = result.evidence[1].facts
    assert {fact.key for fact in refund_facts} == {
        FactKey.REFUND_RECEIVED,
        FactKey.REFUND_STATUS,
        FactKey.REFUND_AMOUNT,
    }


def test_missing_target_refund_becomes_incomplete_evidence() -> None:
    result = assemble_refund_not_received_evidence(
        make_case(refund_id="refund-missing"),
        (payment_result(make_payment()),),
        collected_at=COLLECTED_AT,
    )

    assert result.status is EvidenceStatus.INCOMPLETE
    assert result.missing_evidence[0].kind is EvidenceKind.REFUND_RECORD


def test_missing_refund_id_discovers_the_only_refund() -> None:
    result = assemble_refund_not_received_evidence(
        make_case(refund_id=None),
        (payment_result(make_payment()),),
        collected_at=COLLECTED_AT,
    )

    assert result.status is EvidenceStatus.COMPLETE
    assert result.evidence[1].source_record_id == "refund-1"


def test_multiple_refunds_without_id_remain_incomplete() -> None:
    result = assemble_refund_not_received_evidence(
        make_case(refund_id=None),
        (payment_result(make_payment(refund_ids=("refund-1", "refund-2"))),),
        collected_at=COLLECTED_AT,
    )

    assert result.status is EvidenceStatus.INCOMPLETE
    assert "uniquely" in result.missing_evidence[0].reason


def test_payment_source_error_is_not_treated_as_missing_evidence() -> None:
    tool_result = execute_tool(
        InMemoryBusinessDataSource(
            payments=(make_payment(),),
            timed_out_operations={"payments"},
        ),
        ToolCall(
            call_id="call-payment-timeout",
            tool_name="get_payment",
            arguments={"payment_id": "payment-1"},
        ),
    )

    assert tool_result.error is not None
    assert tool_result.error.code is ToolErrorCode.TIMEOUT

    with pytest.raises(EvidenceAssemblyError, match="source"):
        assemble_refund_not_received_evidence(
            make_case(),
            (tool_result,),
            collected_at=COLLECTED_AT,
        )
