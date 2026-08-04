from collections.abc import Iterable
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import String, Text, create_engine, event
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from caselens.resolution.models import (
    ActionErrorCode,
    ActionReceipt,
    ActionStatus,
    ApprovalDecision,
    ApprovalRecord,
    RefundActionCommand,
    RefundSnapshot,
    ResolutionRun,
    ResolutionStatus,
    VerificationResult,
    VerificationStatus,
)
from caselens.resolution.verifier import RefundStateReadError
from caselens.tools.models import PaymentRecord, RefundStatus


class ResolutionStoreError(RefundStateReadError):
    """The durable resolution state could not be handled safely."""


class ResolutionNotFoundError(ResolutionStoreError):
    """The requested resolution workflow does not exist."""


class ResolutionConflictError(ResolutionStoreError):
    """A repeated request conflicts with durable workflow state."""


class IllegalTransitionError(ResolutionStoreError):
    """The requested operation is not legal from the current state."""


class ResolutionBase(DeclarativeBase):
    pass


class ResolutionRunRow(ResolutionBase):
    __tablename__ = "resolution_runs"

    workflow_id: Mapped[str] = mapped_column(String, primary_key=True)
    run_json: Mapped[str] = mapped_column(Text, nullable=False)


class SimulatedRefundRow(ResolutionBase):
    __tablename__ = "simulated_refunds"

    payment_id: Mapped[str] = mapped_column(String, primary_key=True)
    refund_id: Mapped[str] = mapped_column(String, primary_key=True)
    status: Mapped[str] = mapped_column(String, nullable=False)
    amount: Mapped[str] = mapped_column(Text, nullable=False)
    currency: Mapped[str] = mapped_column(String, nullable=False)
    requested_at: Mapped[str] = mapped_column(String, nullable=False)
    completed_at: Mapped[str | None] = mapped_column(String)


class ActionExecutionRow(ResolutionBase):
    __tablename__ = "action_executions"

    idempotency_key: Mapped[str] = mapped_column(String, primary_key=True)
    command_json: Mapped[str] = mapped_column(Text, nullable=False)
    receipt_json: Mapped[str] = mapped_column(Text, nullable=False)


class SqliteResolutionStore:
    def __init__(self, database_path: str | Path) -> None:
        path = Path(database_path)
        self._engine = create_engine(f"sqlite:///{path.as_posix()}")
        event.listen(self._engine, "connect", _enable_sqlite_foreign_keys)
        ResolutionBase.metadata.create_all(self._engine)
        self._session_factory = sessionmaker(self._engine)

    def close(self) -> None:
        self._engine.dispose()

    def create_run(self, run: ResolutionRun) -> ResolutionRun:
        try:
            with self._session_factory.begin() as session:
                if session.get(ResolutionRunRow, run.workflow_id) is not None:
                    raise ResolutionConflictError(
                        f"Resolution workflow {run.workflow_id!r} already exists."
                    )
                session.add(
                    ResolutionRunRow(
                        workflow_id=run.workflow_id,
                        run_json=run.model_dump_json(),
                    )
                )
        except ResolutionConflictError:
            raise
        except IntegrityError as error:
            raise ResolutionConflictError(
                "The resolution conflicts with stored workflow state."
            ) from error
        except SQLAlchemyError as error:
            raise ResolutionStoreError(
                "The resolution workflow could not be stored."
            ) from error
        return run

    def get_run(self, workflow_id: str) -> ResolutionRun:
        try:
            with self._session_factory() as session:
                row = session.get(ResolutionRunRow, workflow_id)
                if row is None:
                    raise ResolutionNotFoundError(
                        f"Resolution workflow {workflow_id!r} was not found."
                    )
                return _row_to_run(row)
        except (ResolutionNotFoundError, ResolutionStoreError):
            raise
        except SQLAlchemyError as error:
            raise ResolutionStoreError(
                "The resolution workflow could not be loaded."
            ) from error

    def seed_refunds(self, payments: Iterable[PaymentRecord]) -> None:
        try:
            with self._session_factory.begin() as session:
                for payment in payments:
                    for refund in payment.refunds:
                        snapshot = RefundSnapshot(
                            payment_id=payment.payment_id,
                            refund_id=refund.refund_id,
                            status=refund.status,
                            amount=refund.amount,
                            currency=refund.currency,
                            requested_at=refund.requested_at,
                            completed_at=refund.completed_at,
                        )
                        existing = session.get(
                            SimulatedRefundRow,
                            (payment.payment_id, refund.refund_id),
                        )
                        if existing is not None:
                            if _row_to_refund(existing) != snapshot:
                                raise ResolutionConflictError(
                                    "The simulated refund conflicts with stored state."
                                )
                            continue
                        session.add(_refund_to_row(snapshot))
        except ResolutionConflictError:
            raise
        except IntegrityError as error:
            raise ResolutionConflictError(
                "The simulated refund conflicts with stored state."
            ) from error
        except SQLAlchemyError as error:
            raise ResolutionStoreError(
                "The simulated refunds could not be stored."
            ) from error

    def get_refund(self, payment_id: str, refund_id: str) -> RefundSnapshot:
        try:
            with self._session_factory() as session:
                row = session.get(SimulatedRefundRow, (payment_id, refund_id))
                if row is None:
                    raise ResolutionNotFoundError("The simulated refund was not found.")
                return _row_to_refund(row)
        except (ResolutionNotFoundError, ResolutionStoreError):
            raise
        except SQLAlchemyError as error:
            raise ResolutionStoreError(
                "The simulated refund could not be loaded."
            ) from error

    def record_approval(
        self,
        workflow_id: str,
        decision: ApprovalDecision,
        *,
        decided_by: str,
        decided_at: datetime,
    ) -> ResolutionRun:
        try:
            with self._session_factory.begin() as session:
                row = session.get(ResolutionRunRow, workflow_id)
                if row is None:
                    raise ResolutionNotFoundError(
                        f"Resolution workflow {workflow_id!r} was not found."
                    )
                run = _row_to_run(row)
                request = run.approval_request
                if request is None:
                    raise IllegalTransitionError(
                        "This resolution does not have an approval request."
                    )
                _require_aware_time(decided_at, "Approval")
                if decided_at < request.requested_at:
                    raise IllegalTransitionError(
                        "Approval time cannot precede the approval request."
                    )
                record = ApprovalRecord(
                    approval_id=request.approval_id,
                    workflow_id=workflow_id,
                    decision=decision,
                    decided_by=decided_by,
                    decided_at=decided_at,
                )
                if run.approval_record is not None:
                    if run.approval_record == record:
                        return run
                    raise ResolutionConflictError(
                        "The repeated approval conflicts with the stored decision."
                    )
                if run.status is not ResolutionStatus.WAITING_APPROVAL:
                    raise IllegalTransitionError(
                        f"Approval is not legal from state {run.status.value!r}."
                    )
                if decision is ApprovalDecision.REJECTED:
                    next_status = ResolutionStatus.APPROVAL_REJECTED
                elif run.action_command is not None:
                    next_status = ResolutionStatus.READY_TO_EXECUTE
                else:
                    next_status = ResolutionStatus.COMPLETED_NO_ACTION
                updated = run.model_copy(
                    update={
                        "status": next_status,
                        "updated_at": decided_at,
                        "approval_record": record,
                    }
                )
                updated = ResolutionRun.model_validate(updated.model_dump())
                row.run_json = updated.model_dump_json()
                return updated
        except (
            IllegalTransitionError,
            ResolutionConflictError,
            ResolutionNotFoundError,
        ):
            raise
        except IntegrityError as error:
            raise ResolutionConflictError(
                "The approval conflicts with stored workflow state."
            ) from error
        except SQLAlchemyError as error:
            raise ResolutionStoreError(
                "The approval decision could not be stored."
            ) from error

    def execute_refund_once(
        self,
        workflow_id: str,
        *,
        executed_at: datetime,
    ) -> ResolutionRun:
        try:
            with self._session_factory.begin() as session:
                run_row = session.get(ResolutionRunRow, workflow_id)
                if run_row is None:
                    raise ResolutionNotFoundError(
                        f"Resolution workflow {workflow_id!r} was not found."
                    )
                run = _row_to_run(run_row)
                command = run.action_command
                if command is None:
                    raise IllegalTransitionError(
                        "This resolution does not contain a refund action."
                    )
                if run.action_receipt is not None:
                    replayed = run.action_receipt.model_copy(update={"replayed": True})
                    return ResolutionRun.model_validate(
                        run.model_copy(update={"action_receipt": replayed}).model_dump()
                    )
                if run.status is not ResolutionStatus.READY_TO_EXECUTE:
                    raise IllegalTransitionError(
                        f"Refund execution is not legal from state {run.status.value!r}."
                    )
                _require_aware_time(executed_at, "Execution")
                approval = run.approval_record
                assert approval is not None
                if executed_at < approval.decided_at:
                    raise IllegalTransitionError(
                        "Execution time cannot precede approval time."
                    )

                execution = session.get(
                    ActionExecutionRow,
                    command.idempotency_key,
                )
                if execution is not None:
                    stored_command = RefundActionCommand.model_validate_json(
                        execution.command_json
                    )
                    if stored_command != command:
                        raise ResolutionConflictError(
                            "The idempotency key conflicts with another action."
                        )
                    stored_receipt = ActionReceipt.model_validate_json(
                        execution.receipt_json
                    )
                    updated = _run_with_receipt(run, stored_receipt, executed_at)
                    run_row.run_json = updated.model_dump_json()
                    return updated

                refund_row = session.get(
                    SimulatedRefundRow,
                    (command.payment_id, command.refund_id),
                )
                error = _refund_precondition_error(refund_row, command)
                if error is None:
                    assert refund_row is not None
                    refund_row.status = RefundStatus.SUCCEEDED.value
                    refund_row.completed_at = executed_at.isoformat()
                    receipt = _action_receipt(
                        command,
                        status=ActionStatus.SUCCEEDED,
                        completed_at=executed_at,
                    )
                else:
                    error_code, message = error
                    receipt = _action_receipt(
                        command,
                        status=ActionStatus.FAILED,
                        completed_at=executed_at,
                        error_code=error_code,
                        error_message=message,
                    )

                session.add(
                    ActionExecutionRow(
                        idempotency_key=command.idempotency_key,
                        command_json=command.model_dump_json(),
                        receipt_json=receipt.model_dump_json(),
                    )
                )
                updated = _run_with_receipt(run, receipt, executed_at)
                run_row.run_json = updated.model_dump_json()
                return updated
        except (
            IllegalTransitionError,
            ResolutionConflictError,
            ResolutionNotFoundError,
        ):
            raise
        except IntegrityError as error:
            raise ResolutionConflictError(
                "The idempotent action conflicts with stored state."
            ) from error
        except SQLAlchemyError as error:
            raise ResolutionStoreError(
                "The simulated refund action could not be executed."
            ) from error

    def record_verification(
        self,
        workflow_id: str,
        result: VerificationResult,
    ) -> ResolutionRun:
        try:
            with self._session_factory.begin() as session:
                row = session.get(ResolutionRunRow, workflow_id)
                if row is None:
                    raise ResolutionNotFoundError(
                        f"Resolution workflow {workflow_id!r} was not found."
                    )
                run = _row_to_run(row)
                if run.verification is not None:
                    if run.verification == result:
                        return run
                    raise ResolutionConflictError(
                        "The verification conflicts with the stored result."
                    )
                if run.status is not ResolutionStatus.READY_TO_VERIFY:
                    raise IllegalTransitionError(
                        f"Verification is not legal from state {run.status.value!r}."
                    )
                receipt = run.action_receipt
                assert receipt is not None
                if result.verified_at < receipt.completed_at:
                    raise IllegalTransitionError(
                        "Verification time cannot precede execution time."
                    )
                next_status = (
                    ResolutionStatus.COMPLETED_VERIFIED
                    if result.status is VerificationStatus.VERIFIED
                    else ResolutionStatus.VERIFICATION_FAILED
                )
                updated = run.model_copy(
                    update={
                        "status": next_status,
                        "updated_at": result.verified_at,
                        "verification": result,
                    }
                )
                updated = ResolutionRun.model_validate(updated.model_dump())
                row.run_json = updated.model_dump_json()
                return updated
        except (
            IllegalTransitionError,
            ResolutionConflictError,
            ResolutionNotFoundError,
        ):
            raise
        except SQLAlchemyError as error:
            raise ResolutionStoreError(
                "The verification result could not be stored."
            ) from error


def _row_to_run(row: ResolutionRunRow) -> ResolutionRun:
    try:
        return ResolutionRun.model_validate_json(row.run_json)
    except ValueError as error:
        raise ResolutionStoreError(
            "The stored resolution workflow is invalid."
        ) from error


def _refund_to_row(snapshot: RefundSnapshot) -> SimulatedRefundRow:
    return SimulatedRefundRow(
        payment_id=snapshot.payment_id,
        refund_id=snapshot.refund_id,
        status=snapshot.status.value,
        amount=str(snapshot.amount),
        currency=snapshot.currency,
        requested_at=snapshot.requested_at.isoformat(),
        completed_at=(
            snapshot.completed_at.isoformat()
            if snapshot.completed_at is not None
            else None
        ),
    )


def _row_to_refund(row: SimulatedRefundRow) -> RefundSnapshot:
    return RefundSnapshot(
        payment_id=row.payment_id,
        refund_id=row.refund_id,
        status=row.status,
        amount=Decimal(row.amount),
        currency=row.currency,
        requested_at=datetime.fromisoformat(row.requested_at),
        completed_at=(
            datetime.fromisoformat(row.completed_at)
            if row.completed_at is not None
            else None
        ),
    )


def _refund_precondition_error(
    refund_row: SimulatedRefundRow | None,
    command: RefundActionCommand,
) -> tuple[ActionErrorCode, str] | None:
    if refund_row is None:
        return ActionErrorCode.REFUND_NOT_FOUND, "The target refund was not found."
    refund = _row_to_refund(refund_row)
    if refund.amount != command.amount:
        return (
            ActionErrorCode.AMOUNT_MISMATCH,
            "The target refund amount does not match the approved action.",
        )
    if refund.currency != command.currency:
        return (
            ActionErrorCode.CURRENCY_MISMATCH,
            "The target refund currency does not match the approved action.",
        )
    if refund.status not in {RefundStatus.REQUESTED, RefundStatus.PROCESSING}:
        return (
            ActionErrorCode.INVALID_REFUND_STATE,
            "The target refund is not in an executable state.",
        )
    return None


def _action_receipt(
    command: RefundActionCommand,
    *,
    status: ActionStatus,
    completed_at: datetime,
    error_code: ActionErrorCode | None = None,
    error_message: str | None = None,
) -> ActionReceipt:
    return ActionReceipt(
        receipt_id=f"{command.action_id}:receipt",
        action_id=command.action_id,
        workflow_id=command.workflow_id,
        idempotency_key=command.idempotency_key,
        status=status,
        completed_at=completed_at,
        error_code=error_code,
        error_message=error_message,
    )


def _run_with_receipt(
    run: ResolutionRun,
    receipt: ActionReceipt,
    updated_at: datetime,
) -> ResolutionRun:
    status = (
        ResolutionStatus.READY_TO_VERIFY
        if receipt.status is ActionStatus.SUCCEEDED
        else ResolutionStatus.EXECUTION_FAILED
    )
    updated = run.model_copy(
        update={
            "status": status,
            "updated_at": updated_at,
            "action_receipt": receipt,
        }
    )
    return ResolutionRun.model_validate(updated.model_dump())


def _enable_sqlite_foreign_keys(
    dbapi_connection: object,
    _connection_record: object,
) -> None:
    cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def _require_aware_time(value: datetime, operation: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise IllegalTransitionError(f"{operation} time must be timezone-aware.")
