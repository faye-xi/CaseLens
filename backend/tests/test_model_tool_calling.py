from datetime import UTC, datetime
from decimal import Decimal

from caselens.model import (
    MockModel,
    ModelErrorCode,
    ModelFinishReason,
    ModelMessage,
    ModelRequest,
    ModelResponse,
)
from caselens.tools.execution import execute_tool_calls, tool_definitions
from caselens.tools.models import OrderRecord, OrderStatus
from caselens.tools.protocol import ToolCall, ToolErrorCode
from caselens.tools.source import InMemoryBusinessDataSource

STARTED_AT = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)


def make_source() -> InMemoryBusinessDataSource:
    return InMemoryBusinessDataSource(
        orders=(
            OrderRecord(
                order_id="order-1",
                customer_id="customer-1",
                status=OrderStatus.COMPLETED,
                total_amount=Decimal("129.90"),
                currency="CNY",
                placed_at=STARTED_AT,
            ),
        )
    )


class RaisingSource:
    def __init__(self) -> None:
        self.calls = 0

    def get_order(self, order_id: str) -> OrderRecord:
        self.calls += 1
        raise AssertionError("The source must not be called.")

    def get_payment(self, payment_id: str):
        self.calls += 1
        raise AssertionError("The source must not be called.")

    def get_logistics(self, order_id: str):
        self.calls += 1
        raise AssertionError("The source must not be called.")

    def get_messages(self, order_id: str):
        self.calls += 1
        raise AssertionError("The source must not be called.")


def make_request() -> ModelRequest:
    return ModelRequest(
        request_id="request-1",
        messages=(ModelMessage(role="user", content="查订单"),),
        tools=tool_definitions(),
    )


def make_tool_call_response(tool_name: str = "get_order") -> ModelResponse:
    return ModelResponse(
        response_id="response-1",
        finish_reason=ModelFinishReason.TOOL_CALLS,
        message=ModelMessage(
            role="assistant",
            tool_calls=(
                ToolCall(
                    call_id="call-1",
                    tool_name=tool_name,
                    arguments={"order_id": "order-1"},
                ),
            ),
        ),
    )


def test_model_tool_call_can_be_passed_directly_to_day5_executor() -> None:
    model = MockModel((make_tool_call_response(),))
    result = model.complete(make_request())

    assert result.response is not None
    batch = execute_tool_calls(
        make_source(),
        result.response.message.tool_calls,
        allowed_tool_names={tool.name for tool in tool_definitions()},
    )

    assert batch.error is None
    assert batch.results[0].data is not None
    assert batch.results[0].trace.call_id == "call-1"


def test_unknown_tool_keeps_day5_unknown_tool_error_and_failed_trace() -> None:
    batch = execute_tool_calls(
        make_source(),
        (ToolCall(call_id="call-1", tool_name="delete_order", arguments={}),),
        allowed_tool_names={"delete_order"},
    )

    assert batch.results[0].error is not None
    assert batch.results[0].error.code is ToolErrorCode.UNKNOWN_TOOL
    assert batch.results[0].trace.error_code is ToolErrorCode.UNKNOWN_TOOL


def test_invalid_arguments_keep_day5_invalid_input_error_without_source_call() -> None:
    source = RaisingSource()
    batch = execute_tool_calls(
        source,
        (
            ToolCall(
                call_id="call-1",
                tool_name="get_order",
                arguments={"order_id": " "},
            ),
        ),
        allowed_tool_names={"get_order"},
    )

    assert source.calls == 0
    assert batch.results[0].error is not None
    assert batch.results[0].error.code is ToolErrorCode.INVALID_INPUT


def test_malformed_model_response_never_executes_a_tool() -> None:
    source = RaisingSource()
    model = MockModel(({"finish_reason": "tool_calls"},))
    result = model.complete(make_request())

    assert result.response is None
    assert result.error is not None
    assert result.error.code is ModelErrorCode.INVALID_RESPONSE
    assert source.calls == 0
