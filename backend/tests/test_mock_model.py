from datetime import UTC, datetime

from caselens.model.mock import MockModel
from caselens.model.protocol import (
    ModelErrorCode,
    ModelFinishReason,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelTraceStatus,
)

STARTED_AT = datetime(2026, 8, 4, 11, 0, tzinfo=UTC)
COMPLETED_AT = datetime(2026, 8, 4, 11, 0, 0, 125000, tzinfo=UTC)


def make_request(request_id: str) -> ModelRequest:
    return ModelRequest(
        request_id=request_id,
        messages=(ModelMessage(role="user", content="查订单"),),
    )


def make_response(response_id: str) -> ModelResponse:
    return ModelResponse(
        response_id=response_id,
        finish_reason=ModelFinishReason.STOP,
        message=ModelMessage(role="assistant", content="done"),
    )


def test_mock_model_returns_scripted_responses_in_order_and_records_requests() -> None:
    model = MockModel(
        (make_response("response-1"), make_response("response-2")),
        clock=iter((STARTED_AT, COMPLETED_AT, STARTED_AT, COMPLETED_AT)).__next__,
    )

    first = model.complete(make_request("request-1"))
    second = model.complete(make_request("request-2"))

    assert first.response is not None
    assert first.response.response_id == "response-1"
    assert second.response is not None
    assert second.response.response_id == "response-2"
    assert [request.request_id for request in model.received_requests] == [
        "request-1",
        "request-2",
    ]
    assert first.trace.status is ModelTraceStatus.SUCCEEDED
    assert first.trace.duration_ms == 125


def test_mock_model_converts_malformed_script_response_to_structured_error() -> None:
    model = MockModel(
        ({"response_id": "broken", "finish_reason": "unknown"},),
        clock=iter((STARTED_AT, COMPLETED_AT)).__next__,
    )

    result = model.complete(make_request("request-1"))

    assert result.response is None
    assert result.error is not None
    assert result.error.code is ModelErrorCode.INVALID_RESPONSE
    assert result.trace.status is ModelTraceStatus.FAILED
    assert result.trace.error_code is ModelErrorCode.INVALID_RESPONSE


def test_mock_model_script_exhaustion_does_not_fallback_to_a_real_api() -> None:
    model = MockModel(
        (),
        clock=iter((STARTED_AT, COMPLETED_AT)).__next__,
    )

    result = model.complete(make_request("request-1"))

    assert result.response is None
    assert result.error is not None
    assert result.error.code is ModelErrorCode.MOCK_SCRIPT_EXHAUSTED
    assert result.trace.status is ModelTraceStatus.FAILED
