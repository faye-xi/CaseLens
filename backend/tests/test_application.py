from datetime import UTC, datetime, timedelta

import pytest
from test_resolution_models import make_case, make_review
from test_resolution_store import make_payment

from caselens.agent.case_review import (
    CaseReviewError,
    CaseReviewResult,
    CaseReviewStatus,
    CaseReviewTerminationReason,
)
from caselens.agent.protocol import (
    InvestigationResult,
    InvestigationStatus,
    InvestigationTerminationReason,
)
from caselens.application import CaseLensApplication
from caselens.model.protocol import ModelError
from caselens.persistence.repository import RecordConflictError, SqliteRepository
from caselens.resolution.models import ApprovalDecision, ResolutionStatus
from caselens.resolution.service import ResolutionWorkflow
from caselens.resolution.store import (
    ResolutionConflictError,
    ResolutionStoreError,
    SqliteResolutionStore,
)

CREATED_AT = datetime(2026, 8, 4, 13, 0, tzinfo=UTC)
DECIDED_AT = CREATED_AT + timedelta(minutes=5)
EXECUTED_AT = CREATED_AT + timedelta(minutes=10)
VERIFIED_AT = CREATED_AT + timedelta(minutes=11)


class FixedReviewer:
    def __init__(self, result: CaseReviewResult) -> None:
        self.result = result
        self.calls: list[tuple[str, datetime, str]] = []

    def review(
        self,
        case,
        *,
        collected_at: datetime,
        request_id_prefix: str,
    ) -> CaseReviewResult:
        self.calls.append((case.case_id, collected_at, request_id_prefix))
        return self.result


class SequenceClock:
    def __init__(self, *values: datetime) -> None:
        self._values = iter(values)

    def __call__(self) -> datetime:
        return next(self._values)


class FailFirstStartWorkflow:
    def __init__(self, workflow: ResolutionWorkflow) -> None:
        self._workflow = workflow
        self.calls = 0

    def start_resolution(self, *args, **kwargs):
        self.calls += 1
        if self.calls == 1:
            raise ResolutionStoreError("Simulated workflow write failure.")
        return self._workflow.start_resolution(*args, **kwargs)

    def decide_approval(self, *args, **kwargs):
        return self._workflow.decide_approval(*args, **kwargs)

    def execute_action(self, *args, **kwargs):
        return self._workflow.execute_action(*args, **kwargs)

    def verify_action(self, *args, **kwargs):
        return self._workflow.verify_action(*args, **kwargs)


class ConcurrentWinnerRepository:
    def __init__(self, repository: SqliteRepository) -> None:
        self._repository = repository

    def save_case_review(self, *args, **kwargs):
        self._repository.save_case_review(*args, **kwargs)
        raise RecordConflictError("A concurrent request committed first.")

    def __getattr__(self, name):
        return getattr(self._repository, name)


class ConcurrentWinnerWorkflow:
    def __init__(self, workflow: ResolutionWorkflow) -> None:
        self._workflow = workflow

    def start_resolution(self, *args, **kwargs):
        self._workflow.start_resolution(*args, **kwargs)
        raise ResolutionConflictError("A concurrent workflow committed first.")

    def __getattr__(self, name):
        return getattr(self._workflow, name)


def test_completed_review_persists_and_starts_linked_resolution(tmp_path) -> None:
    application, reviewer = _application(
        tmp_path,
        make_review(),
        CREATED_AT,
    )

    started = application.start_review(
        "CASE-006",
        review_id="review-1",
        workflow_id="workflow-1",
    )
    replay = application.get_workflow_replay("workflow-1")

    assert started.review.result == make_review()
    assert started.workflow is not None
    assert started.workflow.review_id == "review-1"
    assert started.workflow.status is ResolutionStatus.WAITING_APPROVAL
    assert reviewer.calls == [("CASE-006", CREATED_AT, "review-1")]
    assert replay.case == make_case()
    assert replay.review.review_id == "review-1"
    assert replay.resolution.workflow_id == "workflow-1"
    application.close()


def test_identical_start_review_retry_reuses_durable_result(tmp_path) -> None:
    application, reviewer = _application(tmp_path, make_review(), CREATED_AT)

    first = application.start_review(
        "CASE-006",
        review_id="review-1",
        workflow_id="workflow-1",
    )
    replay = application.start_review(
        "CASE-006",
        review_id="review-1",
        workflow_id="workflow-1",
    )

    assert replay.review == first.review
    assert replay.workflow == first.workflow
    assert first.created is True
    assert replay.created is False
    assert reviewer.calls == [("CASE-006", CREATED_AT, "review-1")]
    application.close()


def test_concurrent_identical_review_write_converges_on_durable_result(
    tmp_path,
) -> None:
    database = tmp_path / "caselens.db"
    repository = SqliteRepository(database)
    store = SqliteResolutionStore(database)
    repository.save_case(make_case())
    reviewer = FixedReviewer(make_review())
    application = CaseLensApplication(
        ConcurrentWinnerRepository(repository),
        store,
        ResolutionWorkflow(store),
        reviewer,
        clock=SequenceClock(CREATED_AT),
    )

    started = application.start_review(
        "CASE-006",
        review_id="review-1",
        workflow_id="workflow-1",
    )

    assert started.created is False
    assert started.review.result == make_review()
    assert started.workflow is not None
    assert application.get_workflow("workflow-1") == started.workflow
    application.close()


def test_concurrent_identical_workflow_write_converges_on_durable_result(
    tmp_path,
) -> None:
    database = tmp_path / "caselens.db"
    repository = SqliteRepository(database)
    store = SqliteResolutionStore(database)
    repository.save_case(make_case())
    reviewer = FixedReviewer(make_review())
    application = CaseLensApplication(
        repository,
        store,
        ConcurrentWinnerWorkflow(ResolutionWorkflow(store)),
        reviewer,
        clock=SequenceClock(CREATED_AT),
    )

    started = application.start_review(
        "CASE-006",
        review_id="review-1",
        workflow_id="workflow-1",
    )

    assert started.created is True
    assert started.workflow is not None
    assert application.get_workflow("workflow-1") == started.workflow
    application.close()


def test_start_review_retry_recovers_after_workflow_write_failure(tmp_path) -> None:
    database = tmp_path / "caselens.db"
    repository = SqliteRepository(database)
    store = SqliteResolutionStore(database)
    store.seed_refunds((make_payment(),))
    repository.save_case(make_case())
    reviewer = FixedReviewer(make_review())
    workflow = FailFirstStartWorkflow(ResolutionWorkflow(store))
    application = CaseLensApplication(
        repository,
        store,
        workflow,
        reviewer,
        clock=SequenceClock(CREATED_AT),
    )

    with pytest.raises(ResolutionStoreError, match="Simulated"):
        application.start_review(
            "CASE-006",
            review_id="review-1",
            workflow_id="workflow-1",
        )

    recovered = application.start_review(
        "CASE-006",
        review_id="review-1",
        workflow_id="workflow-1",
    )

    assert recovered.workflow is not None
    assert recovered.workflow.created_at == CREATED_AT
    assert reviewer.calls == [("CASE-006", CREATED_AT, "review-1")]
    assert workflow.calls == 2
    application.close()


def test_safe_review_is_replayable_without_creating_workflow(tmp_path) -> None:
    review = _failed_review()
    application, _ = _application(tmp_path, review, CREATED_AT)

    started = application.start_review(
        "CASE-006",
        review_id="review-failed",
        workflow_id="workflow-must-not-exist",
    )

    assert started.review.result == review
    assert started.workflow is None
    assert application.get_review("review-failed").result.error is not None
    application.close()


def test_resolution_commands_use_application_clock_and_preserve_replay(
    tmp_path,
) -> None:
    application, _ = _application(
        tmp_path,
        make_review(),
        CREATED_AT,
        DECIDED_AT,
        EXECUTED_AT,
        VERIFIED_AT,
    )
    application.start_review(
        "CASE-006",
        review_id="review-1",
        workflow_id="workflow-1",
    )

    approved = application.decide_approval(
        "workflow-1",
        ApprovalDecision.APPROVED,
        decided_by="reviewer-1",
    )
    executed = application.execute_action("workflow-1")
    verified = application.verify_action("workflow-1")

    assert approved.approval_record is not None
    assert approved.approval_record.decided_at == DECIDED_AT
    assert executed.action_receipt is not None
    assert executed.action_receipt.completed_at == EXECUTED_AT
    assert verified.verification is not None
    assert verified.verification.verified_at == VERIFIED_AT
    assert verified.status is ResolutionStatus.COMPLETED_VERIFIED
    assert application.get_workflow_replay("workflow-1").resolution == verified
    application.close()


def _application(tmp_path, review: CaseReviewResult, *times: datetime):
    database = tmp_path / "caselens.db"
    repository = SqliteRepository(database)
    store = SqliteResolutionStore(database)
    store.seed_refunds((make_payment(),))
    repository.save_case(make_case())
    reviewer = FixedReviewer(review)
    application = CaseLensApplication(
        repository,
        store,
        ResolutionWorkflow(store),
        reviewer,
        clock=SequenceClock(*times),
    )
    return application, reviewer


def _failed_review() -> CaseReviewResult:
    model_error = ModelError(
        code="invalid_response",
        message="The deterministic model failed safely.",
    )
    return CaseReviewResult(
        case_id="CASE-006",
        status=CaseReviewStatus.ERROR,
        termination_reason=CaseReviewTerminationReason.MODEL_ERROR,
        investigation=InvestigationResult(
            status=InvestigationStatus.ERROR,
            termination_reason=InvestigationTerminationReason.MODEL_ERROR,
            steps=1,
            model_error=model_error,
        ),
        error=CaseReviewError(
            code="model_error",
            message="The review stopped safely.",
        ),
    )
