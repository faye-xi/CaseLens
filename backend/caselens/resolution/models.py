import hashlib
import json
from decimal import Decimal
from enum import StrEnum
from typing import Annotated

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from caselens.domain.decision import DecisionPacket
from caselens.tools.models import RefundStatus

Identifier = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
]


class ResolutionModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ResolutionStatus(StrEnum):
    WAITING_APPROVAL = "waiting_approval"
    APPROVAL_REJECTED = "approval_rejected"
    READY_TO_EXECUTE = "ready_to_execute"
    EXECUTION_FAILED = "execution_failed"
    READY_TO_VERIFY = "ready_to_verify"
    COMPLETED_VERIFIED = "completed_verified"
    VERIFICATION_FAILED = "verification_failed"
    COMPLETED_NO_ACTION = "completed_no_action"


class ApprovalDecision(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"


class ActionStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ActionErrorCode(StrEnum):
    REFUND_NOT_FOUND = "refund_not_found"
    INVALID_REFUND_STATE = "invalid_refund_state"
    AMOUNT_MISMATCH = "amount_mismatch"
    CURRENCY_MISMATCH = "currency_mismatch"


class VerificationStatus(StrEnum):
    VERIFIED = "verified"
    MISMATCH = "mismatch"
    READ_ERROR = "read_error"


class ApprovalRequest(ResolutionModel):
    approval_id: Identifier
    workflow_id: Identifier
    case_id: Identifier
    packet_fingerprint: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    requested_at: AwareDatetime


class ApprovalRecord(ResolutionModel):
    approval_id: Identifier
    workflow_id: Identifier
    decision: ApprovalDecision
    decided_by: Identifier
    decided_at: AwareDatetime


class RefundActionCommand(ResolutionModel):
    action_id: Identifier
    workflow_id: Identifier
    case_id: Identifier
    payment_id: Identifier
    refund_id: Identifier
    amount: Decimal = Field(gt=0)
    currency: Identifier
    packet_fingerprint: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    idempotency_key: Identifier

    @model_validator(mode="after")
    def validate_idempotency_key(self) -> "RefundActionCommand":
        expected = f"complete_refund:{self.payment_id}:{self.refund_id}"
        if self.idempotency_key != expected:
            raise ValueError("Refund action idempotency key must match its resource.")
        return self


class ActionReceipt(ResolutionModel):
    receipt_id: Identifier
    action_id: Identifier
    workflow_id: Identifier
    idempotency_key: Identifier
    status: ActionStatus
    completed_at: AwareDatetime
    replayed: bool = False
    error_code: ActionErrorCode | None = None
    error_message: Identifier | None = None

    @model_validator(mode="after")
    def validate_outcome(self) -> "ActionReceipt":
        has_complete_error = (
            self.error_code is not None and self.error_message is not None
        )
        has_any_error = self.error_code is not None or self.error_message is not None
        if self.status is ActionStatus.FAILED and not has_complete_error:
            raise ValueError("Failed action receipts require an error.")
        if self.status is ActionStatus.SUCCEEDED and has_any_error:
            raise ValueError("Successful action receipts cannot contain an error.")
        return self


class RefundSnapshot(ResolutionModel):
    payment_id: Identifier
    refund_id: Identifier
    status: RefundStatus
    amount: Decimal = Field(gt=0)
    currency: Identifier
    requested_at: AwareDatetime
    completed_at: AwareDatetime | None = None


class VerificationResult(ResolutionModel):
    verification_id: Identifier
    workflow_id: Identifier
    status: VerificationStatus
    verified_at: AwareDatetime
    expected: RefundActionCommand
    actual: RefundSnapshot | None = None
    mismatches: tuple[Identifier, ...] = ()
    error_message: Identifier | None = None

    @model_validator(mode="after")
    def validate_outcome(self) -> "VerificationResult":
        if self.status is VerificationStatus.VERIFIED:
            if self.actual is None or self.mismatches or self.error_message is not None:
                raise ValueError("Verified results require matching actual state only.")
        elif self.status is VerificationStatus.MISMATCH:
            if (
                self.actual is None
                or not self.mismatches
                or self.error_message is not None
            ):
                raise ValueError(
                    "Mismatch results require actual state and mismatches."
                )
        elif self.actual is not None or self.mismatches or self.error_message is None:
            raise ValueError("Read errors require only a safe error message.")
        return self


class ResolutionRun(ResolutionModel):
    workflow_id: Identifier
    review_id: Identifier
    case_id: Identifier
    packet: DecisionPacket
    packet_fingerprint: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    status: ResolutionStatus
    created_at: AwareDatetime
    updated_at: AwareDatetime
    approval_request: ApprovalRequest | None = None
    approval_record: ApprovalRecord | None = None
    action_command: RefundActionCommand | None = None
    action_receipt: ActionReceipt | None = None
    verification: VerificationResult | None = None

    @model_validator(mode="after")
    def validate_state(self) -> "ResolutionRun":
        if self.packet.case_id != self.case_id:
            raise ValueError("Resolution packet must reference the same case.")
        if self.packet_fingerprint != packet_fingerprint(self.packet):
            raise ValueError("Resolution packet fingerprint does not match its packet.")
        if self.updated_at < self.created_at:
            raise ValueError("Resolution update time cannot precede creation.")
        if self.approval_request is not None and (
            self.approval_request.workflow_id != self.workflow_id
            or self.approval_request.case_id != self.case_id
            or self.approval_request.packet_fingerprint != self.packet_fingerprint
        ):
            raise ValueError("Approval request must belong to this resolution.")
        if self.approval_record is not None and (
            self.approval_request is None
            or self.approval_record.approval_id != self.approval_request.approval_id
            or self.approval_record.workflow_id != self.workflow_id
        ):
            raise ValueError("Approval record must answer this approval request.")
        if self.action_command is not None and (
            self.action_command.workflow_id != self.workflow_id
            or self.action_command.case_id != self.case_id
            or self.action_command.packet_fingerprint != self.packet_fingerprint
        ):
            raise ValueError("Action command must belong to this resolution.")
        if self.action_receipt is not None and (
            self.action_command is None
            or self.action_receipt.action_id != self.action_command.action_id
            or self.action_receipt.workflow_id != self.workflow_id
            or self.action_receipt.idempotency_key
            != self.action_command.idempotency_key
        ):
            raise ValueError("Action receipt must answer this action command.")
        if self.verification is not None and (
            self.action_command is None
            or self.verification.workflow_id != self.workflow_id
            or self.verification.expected != self.action_command
        ):
            raise ValueError("Verification must check this action command.")

        self._validate_status_shape()
        return self

    def _validate_status_shape(self) -> None:
        if self.status is ResolutionStatus.WAITING_APPROVAL:
            if self.approval_request is None or self.approval_record is not None:
                raise ValueError("Waiting resolutions require a pending approval.")
            if self.action_receipt is not None or self.verification is not None:
                raise ValueError("Waiting resolutions cannot have action outcomes.")
        elif self.status is ResolutionStatus.APPROVAL_REJECTED:
            if (
                self.approval_record is None
                or self.approval_record.decision is not ApprovalDecision.REJECTED
                or self.action_receipt is not None
                or self.verification is not None
            ):
                raise ValueError("Rejected resolutions require rejection only.")
        elif self.status is ResolutionStatus.READY_TO_EXECUTE:
            if (
                self.approval_record is None
                or self.approval_record.decision is not ApprovalDecision.APPROVED
                or self.action_command is None
                or self.action_receipt is not None
                or self.verification is not None
            ):
                raise ValueError("Executable resolutions require approved action only.")
        elif self.status is ResolutionStatus.EXECUTION_FAILED:
            if (
                self.action_receipt is None
                or self.action_receipt.status is not ActionStatus.FAILED
                or self.verification is not None
            ):
                raise ValueError("Execution failures require a failed receipt.")
        elif self.status is ResolutionStatus.READY_TO_VERIFY:
            if (
                self.action_receipt is None
                or self.action_receipt.status is not ActionStatus.SUCCEEDED
                or self.verification is not None
            ):
                raise ValueError("Verification requires a successful action receipt.")
        elif self.status is ResolutionStatus.COMPLETED_VERIFIED:
            if (
                self.action_receipt is None
                or self.action_receipt.status is not ActionStatus.SUCCEEDED
                or self.verification is None
                or self.verification.status is not VerificationStatus.VERIFIED
            ):
                raise ValueError(
                    "Verified completion requires successful verification."
                )
        elif self.status is ResolutionStatus.VERIFICATION_FAILED:
            if (
                self.action_receipt is None
                or self.action_receipt.status is not ActionStatus.SUCCEEDED
                or self.verification is None
                or self.verification.status is VerificationStatus.VERIFIED
            ):
                raise ValueError("Verification failure requires a failed verification.")
        elif (
            self.action_command is not None
            or self.action_receipt is not None
            or self.verification is not None
        ):
            raise ValueError("No-action completion cannot contain an action outcome.")


def packet_fingerprint(packet: DecisionPacket) -> str:
    payload = json.dumps(
        packet.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
