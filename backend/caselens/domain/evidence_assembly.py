from collections.abc import Collection
from datetime import datetime

from caselens.domain.investigation import (
    Evidence,
    EvidenceBundle,
    EvidenceConflict,
    EvidenceKind,
    Fact,
    FactKey,
    FactReference,
    MissingEvidence,
)
from caselens.domain.models import Case
from caselens.tools.models import PaymentRecord, RefundRecord, RefundStatus
from caselens.tools.protocol import ToolErrorCode, ToolExecutionResult


class EvidenceAssemblyError(RuntimeError):
    """A required evidence source failed without yielding trusted data."""

    def __init__(self, code: ToolErrorCode, message: str) -> None:
        self.code = code
        super().__init__(message)


def assemble_refund_not_received_evidence(
    case: Case,
    tool_results: Collection[ToolExecutionResult],
    *,
    collected_at: datetime,
) -> EvidenceBundle:
    customer_evidence_id = f"{case.case_id}:customer_statement"
    customer_fact_id = f"{customer_evidence_id}:refund_received"
    customer_evidence = Evidence(
        evidence_id=customer_evidence_id,
        kind=EvidenceKind.CUSTOMER_STATEMENT,
        source_record_id=case.case_id,
        collected_at=collected_at,
        facts=(
            Fact(
                fact_id=customer_fact_id,
                key=FactKey.REFUND_RECEIVED,
                value=False,
            ),
        ),
    )

    payment_results = tuple(
        result for result in tool_results if result.trace.tool_name == "get_payment"
    )
    payment = _latest_successful_payment(payment_results)
    if payment is None:
        _raise_unresolved_payment_error(payment_results)
        return EvidenceBundle(
            case_id=case.case_id,
            evidence=(customer_evidence,),
            missing_evidence=(
                MissingEvidence(
                    kind=EvidenceKind.REFUND_RECORD,
                    reason="The refund record has not been retrieved.",
                ),
            ),
        )

    refund = _select_refund(case, payment)
    if refund is None:
        reason = (
            "The refund record could not be matched uniquely to the case."
            if case.refund_id is None and len(payment.refunds) > 1
            else "The matching refund record was not found in the payment record."
        )
        return EvidenceBundle(
            case_id=case.case_id,
            evidence=(customer_evidence,),
            missing_evidence=(
                MissingEvidence(kind=EvidenceKind.REFUND_RECORD, reason=reason),
            ),
        )

    refund_evidence_id = f"{case.case_id}:refund:{refund.refund_id}"
    refund_received_fact_id = f"{refund_evidence_id}:refund_received"
    refund_evidence = Evidence(
        evidence_id=refund_evidence_id,
        kind=EvidenceKind.REFUND_RECORD,
        source_record_id=refund.refund_id,
        collected_at=_tool_completed_at(payment_results, payment),
        facts=(
            Fact(
                fact_id=refund_received_fact_id,
                key=FactKey.REFUND_RECEIVED,
                value=refund.status is RefundStatus.SUCCEEDED,
            ),
            Fact(
                fact_id=f"{refund_evidence_id}:refund_status",
                key=FactKey.REFUND_STATUS,
                value=refund.status.value,
            ),
            Fact(
                fact_id=f"{refund_evidence_id}:refund_amount",
                key=FactKey.REFUND_AMOUNT,
                value=refund.amount,
            ),
        ),
    )

    conflicts: tuple[EvidenceConflict, ...] = ()
    refund_received = refund.status is RefundStatus.SUCCEEDED
    if refund_received:
        conflicts = (
            EvidenceConflict(
                key=FactKey.REFUND_RECEIVED,
                left=FactReference(
                    evidence_id=customer_evidence_id,
                    fact_id=customer_fact_id,
                ),
                right=FactReference(
                    evidence_id=refund_evidence_id,
                    fact_id=refund_received_fact_id,
                ),
            ),
        )

    return EvidenceBundle(
        case_id=case.case_id,
        evidence=(customer_evidence, refund_evidence),
        conflicts=conflicts,
    )


def _latest_successful_payment(
    payment_results: tuple[ToolExecutionResult, ...],
) -> PaymentRecord | None:
    for result in reversed(payment_results):
        if isinstance(result.data, PaymentRecord):
            return result.data
    return None


def _raise_unresolved_payment_error(
    payment_results: tuple[ToolExecutionResult, ...],
) -> None:
    for result in payment_results:
        if (
            result.error is not None
            and result.error.code is not ToolErrorCode.NOT_FOUND
        ):
            raise EvidenceAssemblyError(
                result.error.code,
                f"The payment evidence source failed: {result.error.code.value}.",
            )


def _select_refund(case: Case, payment: PaymentRecord) -> RefundRecord | None:
    if case.refund_id is not None:
        return next(
            (
                refund
                for refund in payment.refunds
                if refund.refund_id == case.refund_id
            ),
            None,
        )
    if len(payment.refunds) == 1:
        return payment.refunds[0]
    return None


def _tool_completed_at(
    payment_results: tuple[ToolExecutionResult, ...],
    payment: PaymentRecord,
) -> datetime:
    for result in reversed(payment_results):
        if result.data is payment:
            return result.trace.completed_at
    raise AssertionError("A selected payment must have a matching tool trace.")
