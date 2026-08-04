from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from caselens.agent.protocol import (
    InvestigationResult,
    InvestigationStatus,
    InvestigationTerminationReason,
)
from caselens.model.protocol import (
    ModelError,
    ModelErrorCode,
    ModelFinishReason,
    ModelMessage,
    ModelResponse,
    ModelTrace,
    ModelTraceStatus,
)

STARTED_AT = datetime(2026, 8, 4, 13, 0, tzinfo=UTC)
COMPLETED_AT = datetime(2026, 8, 4, 13, 0, 0, 125000, tzinfo=UTC)


def make_response() -> ModelResponse:
    return ModelResponse(
        response_id="response-1",
        finish_reason=ModelFinishReason.STOP,
        message=ModelMessage(role="assistant", content="调查完成"),
    )


def make_trace() -> ModelTrace:
    return ModelTrace(
        request_id="request-1",
        implementation="mock",
        started_at=STARTED_AT,
        completed_at=COMPLETED_AT,
        duration_ms=125,
        status=ModelTraceStatus.SUCCEEDED,
        response_id="response-1",
        finish_reason=ModelFinishReason.STOP,
    )


def test_completed_result_requires_final_model_response() -> None:
    result = InvestigationResult(
        status=InvestigationStatus.COMPLETED,
        termination_reason=InvestigationTerminationReason.COMPLETED,
        steps=1,
        messages=(make_response().message,),
        final_response=make_response(),
        model_traces=(make_trace(),),
    )

    assert result.status is InvestigationStatus.COMPLETED
    assert result.final_response is not None

    with pytest.raises(ValidationError):
        InvestigationResult(
            status=InvestigationStatus.COMPLETED,
            termination_reason=InvestigationTerminationReason.COMPLETED,
            steps=1,
            messages=(make_response().message,),
            model_traces=(make_trace(),),
        )


def test_model_error_result_cannot_claim_a_final_response() -> None:
    result = InvestigationResult(
        status=InvestigationStatus.ERROR,
        termination_reason=InvestigationTerminationReason.MODEL_ERROR,
        steps=1,
        messages=(),
        model_traces=(
            ModelTrace(
                request_id="request-1",
                implementation="mock",
                started_at=STARTED_AT,
                completed_at=COMPLETED_AT,
                duration_ms=125,
                status=ModelTraceStatus.FAILED,
                error_code=ModelErrorCode.INVALID_RESPONSE,
            ),
        ),
        model_error=ModelError(
            code=ModelErrorCode.INVALID_RESPONSE,
            message="The model response is invalid.",
        ),
    )

    assert result.status is InvestigationStatus.ERROR
    assert result.final_response is None

    with pytest.raises(ValidationError):
        InvestigationResult(
            status=InvestigationStatus.ERROR,
            termination_reason=InvestigationTerminationReason.MODEL_ERROR,
            steps=1,
            messages=(make_response().message,),
            final_response=make_response(),
            model_error=ModelError(
                code=ModelErrorCode.INVALID_RESPONSE,
                message="The model response is invalid.",
            ),
        )


def test_max_steps_result_is_safe_termination_without_model_error() -> None:
    result = InvestigationResult(
        status=InvestigationStatus.SAFE_TERMINATED,
        termination_reason=InvestigationTerminationReason.MAX_STEPS,
        steps=8,
        messages=(),
    )

    assert result.status is InvestigationStatus.SAFE_TERMINATED
    assert result.termination_reason is InvestigationTerminationReason.MAX_STEPS
