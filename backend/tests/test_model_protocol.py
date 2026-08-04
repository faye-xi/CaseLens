from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from caselens.domain.decision import DecisionDraft
from caselens.model.protocol import (
    ModelErrorCode,
    ModelInvocationResult,
    ModelMessage,
    ModelResponse,
    ModelTrace,
    ModelTraceStatus,
    parse_structured_output,
)
from caselens.tools.protocol import ToolCall

STARTED_AT = datetime(2026, 8, 4, 10, 0, tzinfo=UTC)
COMPLETED_AT = datetime(2026, 8, 4, 10, 0, 0, 125000, tzinfo=UTC)


def make_model_trace(
    *,
    status: ModelTraceStatus = ModelTraceStatus.SUCCEEDED,
    error_code: ModelErrorCode | None = None,
) -> ModelTrace:
    return ModelTrace(
        request_id="request-1",
        implementation="mock",
        started_at=STARTED_AT,
        completed_at=COMPLETED_AT,
        duration_ms=125,
        status=status,
        response_id="response-1" if error_code is None else None,
        finish_reason="stop" if error_code is None else None,
        tool_call_ids=(),
        error_code=error_code,
    )


def make_response(
    *, structured_output: dict[str, object] | None = None
) -> ModelResponse:
    return ModelResponse(
        response_id="response-1",
        finish_reason="stop",
        message=ModelMessage(role="assistant", content="done"),
        structured_output=structured_output,
    )


def test_assistant_message_can_request_a_day5_tool_call() -> None:
    message = ModelMessage(
        role="assistant",
        tool_calls=(
            ToolCall(
                call_id="call-1",
                tool_name="get_order",
                arguments={"order_id": "order-1"},
            ),
        ),
    )

    assert message.tool_calls[0].call_id == "call-1"


def test_tool_message_requires_the_matching_tool_result_fields() -> None:
    with pytest.raises(ValidationError):
        ModelMessage(role="tool", content="not a structured result")


def test_model_response_rejects_stop_with_tool_calls() -> None:
    with pytest.raises(ValidationError):
        ModelResponse(
            response_id="response-1",
            finish_reason="stop",
            message=ModelMessage(
                role="assistant",
                tool_calls=(
                    ToolCall(
                        call_id="call-1",
                        tool_name="get_order",
                        arguments={"order_id": "order-1"},
                    ),
                ),
            ),
        )


def test_model_response_requires_a_tool_call_for_tool_calls_finish_reason() -> None:
    with pytest.raises(ValidationError):
        ModelResponse(
            response_id="response-1",
            finish_reason="tool_calls",
            message=ModelMessage(role="assistant"),
        )


def test_model_invocation_result_requires_exactly_one_response_or_error() -> None:
    trace = make_model_trace()

    with pytest.raises(ValidationError):
        ModelInvocationResult(trace=trace)

    with pytest.raises(ValidationError):
        ModelInvocationResult(
            trace=trace,
            response=make_response(),
            error={"code": "invalid_response", "message": "invalid"},
        )


def test_invalid_structured_output_returns_model_error_without_raw_exception() -> None:
    response = make_response(structured_output={"recommendation": "not-valid"})

    result = parse_structured_output(response, DecisionDraft)

    assert result.data is None
    assert result.error is not None
    assert result.error.code is ModelErrorCode.INVALID_STRUCTURED_OUTPUT
    assert "recommendation" not in result.error.message


def test_model_trace_requires_error_code_only_for_failed_calls() -> None:
    with pytest.raises(ValidationError):
        make_model_trace(status=ModelTraceStatus.FAILED)

    with pytest.raises(ValidationError):
        make_model_trace(error_code=ModelErrorCode.INVALID_RESPONSE)
