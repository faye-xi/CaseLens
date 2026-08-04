from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from test_resolution_models import make_case, make_review

from caselens.resolution.models import (
    ActionErrorCode,
    ActionStatus,
    ApprovalDecision,
    ApprovalRequest,
    ResolutionRun,
    ResolutionStatus,
)
from caselens.resolution.planning import packet_fingerprint, plan_refund_action
from caselens.resolution.store import (
    IllegalTransitionError,
    ResolutionConflictError,
    SqliteResolutionStore,
)
from caselens.tools.models import (
    PaymentRecord,
    PaymentStatus,
    RefundRecord,
    RefundStatus,
)

CREATED_AT = datetime(2026, 8, 4, 13, 0, tzinfo=UTC)
DECIDED_AT = datetime(2026, 8, 4, 13, 5, tzinfo=UTC)
EXECUTED_AT = datetime(2026, 8, 4, 13, 10, tzinfo=UTC)
REPLAYED_AT = datetime(2026, 8, 4, 13, 15, tzinfo=UTC)


def make_waiting_run(
    *,
    workflow_id: str = "run-1",
    review_id: str = "review-1",
) -> ResolutionRun:
    case = make_case()
    review = make_review()
    packet = review.decision_packet
    assert packet is not None
    fingerprint = packet_fingerprint(packet)
    return ResolutionRun(
        workflow_id=workflow_id,
        review_id=review_id,
        case_id=case.case_id,
        packet=packet,
        packet_fingerprint=fingerprint,
        status=ResolutionStatus.WAITING_APPROVAL,
        created_at=CREATED_AT,
        updated_at=CREATED_AT,
        approval_request=ApprovalRequest(
            approval_id=f"{workflow_id}:approval",
            workflow_id=workflow_id,
            case_id=case.case_id,
            packet_fingerprint=fingerprint,
            requested_at=CREATED_AT,
        ),
        action_command=plan_refund_action(
            case,
            review,
            workflow_id=workflow_id,
        ),
    )


def make_payment(
    *,
    amount: Decimal = Decimal("50.00"),
    currency: str = "CNY",
    status: RefundStatus = RefundStatus.PROCESSING,
) -> PaymentRecord:
    return PaymentRecord(
        payment_id="payment-1",
        order_id="order-1",
        status=PaymentStatus.PAID,
        amount=Decimal("50.00"),
        currency="CNY",
        paid_at=CREATED_AT,
        refunds=(
            RefundRecord(
                refund_id="refund-1",
                status=status,
                amount=amount,
                currency=currency,
                requested_at=CREATED_AT,
                completed_at=(CREATED_AT if status is RefundStatus.SUCCEEDED else None),
            ),
        ),
    )


def approve(store: SqliteResolutionStore, workflow_id: str = "run-1") -> None:
    store.record_approval(
        workflow_id,
        ApprovalDecision.APPROVED,
        decided_by="reviewer-1",
        decided_at=DECIDED_AT,
    )


def test_run_survives_store_recreation(tmp_path: Path) -> None:
    database = tmp_path / "resolution.db"
    first = SqliteResolutionStore(database)
    first.create_run(make_waiting_run())
    first.close()

    second = SqliteResolutionStore(database)
    loaded = second.get_run("run-1")

    assert loaded == make_waiting_run()
    second.close()


def test_duplicate_workflow_id_is_rejected(tmp_path: Path) -> None:
    store = SqliteResolutionStore(tmp_path / "resolution.db")
    store.create_run(make_waiting_run())

    with pytest.raises(ResolutionConflictError, match="already exists"):
        store.create_run(make_waiting_run())

    store.close()


def test_one_review_cannot_start_two_resolution_workflows(tmp_path: Path) -> None:
    store = SqliteResolutionStore(tmp_path / "resolution.db")
    store.create_run(make_waiting_run())

    with pytest.raises(ResolutionConflictError, match="review"):
        store.create_run(make_waiting_run(workflow_id="run-2"))

    assert store.find_run_by_review_id("review-1") == make_waiting_run()
    assert store.find_run_by_review_id("missing-review") is None
    store.close()


def test_approved_action_becomes_ready_to_execute(tmp_path: Path) -> None:
    store = SqliteResolutionStore(tmp_path / "resolution.db")
    store.create_run(make_waiting_run())

    result = store.record_approval(
        "run-1",
        ApprovalDecision.APPROVED,
        decided_by="reviewer-1",
        decided_at=DECIDED_AT,
    )

    assert result.status is ResolutionStatus.READY_TO_EXECUTE
    assert result.approval_record is not None
    assert result.approval_record.decided_by == "reviewer-1"
    store.close()


def test_approval_time_cannot_precede_request(tmp_path: Path) -> None:
    store = SqliteResolutionStore(tmp_path / "resolution.db")
    store.create_run(make_waiting_run())

    with pytest.raises(IllegalTransitionError, match="time"):
        store.record_approval(
            "run-1",
            ApprovalDecision.APPROVED,
            decided_by="reviewer-1",
            decided_at=datetime(2026, 8, 4, 12, 59, tzinfo=UTC),
        )

    assert store.get_run("run-1").status is ResolutionStatus.WAITING_APPROVAL
    store.close()


def test_identical_approval_is_replayed_but_conflicting_decision_is_rejected(
    tmp_path: Path,
) -> None:
    store = SqliteResolutionStore(tmp_path / "resolution.db")
    store.create_run(make_waiting_run())
    first = store.record_approval(
        "run-1",
        ApprovalDecision.APPROVED,
        decided_by="reviewer-1",
        decided_at=DECIDED_AT,
    )

    replay = store.record_approval(
        "run-1",
        ApprovalDecision.APPROVED,
        decided_by="reviewer-1",
        decided_at=DECIDED_AT,
    )
    assert replay == first

    with pytest.raises(ResolutionConflictError, match="conflicts"):
        store.record_approval(
            "run-1",
            ApprovalDecision.REJECTED,
            decided_by="reviewer-1",
            decided_at=DECIDED_AT,
        )

    store.close()


def test_rejected_approval_is_terminal_without_action_receipt(tmp_path: Path) -> None:
    store = SqliteResolutionStore(tmp_path / "resolution.db")
    store.create_run(make_waiting_run())

    result = store.record_approval(
        "run-1",
        ApprovalDecision.REJECTED,
        decided_by="reviewer-1",
        decided_at=DECIDED_AT,
    )

    assert result.status is ResolutionStatus.APPROVAL_REJECTED
    assert result.action_receipt is None
    assert result.verification is None
    store.close()


def test_approved_refund_completion_changes_state_once(tmp_path: Path) -> None:
    store = SqliteResolutionStore(tmp_path / "resolution.db")
    store.seed_refunds((make_payment(),))
    store.create_run(make_waiting_run())
    approve(store)

    result = store.execute_refund_once("run-1", executed_at=EXECUTED_AT)

    assert result.status is ResolutionStatus.READY_TO_VERIFY
    assert result.action_receipt is not None
    assert result.action_receipt.status is ActionStatus.SUCCEEDED
    snapshot = store.get_refund("payment-1", "refund-1")
    assert snapshot.status is RefundStatus.SUCCEEDED
    assert snapshot.completed_at == EXECUTED_AT
    store.close()


def test_execution_before_approval_is_rejected_without_mutation(tmp_path: Path) -> None:
    store = SqliteResolutionStore(tmp_path / "resolution.db")
    store.seed_refunds((make_payment(),))
    store.create_run(make_waiting_run())

    with pytest.raises(IllegalTransitionError, match="not legal"):
        store.execute_refund_once("run-1", executed_at=EXECUTED_AT)

    assert store.get_refund("payment-1", "refund-1").status is RefundStatus.PROCESSING
    store.close()


def test_execution_time_cannot_precede_approval_without_mutation(
    tmp_path: Path,
) -> None:
    store = SqliteResolutionStore(tmp_path / "resolution.db")
    store.seed_refunds((make_payment(),))
    store.create_run(make_waiting_run())
    approve(store)

    with pytest.raises(IllegalTransitionError, match="time"):
        store.execute_refund_once(
            "run-1",
            executed_at=datetime(2026, 8, 4, 13, 1, tzinfo=UTC),
        )

    assert store.get_refund("payment-1", "refund-1").status is RefundStatus.PROCESSING
    assert store.get_run("run-1").status is ResolutionStatus.READY_TO_EXECUTE
    store.close()


def test_same_action_is_replayed_without_second_mutation(tmp_path: Path) -> None:
    store = SqliteResolutionStore(tmp_path / "resolution.db")
    store.seed_refunds((make_payment(),))
    store.create_run(make_waiting_run())
    approve(store)
    first = store.execute_refund_once("run-1", executed_at=EXECUTED_AT)

    replay = store.execute_refund_once("run-1", executed_at=REPLAYED_AT)

    assert first.action_receipt is not None
    assert replay.action_receipt is not None
    assert replay.action_receipt.replayed is True
    assert replay.action_receipt.receipt_id == first.action_receipt.receipt_id
    assert store.get_run("run-1").action_receipt == replay.action_receipt
    assert store.get_run("run-1").updated_at == REPLAYED_AT
    assert store.get_refund("payment-1", "refund-1").completed_at == EXECUTED_AT
    store.close()


def test_same_idempotency_key_with_different_command_is_rejected(
    tmp_path: Path,
) -> None:
    store = SqliteResolutionStore(tmp_path / "resolution.db")
    store.seed_refunds((make_payment(),))
    store.create_run(make_waiting_run(workflow_id="run-1"))
    approve(store, "run-1")
    store.execute_refund_once("run-1", executed_at=EXECUTED_AT)
    store.create_run(make_waiting_run(workflow_id="run-2", review_id="review-2"))
    approve(store, "run-2")

    with pytest.raises(ResolutionConflictError, match="idempotency"):
        store.execute_refund_once("run-2", executed_at=REPLAYED_AT)

    store.close()


@pytest.mark.parametrize(
    ("payment", "expected_code"),
    [
        (make_payment(amount=Decimal("60.00")), ActionErrorCode.AMOUNT_MISMATCH),
        (make_payment(currency="USD"), ActionErrorCode.CURRENCY_MISMATCH),
        (
            make_payment(status=RefundStatus.SUCCEEDED),
            ActionErrorCode.INVALID_REFUND_STATE,
        ),
    ],
)
def test_refund_precondition_failure_is_terminal_without_mutation(
    tmp_path: Path,
    payment: PaymentRecord,
    expected_code: ActionErrorCode,
) -> None:
    store = SqliteResolutionStore(tmp_path / f"{expected_code.value}.db")
    store.seed_refunds((payment,))
    store.create_run(make_waiting_run())
    approve(store)
    before = store.get_refund("payment-1", "refund-1")

    result = store.execute_refund_once("run-1", executed_at=EXECUTED_AT)

    assert result.status is ResolutionStatus.EXECUTION_FAILED
    assert result.action_receipt is not None
    assert result.action_receipt.error_code is expected_code
    assert store.get_refund("payment-1", "refund-1") == before
    store.close()


def test_missing_refund_is_a_durable_failed_execution(tmp_path: Path) -> None:
    store = SqliteResolutionStore(tmp_path / "missing.db")
    payment = make_payment().model_copy(update={"refunds": ()})
    store.seed_refunds((payment,))
    store.create_run(make_waiting_run())
    approve(store)

    result = store.execute_refund_once("run-1", executed_at=EXECUTED_AT)
    replay = store.execute_refund_once("run-1", executed_at=REPLAYED_AT)

    assert result.status is ResolutionStatus.EXECUTION_FAILED
    assert result.action_receipt is not None
    assert result.action_receipt.error_code is ActionErrorCode.REFUND_NOT_FOUND
    assert replay.action_receipt is not None
    assert replay.action_receipt.replayed is True
    store.close()


def test_action_and_refund_state_survive_store_recreation(tmp_path: Path) -> None:
    database = tmp_path / "resolution.db"
    first = SqliteResolutionStore(database)
    first.seed_refunds((make_payment(),))
    first.create_run(make_waiting_run())
    approve(first)
    executed = first.execute_refund_once("run-1", executed_at=EXECUTED_AT)
    first.close()

    second = SqliteResolutionStore(database)
    assert second.get_run("run-1") == executed
    assert second.get_refund("payment-1", "refund-1").status is RefundStatus.SUCCEEDED
    second.close()
