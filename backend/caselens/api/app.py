from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, Request, Response, status
from fastapi.responses import JSONResponse

from caselens.api.schemas import (
    ApprovalRequest,
    ErrorDetail,
    ErrorResponse,
    HealthResponse,
    StartReviewRequest,
)
from caselens.application import (
    CaseLensApplication,
    ReplayIntegrityError,
    ReviewStartResult,
    WorkflowReplay,
)
from caselens.domain.models import Case
from caselens.persistence.repository import (
    PersistenceError,
    RecordConflictError,
    RecordNotFoundError,
    RepositoryInputError,
    StoredCaseReview,
)
from caselens.resolution.models import ResolutionRun
from caselens.resolution.planning import ResolutionPlanningError
from caselens.resolution.store import (
    IllegalTransitionError,
    ResolutionConflictError,
    ResolutionNotFoundError,
    ResolutionStoreError,
)


def create_app(application: CaseLensApplication) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            application.close()

    app = _base_app(lifespan)
    _register_exception_handlers(app)
    app.include_router(_router(lambda: application), prefix="/api/v1")
    return app


def create_app_from_factory(
    application_factory: Callable[[], CaseLensApplication],
) -> FastAPI:
    applications: list[CaseLensApplication] = []

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        application = application_factory()
        applications.append(application)
        try:
            yield
        finally:
            applications.pop().close()

    def current_application() -> CaseLensApplication:
        if not applications:
            raise RuntimeError("The CaseLens application lifespan is not active.")
        return applications[-1]

    app = _base_app(lifespan)
    _register_exception_handlers(app)
    app.include_router(_router(current_application), prefix="/api/v1")
    return app


def _base_app(lifespan) -> FastAPI:
    return FastAPI(
        title="CaseLens API",
        version="0.1.0",
        lifespan=lifespan,
    )


def _router(
    application_provider: Callable[[], CaseLensApplication],
) -> APIRouter:
    router = APIRouter()

    @router.get("/health")
    def health() -> HealthResponse:
        return HealthResponse()

    @router.get("/cases")
    def list_cases() -> tuple[Case, ...]:
        return application_provider().list_cases()

    @router.get("/cases/{case_id}")
    def get_case(case_id: str) -> Case:
        return application_provider().get_case(case_id)

    @router.post(
        "/cases/{case_id}/reviews",
        status_code=status.HTTP_201_CREATED,
    )
    def start_review(
        case_id: str,
        command: StartReviewRequest,
        response: Response,
    ) -> ReviewStartResult:
        result = application_provider().start_review(
            case_id,
            review_id=command.review_id,
            workflow_id=command.workflow_id,
        )
        if not result.created:
            response.status_code = status.HTTP_200_OK
        return result

    @router.get("/reviews/{review_id}")
    def get_review(review_id: str) -> StoredCaseReview:
        return application_provider().get_review(review_id)

    @router.get("/workflows/{workflow_id}")
    def get_workflow(workflow_id: str) -> ResolutionRun:
        return application_provider().get_workflow(workflow_id)

    @router.post("/workflows/{workflow_id}/approval")
    def decide_approval(
        workflow_id: str,
        command: ApprovalRequest,
    ) -> ResolutionRun:
        return application_provider().decide_approval(
            workflow_id,
            command.decision,
            decided_by=command.decided_by,
        )

    @router.post("/workflows/{workflow_id}/execute")
    def execute_action(workflow_id: str) -> ResolutionRun:
        return application_provider().execute_action(workflow_id)

    @router.post("/workflows/{workflow_id}/verify")
    def verify_action(workflow_id: str) -> ResolutionRun:
        return application_provider().verify_action(workflow_id)

    @router.get("/workflows/{workflow_id}/replay")
    def get_workflow_replay(workflow_id: str) -> WorkflowReplay:
        return application_provider().get_workflow_replay(workflow_id)

    return router


def _register_exception_handlers(app: FastAPI) -> None:
    for exception_type in (RecordNotFoundError, ResolutionNotFoundError):
        app.add_exception_handler(
            exception_type,
            _not_found_handler,
        )
    for exception_type in (
        RecordConflictError,
        RepositoryInputError,
        ResolutionConflictError,
        ResolutionPlanningError,
    ):
        app.add_exception_handler(exception_type, _conflict_handler)
    app.add_exception_handler(IllegalTransitionError, _illegal_transition_handler)
    for exception_type in (
        PersistenceError,
        ResolutionStoreError,
        ReplayIntegrityError,
    ):
        app.add_exception_handler(exception_type, _unavailable_handler)


async def _not_found_handler(_request: Request, _error: Exception) -> JSONResponse:
    return _error_response(
        status.HTTP_404_NOT_FOUND,
        "resource_not_found",
        "The requested resource was not found.",
    )


async def _conflict_handler(_request: Request, _error: Exception) -> JSONResponse:
    return _error_response(
        status.HTTP_409_CONFLICT,
        "resource_conflict",
        "The request conflicts with existing resource state.",
    )


async def _illegal_transition_handler(
    _request: Request,
    _error: Exception,
) -> JSONResponse:
    return _error_response(
        status.HTTP_409_CONFLICT,
        "illegal_transition",
        "The operation is not legal from the current workflow state.",
    )


async def _unavailable_handler(_request: Request, _error: Exception) -> JSONResponse:
    return _error_response(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "service_unavailable",
        "The requested operation could not be completed safely.",
    )


def _error_response(status_code: int, code: str, message: str) -> JSONResponse:
    response = ErrorResponse(error=ErrorDetail(code=code, message=message))
    return JSONResponse(status_code=status_code, content=response.model_dump())
