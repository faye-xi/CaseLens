from datetime import datetime
from typing import Protocol

from caselens.resolution.models import (
    RefundActionCommand,
    RefundSnapshot,
    VerificationResult,
    VerificationStatus,
)
from caselens.tools.models import RefundStatus


class RefundStateReadError(RuntimeError):
    """The final refund state could not be read safely."""


class RefundStateReader(Protocol):
    def get_refund(self, payment_id: str, refund_id: str) -> RefundSnapshot: ...


def verify_refund_state(
    command: RefundActionCommand,
    reader: RefundStateReader,
    *,
    verified_at: datetime,
) -> VerificationResult:
    try:
        actual = reader.get_refund(command.payment_id, command.refund_id)
    except RefundStateReadError:
        return VerificationResult(
            verification_id=f"{command.workflow_id}:verification",
            workflow_id=command.workflow_id,
            status=VerificationStatus.READ_ERROR,
            verified_at=verified_at,
            expected=command,
            error_message="The refund state could not be read.",
        )

    mismatches: list[str] = []
    if actual.payment_id != command.payment_id:
        mismatches.append("payment_id")
    if actual.refund_id != command.refund_id:
        mismatches.append("refund_id")
    if actual.status is not RefundStatus.SUCCEEDED:
        mismatches.append("status")
    if actual.amount != command.amount:
        mismatches.append("amount")
    if actual.currency != command.currency:
        mismatches.append("currency")
    if actual.completed_at is None:
        mismatches.append("completed_at")

    return VerificationResult(
        verification_id=f"{command.workflow_id}:verification",
        workflow_id=command.workflow_id,
        status=(
            VerificationStatus.MISMATCH if mismatches else VerificationStatus.VERIFIED
        ),
        verified_at=verified_at,
        expected=command,
        actual=actual,
        mismatches=tuple(mismatches),
    )
