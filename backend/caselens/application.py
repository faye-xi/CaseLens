from datetime import UTC, datetime
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from caselens.agent.case_review import CaseReviewResult
from caselens.domain.models import Case
from caselens.model.protocol import ModelRole, ModelTrace
from caselens.persistence.repository import (
    RecordConflictError,
    RecordNotFoundError,
    SqliteRepository,
    StoredCaseReview,
)
from caselens.resolution.models import (
    ApprovalDecision,
    ResolutionRun,
)
from caselens.resolution.service import ResolutionWorkflow
from caselens.resolution.store import (
    ResolutionConflictError,
    ResolutionNotFoundError,
    SqliteResolutionStore,
)
from caselens.tools.protocol import ToolTrace


class ApplicationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ReviewStartResult(ApplicationModel):
    created: bool
    review: StoredCaseReview
    workflow: ResolutionRun | None = None


class WorkflowReplay(ApplicationModel):
    case: Case
    review: StoredCaseReview
    resolution: ResolutionRun
    trace: "ReplayTrace"


class ReplayTrace(ApplicationModel):
    model_traces: tuple[ModelTrace, ...] = ()
    tool_traces: tuple[ToolTrace, ...] = ()


class ReplayIntegrityError(RuntimeError):
    """Stored replay resources do not belong to one workflow lineage."""


class CaseReviewer(Protocol):
    def review(
        self,
        case: Case,
        *,
        collected_at: datetime,
        request_id_prefix: str,
    ) -> CaseReviewResult: ...


class Clock(Protocol):
    def __call__(self) -> datetime: ...


def utc_now() -> datetime:
    return datetime.now(UTC)


class CaseLensApplication:
    def __init__(
        self,
        repository: SqliteRepository,
        resolution_store: SqliteResolutionStore,
        resolution_workflow: ResolutionWorkflow,
        reviewer: CaseReviewer,
        *,
        clock: Clock = utc_now,
    ) -> None:
        self._repository = repository
        self._resolution_store = resolution_store
        self._resolution_workflow = resolution_workflow
        self._reviewer = reviewer
        self._clock = clock

    def close(self) -> None:
        self._repository.close()
        self._resolution_store.close()

    def list_cases(self) -> tuple[Case, ...]:
        return self._repository.list_cases()

    def get_case(self, case_id: str) -> Case:
        return self._repository.get_case(case_id)

    def get_review(self, review_id: str) -> StoredCaseReview:
        return self._repository.get_case_review(review_id)

    def get_workflow(self, workflow_id: str) -> ResolutionRun:
        return self._resolution_store.get_run(workflow_id)

    def start_review(
        self,
        case_id: str,
        *,
        review_id: str,
        workflow_id: str,
    ) -> ReviewStartResult:
        case = self._repository.get_case(case_id)
        try:
            stored = self._repository.get_case_review(review_id)
        except RecordNotFoundError:
            stored = None
        if stored is not None:
            return self._resume_review(case, stored, workflow_id=workflow_id)

        try:
            self._resolution_store.get_run(workflow_id)
        except ResolutionNotFoundError:
            pass
        else:
            raise ResolutionConflictError(
                f"Resolution workflow {workflow_id!r} already exists."
            )

        created_at = self._clock()
        result = self._reviewer.review(
            case,
            collected_at=created_at,
            request_id_prefix=review_id,
        )
        try:
            stored = self._repository.save_case_review(
                review_id,
                case,
                result,
                created_at=created_at,
            )
        except RecordConflictError:
            durable = self._repository.get_case_review(review_id)
            if durable.case_id != case.case_id or durable.result != result:
                raise
            return self._resume_review(
                case,
                durable,
                workflow_id=workflow_id,
            )
        workflow = None
        if result.decision_packet is not None:
            try:
                workflow = self._resolution_workflow.start_resolution(
                    case,
                    result,
                    review_id=review_id,
                    workflow_id=workflow_id,
                    created_at=created_at,
                )
            except ResolutionConflictError:
                return self._resume_review(
                    case,
                    stored,
                    workflow_id=workflow_id,
                    created=True,
                )
        return ReviewStartResult(created=True, review=stored, workflow=workflow)

    def _resume_review(
        self,
        case: Case,
        stored: StoredCaseReview,
        *,
        workflow_id: str,
        created: bool = False,
    ) -> ReviewStartResult:
        if stored.case_id != case.case_id:
            raise ResolutionConflictError("The review ID belongs to a different case.")
        result = stored.result
        if result.decision_packet is None:
            return ReviewStartResult(created=created, review=stored)

        existing = self._resolution_store.find_run_by_review_id(stored.review_id)
        if existing is not None:
            if (
                existing.workflow_id != workflow_id
                or existing.case_id != stored.case_id
                or existing.packet != result.decision_packet
            ):
                raise ResolutionConflictError(
                    "The review already belongs to a different resolution workflow."
                )
            return ReviewStartResult(
                created=created,
                review=stored,
                workflow=existing,
            )

        try:
            workflow = self._resolution_workflow.start_resolution(
                case,
                result,
                review_id=stored.review_id,
                workflow_id=workflow_id,
                created_at=stored.created_at,
            )
        except ResolutionConflictError:
            workflow = self._resolution_store.find_run_by_review_id(stored.review_id)
            if workflow is None:
                raise
            if (
                workflow.workflow_id != workflow_id
                or workflow.case_id != stored.case_id
                or workflow.packet != result.decision_packet
            ):
                raise ResolutionConflictError(
                    "The review already belongs to a different resolution workflow."
                )
        return ReviewStartResult(
            created=created,
            review=stored,
            workflow=workflow,
        )

    def decide_approval(
        self,
        workflow_id: str,
        decision: ApprovalDecision,
        *,
        decided_by: str,
    ) -> ResolutionRun:
        return self._resolution_workflow.decide_approval(
            workflow_id,
            decision,
            decided_by=decided_by,
            decided_at=self._clock(),
        )

    def execute_action(self, workflow_id: str) -> ResolutionRun:
        return self._resolution_workflow.execute_action(
            workflow_id,
            executed_at=self._clock(),
        )

    def verify_action(self, workflow_id: str) -> ResolutionRun:
        return self._resolution_workflow.verify_action(
            workflow_id,
            verified_at=self._clock(),
        )

    def get_workflow_replay(self, workflow_id: str) -> WorkflowReplay:
        resolution = self._resolution_store.get_run(workflow_id)
        review = self._repository.get_case_review(resolution.review_id)
        case = self._repository.get_case(resolution.case_id)
        if (
            review.case_id != resolution.case_id
            or review.result.decision_packet != resolution.packet
            or case.case_id != review.case_id
        ):
            raise ReplayIntegrityError(
                "The stored case, review, and resolution lineage is inconsistent."
            )
        return WorkflowReplay(
            case=case,
            review=review,
            resolution=resolution,
            trace=_replay_trace(review.result),
        )


def _replay_trace(result: CaseReviewResult) -> ReplayTrace:
    tool_traces = tuple(
        message.tool_result.trace
        for message in result.investigation.messages
        if message.role is ModelRole.TOOL and message.tool_result is not None
    )
    model_traces = result.investigation.model_traces
    if result.draft_trace is not None:
        model_traces += (result.draft_trace,)
    return ReplayTrace(
        model_traces=model_traces,
        tool_traces=tool_traces,
    )
