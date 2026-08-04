from datetime import UTC, datetime
from pathlib import Path

import pytest
from test_resolution_models import make_case, make_review
from test_resolution_store import make_payment

from caselens.resolution.models import (
    ApprovalDecision,
    RefundSnapshot,
    ResolutionStatus,
    VerificationStatus,
)
from caselens.resolution.service import ResolutionWorkflow
from caselens.resolution.store import (
    IllegalTransitionError,
    SqliteResolutionStore,
)
from caselens.resolution.verifier import (
    RefundStateReadError,
    verify_refund_state,
)
from caselens.tools.models import RefundStatus

CREATED_AT = datetime(2026, 8, 4, 13, 0, tzinfo=UTC)
DECIDED_AT = datetime(2026, 8, 4, 13, 5, tzinfo=UTC)
EXECUTED_AT = datetime(2026, 8, 4, 13, 10, tzinfo=UTC)
VERIFIED_AT = datetime(2026, 8, 4, 13, 11, tzinfo=UTC)


class FixedReader:
    def __init__(self, snapshot: RefundSnapshot) -> None:
        self._snapshot = snapshot

    def get_refund(self, payment_id: str, refund_id: str) -> RefundSnapshot:
        return self._snapshot


class FailingReader:
    def get_refund(self, payment_id: str, refund_id: str) -> RefundSnapshot:
        raise RefundStateReadError("The refund source is unavailable.")


def make_snapshot(
    *,
    status: RefundStatus = RefundStatus.SUCCEEDED,
    completed_at: datetime | None = EXECUTED_AT,
) -> RefundSnapshot:
    return RefundSnapshot(
        payment_id="payment-1",
        refund_id="refund-1",
        status=status,
        amount="50.00",
        currency="CNY",
        requested_at=CREATED_AT,
        completed_at=completed_at,
    )


def start_approved_workflow(
    store: SqliteResolutionStore,
    *,
    reader=None,
) -> ResolutionWorkflow:
    store.seed_refunds((make_payment(),))
    workflow = ResolutionWorkflow(store, refund_reader=reader)
    workflow.start_resolution(
        make_case(),
        make_review(),
        workflow_id="run-1",
        created_at=CREATED_AT,
    )
    workflow.decide_approval(
        "run-1",
        ApprovalDecision.APPROVED,
        decided_by="reviewer-1",
        decided_at=DECIDED_AT,
    )
    return workflow


def test_verifier_rejects_success_claim_when_refund_is_still_processing() -> None:
    review = make_review()
    packet = review.decision_packet
    assert packet is not None
    from caselens.resolution.planning import plan_refund_action

    command = plan_refund_action(make_case(), review, workflow_id="run-1")
    assert command is not None

    result = verify_refund_state(
        command,
        FixedReader(make_snapshot(status=RefundStatus.PROCESSING, completed_at=None)),
        verified_at=VERIFIED_AT,
    )

    assert result.status is VerificationStatus.MISMATCH
    assert result.mismatches == ("status", "completed_at")


def test_verifier_turns_read_failure_into_safe_result() -> None:
    from caselens.resolution.planning import plan_refund_action

    command = plan_refund_action(make_case(), make_review(), workflow_id="run-1")
    assert command is not None

    result = verify_refund_state(
        command,
        FailingReader(),
        verified_at=VERIFIED_AT,
    )

    assert result.status is VerificationStatus.READ_ERROR
    assert result.actual is None
    assert result.error_message == "The refund state could not be read."


def test_high_risk_resolution_waits_without_mutating_refund(tmp_path: Path) -> None:
    store = SqliteResolutionStore(tmp_path / "resolution.db")
    store.seed_refunds((make_payment(),))
    workflow = ResolutionWorkflow(store)

    result = workflow.start_resolution(
        make_case(),
        make_review(),
        workflow_id="run-1",
        created_at=CREATED_AT,
    )

    assert result.status is ResolutionStatus.WAITING_APPROVAL
    assert store.get_refund("payment-1", "refund-1").status is RefundStatus.PROCESSING
    store.close()


def test_rejected_resolution_never_executes(tmp_path: Path) -> None:
    store = SqliteResolutionStore(tmp_path / "resolution.db")
    store.seed_refunds((make_payment(),))
    workflow = ResolutionWorkflow(store)
    workflow.start_resolution(
        make_case(), make_review(), workflow_id="run-1", created_at=CREATED_AT
    )
    rejected = workflow.decide_approval(
        "run-1",
        ApprovalDecision.REJECTED,
        decided_by="reviewer-1",
        decided_at=DECIDED_AT,
    )

    with pytest.raises(IllegalTransitionError):
        workflow.execute_action("run-1", executed_at=EXECUTED_AT)

    assert rejected.status is ResolutionStatus.APPROVAL_REJECTED
    assert store.get_refund("payment-1", "refund-1").status is RefundStatus.PROCESSING
    store.close()


def test_approved_action_requires_matching_read_back_for_success(
    tmp_path: Path,
) -> None:
    store = SqliteResolutionStore(tmp_path / "resolution.db")
    workflow = start_approved_workflow(store)
    executed = workflow.execute_action("run-1", executed_at=EXECUTED_AT)

    result = workflow.verify_action("run-1", verified_at=VERIFIED_AT)

    assert executed.status is ResolutionStatus.READY_TO_VERIFY
    assert result.status is ResolutionStatus.COMPLETED_VERIFIED
    assert result.verification is not None
    assert result.verification.status is VerificationStatus.VERIFIED
    store.close()


def test_mismatched_read_back_is_terminal_verification_failure(tmp_path: Path) -> None:
    store = SqliteResolutionStore(tmp_path / "resolution.db")
    workflow = start_approved_workflow(
        store,
        reader=FixedReader(
            make_snapshot(status=RefundStatus.PROCESSING, completed_at=None)
        ),
    )
    workflow.execute_action("run-1", executed_at=EXECUTED_AT)

    result = workflow.verify_action("run-1", verified_at=VERIFIED_AT)

    assert result.status is ResolutionStatus.VERIFICATION_FAILED
    assert result.verification is not None
    assert result.verification.status is VerificationStatus.MISMATCH
    store.close()


def test_read_failure_is_terminal_verification_failure(tmp_path: Path) -> None:
    store = SqliteResolutionStore(tmp_path / "resolution.db")
    workflow = start_approved_workflow(store, reader=FailingReader())
    workflow.execute_action("run-1", executed_at=EXECUTED_AT)

    result = workflow.verify_action("run-1", verified_at=VERIFIED_AT)

    assert result.status is ResolutionStatus.VERIFICATION_FAILED
    assert result.verification is not None
    assert result.verification.status is VerificationStatus.READ_ERROR
    store.close()


def test_verification_time_cannot_precede_action(tmp_path: Path) -> None:
    store = SqliteResolutionStore(tmp_path / "resolution.db")
    workflow = start_approved_workflow(store)
    workflow.execute_action("run-1", executed_at=EXECUTED_AT)

    with pytest.raises(IllegalTransitionError, match="time"):
        workflow.verify_action(
            "run-1",
            verified_at=datetime(2026, 8, 4, 13, 9, tzinfo=UTC),
        )

    assert store.get_run("run-1").status is ResolutionStatus.READY_TO_VERIFY
    store.close()


def test_low_risk_non_action_packet_completes_without_approval(tmp_path: Path) -> None:
    store = SqliteResolutionStore(tmp_path / "resolution.db")
    workflow = ResolutionWorkflow(store)

    result = workflow.start_resolution(
        make_case(),
        make_review(recommendation="deny_refund"),
        workflow_id="run-1",
        created_at=CREATED_AT,
    )

    assert result.status is ResolutionStatus.COMPLETED_NO_ACTION
    assert result.approval_request is None
    assert result.action_command is None
    store.close()


def test_high_risk_non_action_packet_waits_then_completes_without_action(
    tmp_path: Path,
) -> None:
    store = SqliteResolutionStore(tmp_path / "resolution.db")
    workflow = ResolutionWorkflow(store)
    waiting = workflow.start_resolution(
        make_case(),
        make_review(recommendation="deny_refund", risk_level="high"),
        workflow_id="run-1",
        created_at=CREATED_AT,
    )

    completed = workflow.decide_approval(
        "run-1",
        ApprovalDecision.APPROVED,
        decided_by="reviewer-1",
        decided_at=DECIDED_AT,
    )

    assert waiting.status is ResolutionStatus.WAITING_APPROVAL
    assert waiting.action_command is None
    assert completed.status is ResolutionStatus.COMPLETED_NO_ACTION
    assert completed.action_receipt is None
    store.close()


def test_verified_workflow_survives_store_recreation(tmp_path: Path) -> None:
    database = tmp_path / "resolution.db"
    first = SqliteResolutionStore(database)
    workflow = start_approved_workflow(first)
    workflow.execute_action("run-1", executed_at=EXECUTED_AT)
    completed = workflow.verify_action("run-1", verified_at=VERIFIED_AT)
    first.close()

    second = SqliteResolutionStore(database)
    assert second.get_run("run-1") == completed
    second.close()
