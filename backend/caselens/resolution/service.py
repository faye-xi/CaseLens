from datetime import datetime

from caselens.agent.case_review import CaseReviewResult
from caselens.domain.models import Case
from caselens.resolution.models import (
    ApprovalDecision,
    ApprovalRequest,
    ResolutionRun,
    ResolutionStatus,
)
from caselens.resolution.planning import (
    ResolutionPlanningError,
    packet_fingerprint,
    plan_refund_action,
)
from caselens.resolution.store import (
    IllegalTransitionError,
    SqliteResolutionStore,
)
from caselens.resolution.verifier import (
    RefundStateReader,
    verify_refund_state,
)


class ResolutionWorkflow:
    def __init__(
        self,
        store: SqliteResolutionStore,
        *,
        refund_reader: RefundStateReader | None = None,
    ) -> None:
        self._store = store
        self._refund_reader = refund_reader or store

    def start_resolution(
        self,
        case: Case,
        review: CaseReviewResult,
        *,
        workflow_id: str,
        created_at: datetime,
    ) -> ResolutionRun:
        packet = review.decision_packet
        if packet is None:
            raise ResolutionPlanningError(
                "Resolution requires a trusted decision packet."
            )
        action = plan_refund_action(
            case,
            review,
            workflow_id=workflow_id,
        )
        fingerprint = packet_fingerprint(packet)
        approval_request = None
        status = ResolutionStatus.COMPLETED_NO_ACTION
        if packet.requires_approval:
            approval_request = ApprovalRequest(
                approval_id=f"{workflow_id}:approval",
                workflow_id=workflow_id,
                case_id=case.case_id,
                packet_fingerprint=fingerprint,
                requested_at=created_at,
            )
            status = ResolutionStatus.WAITING_APPROVAL
        run = ResolutionRun(
            workflow_id=workflow_id,
            case_id=case.case_id,
            packet=packet,
            packet_fingerprint=fingerprint,
            status=status,
            created_at=created_at,
            updated_at=created_at,
            approval_request=approval_request,
            action_command=action,
        )
        return self._store.create_run(run)

    def decide_approval(
        self,
        workflow_id: str,
        decision: ApprovalDecision,
        *,
        decided_by: str,
        decided_at: datetime,
    ) -> ResolutionRun:
        return self._store.record_approval(
            workflow_id,
            decision,
            decided_by=decided_by,
            decided_at=decided_at,
        )

    def execute_action(
        self,
        workflow_id: str,
        *,
        executed_at: datetime,
    ) -> ResolutionRun:
        return self._store.execute_refund_once(
            workflow_id,
            executed_at=executed_at,
        )

    def verify_action(
        self,
        workflow_id: str,
        *,
        verified_at: datetime,
    ) -> ResolutionRun:
        run = self._store.get_run(workflow_id)
        if run.verification is not None:
            return run
        if (
            run.status is not ResolutionStatus.READY_TO_VERIFY
            or run.action_command is None
            or run.action_receipt is None
        ):
            raise IllegalTransitionError(
                f"Verification is not legal from state {run.status.value!r}."
            )
        if (
            verified_at.tzinfo is None
            or verified_at.utcoffset() is None
            or verified_at < run.action_receipt.completed_at
        ):
            raise IllegalTransitionError(
                "Verification time cannot precede execution time."
            )
        result = verify_refund_state(
            run.action_command,
            self._refund_reader,
            verified_at=verified_at,
        )
        return self._store.record_verification(workflow_id, result)
