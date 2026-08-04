from datetime import UTC, datetime
from decimal import Decimal

from caselens.agent import (
    InvestigationStatus,
    run_investigation,
)
from caselens.model import (
    MockModel,
    ModelErrorCode,
    ModelFinishReason,
    ModelMessage,
    ModelResponse,
)
from caselens.tools.models import OrderRecord, OrderStatus
from caselens.tools.protocol import ToolCallBatchErrorCode, ToolErrorCode
from caselens.tools.source import InMemoryBusinessDataSource

OCCURRED_AT = datetime(2026, 8, 4, 14, 0, tzinfo=UTC)


def make_source() -> InMemoryBusinessDataSource:
    return InMemoryBusinessDataSource(orders=(make_order(),))


def make_order() -> OrderRecord:
    return OrderRecord(
        order_id="order-1",
        customer_id="customer-1",
        status=OrderStatus.COMPLETED,
        total_amount=Decimal("129.90"),
        currency="CNY",
        placed_at=OCCURRED_AT,
    )


def make_tool_call_response(
    *,
    tool_name: str = "get_order",
    arguments: dict[str, object] | None = None,
    call_id: str = "call-1",
) -> ModelResponse:
    return ModelResponse(
        response_id="response-1",
        finish_reason=ModelFinishReason.TOOL_CALLS,
        message=ModelMessage(
            role="assistant",
            tool_calls=(
                {
                    "call_id": call_id,
                    "tool_name": tool_name,
                    "arguments": (
                        {"order_id": "order-1"} if arguments is None else arguments
                    ),
                },
            ),
        ),
    )


def make_stop_response() -> ModelResponse:
    return ModelResponse(
        response_id="response-2",
        finish_reason=ModelFinishReason.STOP,
        message=ModelMessage(role="assistant", content="订单记录已核对。"),
    )


def test_tool_call_result_is_appended_before_the_next_model_step() -> None:
    model = MockModel((make_tool_call_response(), make_stop_response()))

    result = run_investigation(
        model,
        make_source(),
        (ModelMessage(role="user", content="请核对订单 order-1。"),),
        request_id_prefix="run-1",
    )

    assert result.status is InvestigationStatus.COMPLETED
    assert result.steps == 2
    assert result.final_response is not None
    assert result.final_response.response_id == "response-2"
    assert len(result.model_traces) == 2
    assert [message.role.value for message in result.messages] == [
        "user",
        "assistant",
        "tool",
        "assistant",
    ]
    assert result.messages[2].tool_call_id == "call-1"
    assert result.messages[2].tool_result is not None
    assert result.messages[2].tool_result.data is not None
    assert result.messages[2].tool_result.data.order_id == "order-1"

    assert len(model.received_requests) == 2
    second_request = model.received_requests[1]
    assert second_request.request_id == "run-1-step-2"
    assert second_request.messages == result.messages[:-1]


def test_model_response_error_stops_before_any_tool_execution() -> None:
    model = MockModel(({"finish_reason": "tool_calls"},))

    result = run_investigation(
        model,
        make_source(),
        (ModelMessage(role="user", content="请调查。"),),
    )

    assert result.status is InvestigationStatus.ERROR
    assert result.termination_reason.value == "model_error"
    assert result.model_error is not None
    assert result.model_error.code is ModelErrorCode.INVALID_RESPONSE
    assert result.messages == (ModelMessage(role="user", content="请调查。"),)


def test_exhausted_model_script_returns_error_without_a_partial_answer() -> None:
    model = MockModel(())

    result = run_investigation(
        model,
        make_source(),
        (ModelMessage(role="user", content="请调查。"),),
    )

    assert result.status is InvestigationStatus.ERROR
    assert result.model_error is not None
    assert result.model_error.code.value == "mock_script_exhausted"
    assert result.final_response is None


def test_unauthorized_tool_batch_safe_terminates_before_source_access() -> None:
    model = MockModel(
        (make_tool_call_response(tool_name="delete_order"),),
    )

    result = run_investigation(
        model,
        make_source(),
        (ModelMessage(role="user", content="请调查。"),),
    )

    assert result.status is InvestigationStatus.SAFE_TERMINATED
    assert result.tool_batch_error is not None
    assert result.tool_batch_error.code is ToolCallBatchErrorCode.UNAUTHORIZED_TOOL
    assert len(result.messages) == 2


def test_duplicate_tool_batch_safe_terminates_before_dispatch() -> None:
    response = ModelResponse(
        response_id="response-duplicate",
        finish_reason=ModelFinishReason.TOOL_CALLS,
        message=ModelMessage(
            role="assistant",
            tool_calls=(
                {
                    "call_id": "call-1",
                    "tool_name": "get_order",
                    "arguments": {"order_id": "order-1"},
                },
                {
                    "call_id": "call-1",
                    "tool_name": "get_order",
                    "arguments": {"order_id": "order-1"},
                },
            ),
        ),
    )

    result = run_investigation(
        MockModel((response,)),
        make_source(),
        (ModelMessage(role="user", content="请调查。"),),
    )

    assert result.status is InvestigationStatus.SAFE_TERMINATED
    assert result.tool_batch_error is not None
    assert result.tool_batch_error.code is ToolCallBatchErrorCode.DUPLICATE_TOOL_CALL


def test_multiple_tool_results_keep_the_model_call_order() -> None:
    response = ModelResponse(
        response_id="response-batch",
        finish_reason=ModelFinishReason.TOOL_CALLS,
        message=ModelMessage(
            role="assistant",
            tool_calls=(
                {
                    "call_id": "call-order",
                    "tool_name": "get_order",
                    "arguments": {"order_id": "order-1"},
                },
                {
                    "call_id": "call-messages",
                    "tool_name": "get_messages",
                    "arguments": {"order_id": "order-1"},
                },
            ),
        ),
    )

    result = run_investigation(
        MockModel((response, make_stop_response())),
        make_source(),
        (ModelMessage(role="user", content="请调查。"),),
    )

    assert result.status is InvestigationStatus.COMPLETED
    assert [message.tool_call_id for message in result.messages[2:4]] == [
        "call-order",
        "call-messages",
    ]


def test_invalid_tool_arguments_are_returned_to_the_model_for_continuation() -> None:
    model = MockModel(
        (
            make_tool_call_response(arguments={"order_id": " "}),
            make_stop_response(),
        ),
    )

    result = run_investigation(
        model,
        make_source(),
        (ModelMessage(role="user", content="请调查。"),),
    )

    assert result.status is InvestigationStatus.COMPLETED
    assert result.messages[2].tool_result is not None
    assert result.messages[2].tool_result.error is not None
    assert result.messages[2].tool_result.error.code is ToolErrorCode.INVALID_INPUT
    assert len(model.received_requests) == 2


def test_tool_source_failure_is_returned_to_the_model_for_continuation() -> None:
    model = MockModel((make_tool_call_response(), make_stop_response()))
    source = InMemoryBusinessDataSource(
        orders=(make_order(),),
        timed_out_operations={"orders"},
    )

    result = run_investigation(
        model,
        source,
        (ModelMessage(role="user", content="请调查。"),),
    )

    assert result.status is InvestigationStatus.COMPLETED
    assert result.messages[2].tool_result is not None
    assert result.messages[2].tool_result.error is not None
    assert result.messages[2].tool_result.error.code is ToolErrorCode.TIMEOUT


def test_max_steps_prevents_another_model_call_after_tool_execution() -> None:
    model = MockModel(
        (
            make_tool_call_response(call_id="call-1"),
            make_tool_call_response(call_id="call-2"),
            make_stop_response(),
        ),
    )

    result = run_investigation(
        model,
        make_source(),
        (ModelMessage(role="user", content="请调查。"),),
        max_steps=2,
    )

    assert result.status is InvestigationStatus.SAFE_TERMINATED
    assert result.termination_reason.value == "max_steps"
    assert result.steps == 2
    assert len(model.received_requests) == 2
    assert result.final_response is None
