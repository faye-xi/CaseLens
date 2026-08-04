from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from caselens.tools.execution import execute_tool, execute_tool_calls, tool_definitions
from caselens.tools.models import (
    Message,
    MessageHistory,
    MessageSender,
    OrderRecord,
    OrderStatus,
    PaymentRecord,
    PaymentStatus,
    ShipmentRecord,
    ShipmentStatus,
)
from caselens.tools.protocol import (
    ToolCall,
    ToolCallBatchErrorCode,
    ToolError,
    ToolErrorCode,
    ToolExecutionResult,
    ToolTrace,
    ToolTraceStatus,
)
from caselens.tools.source import InMemoryBusinessDataSource

STARTED_AT = datetime(2026, 8, 3, 10, 0, tzinfo=UTC)
COMPLETED_AT = datetime(2026, 8, 3, 10, 0, 0, 125000, tzinfo=UTC)


def make_order() -> OrderRecord:
    return OrderRecord(
        order_id="order-1",
        customer_id="customer-1",
        status=OrderStatus.COMPLETED,
        total_amount=Decimal("129.90"),
        currency="CNY",
        placed_at=STARTED_AT,
    )


def make_source_and_records() -> tuple[
    InMemoryBusinessDataSource,
    dict[str, OrderRecord | PaymentRecord | ShipmentRecord | MessageHistory],
]:
    order = make_order()
    payment = PaymentRecord(
        payment_id="payment-1",
        order_id="order-1",
        status=PaymentStatus.PAID,
        amount=Decimal("129.90"),
        currency="CNY",
        paid_at=STARTED_AT,
    )
    shipment = ShipmentRecord(
        shipment_id="shipment-1",
        order_id="order-1",
        status=ShipmentStatus.DELIVERED,
        carrier="SF Express",
        tracking_number="SF001",
    )
    messages = MessageHistory(
        order_id="order-1",
        messages=(
            Message(
                message_id="message-1",
                sender=MessageSender.CUSTOMER,
                content="I have not received the refund.",
                sent_at=STARTED_AT,
            ),
        ),
    )
    source = InMemoryBusinessDataSource(
        orders=(order,),
        payments=(payment,),
        shipments=(shipment,),
        message_histories=(messages,),
    )
    return source, {
        "get_order": order,
        "get_payment": payment,
        "get_logistics": shipment,
        "get_messages": messages,
    }


def make_trace(
    *,
    status: ToolTraceStatus = ToolTraceStatus.SUCCEEDED,
    error_code: ToolErrorCode | None = None,
) -> ToolTrace:
    return ToolTrace(
        call_id="call-1",
        tool_name="get_order",
        arguments_json='{"order_id":"order-1"}',
        started_at=STARTED_AT,
        completed_at=COMPLETED_AT,
        duration_ms=125,
        status=status,
        error_code=error_code,
    )


class RaisingSource:
    def __init__(self, error: Exception) -> None:
        self.error = error
        self.calls = 0

    def get_order(self, order_id: str) -> OrderRecord:
        self.calls += 1
        raise self.error

    def get_payment(self, payment_id: str) -> PaymentRecord:
        self.calls += 1
        raise self.error

    def get_logistics(self, order_id: str) -> ShipmentRecord:
        self.calls += 1
        raise self.error

    def get_messages(self, order_id: str) -> MessageHistory:
        self.calls += 1
        raise self.error


def test_tool_call_accepts_only_a_named_call_with_json_object_arguments() -> None:
    call = ToolCall(
        call_id="call-1",
        tool_name="get_order",
        arguments={"order_id": "order-1", "options": {"fresh": True}},
    )

    assert call.arguments["order_id"] == "order-1"

    with pytest.raises(ValidationError):
        ToolCall(call_id=" ", tool_name="get_order", arguments={})

    with pytest.raises(ValidationError):
        ToolCall(call_id="call-1", tool_name="get_order", arguments={"bad": object()})

    with pytest.raises(ValidationError):
        ToolCall(
            call_id="call-1",
            tool_name="get_order",
            arguments={"bad": float("nan")},
        )


def test_trace_requires_timezone_aware_timestamps() -> None:
    with pytest.raises(ValidationError):
        ToolTrace(
            call_id="call-1",
            tool_name="get_order",
            arguments_json="{}",
            started_at=STARTED_AT.replace(tzinfo=None),
            completed_at=COMPLETED_AT,
            duration_ms=0,
            status=ToolTraceStatus.SUCCEEDED,
        )


def test_trace_status_and_error_code_must_be_consistent() -> None:
    with pytest.raises(ValidationError):
        make_trace(status=ToolTraceStatus.FAILED)

    with pytest.raises(ValidationError):
        make_trace(error_code=ToolErrorCode.TIMEOUT)


def test_success_result_requires_data_and_a_consistent_trace() -> None:
    result = ToolExecutionResult(trace=make_trace(), data=make_order())

    assert result.data == make_order()
    assert result.error is None

    with pytest.raises(ValidationError):
        ToolExecutionResult(trace=make_trace())


def test_failure_result_requires_error_and_matching_trace_code() -> None:
    error = ToolError(
        code=ToolErrorCode.NOT_FOUND,
        message="The requested business record was not found.",
    )
    failed_trace = make_trace(
        status=ToolTraceStatus.FAILED,
        error_code=ToolErrorCode.NOT_FOUND,
    )

    result = ToolExecutionResult(trace=failed_trace, error=error)

    assert result.error == error
    assert result.data is None

    with pytest.raises(ValidationError):
        ToolExecutionResult(trace=failed_trace, data=make_order(), error=error)

    with pytest.raises(ValidationError):
        ToolExecutionResult(
            trace=make_trace(
                status=ToolTraceStatus.FAILED,
                error_code=ToolErrorCode.TIMEOUT,
            ),
            error=error,
        )


@pytest.mark.parametrize(
    ("tool_name", "arguments", "expected_arguments_json"),
    [
        ("get_order", {"order_id": "order-1"}, '{"order_id":"order-1"}'),
        (
            "get_payment",
            {"payment_id": "payment-1"},
            '{"payment_id":"payment-1"}',
        ),
        ("get_logistics", {"order_id": "order-1"}, '{"order_id":"order-1"}'),
        ("get_messages", {"order_id": "order-1"}, '{"order_id":"order-1"}'),
    ],
)
def test_four_tools_return_structured_data_with_success_trace(
    tool_name: str,
    arguments: dict[str, str],
    expected_arguments_json: str,
) -> None:
    source, records = make_source_and_records()
    times = iter((STARTED_AT, COMPLETED_AT))

    result = execute_tool(
        source,
        ToolCall(call_id="call-1", tool_name=tool_name, arguments=arguments),
        clock=times.__next__,
    )

    assert result.data == records[tool_name]
    assert result.error is None
    assert result.trace.call_id == "call-1"
    assert result.trace.tool_name == tool_name
    assert result.trace.arguments_json == expected_arguments_json
    assert result.trace.started_at == STARTED_AT
    assert result.trace.completed_at == COMPLETED_AT
    assert result.trace.duration_ms == 125
    assert result.trace.status is ToolTraceStatus.SUCCEEDED
    assert result.trace.error_code is None


@pytest.mark.parametrize(
    ("call", "expected_code"),
    [
        (
            ToolCall(
                call_id="call-unknown",
                tool_name="delete_order",
                arguments={"z": 1, "a": 2},
            ),
            ToolErrorCode.UNKNOWN_TOOL,
        ),
        (
            ToolCall(
                call_id="call-invalid",
                tool_name="get_order",
                arguments={"order_id": " "},
            ),
            ToolErrorCode.INVALID_INPUT,
        ),
    ],
)
def test_unknown_and_invalid_calls_fail_without_reaching_source(
    call: ToolCall,
    expected_code: ToolErrorCode,
) -> None:
    source = RaisingSource(AssertionError("The source must not be called."))
    times = iter((STARTED_AT, COMPLETED_AT))

    result = execute_tool(source, call, clock=times.__next__)

    assert source.calls == 0
    assert result.data is None
    assert result.error is not None
    assert result.error.code is expected_code
    assert result.trace.status is ToolTraceStatus.FAILED
    assert result.trace.error_code is expected_code
    if expected_code is ToolErrorCode.UNKNOWN_TOOL:
        assert result.trace.arguments_json == '{"a":2,"z":1}'


@pytest.mark.parametrize(
    ("source", "expected_code"),
    [
        (InMemoryBusinessDataSource(), ToolErrorCode.NOT_FOUND),
        (
            InMemoryBusinessDataSource(timed_out_operations={"orders"}),
            ToolErrorCode.TIMEOUT,
        ),
        (
            InMemoryBusinessDataSource(failing_operations={"orders"}),
            ToolErrorCode.SOURCE_ERROR,
        ),
    ],
)
def test_expected_source_failures_become_distinct_results(
    source: InMemoryBusinessDataSource,
    expected_code: ToolErrorCode,
) -> None:
    times = iter((STARTED_AT, COMPLETED_AT))

    result = execute_tool(
        source,
        ToolCall(
            call_id="call-source-error",
            tool_name="get_order",
            arguments={"order_id": "order-1"},
        ),
        clock=times.__next__,
    )

    assert result.data is None
    assert result.error is not None
    assert result.error.code is expected_code
    assert result.trace.status is ToolTraceStatus.FAILED
    assert result.trace.error_code is expected_code


def test_unexpected_exception_becomes_safe_internal_error() -> None:
    source = RaisingSource(RuntimeError("secret-token=do-not-leak"))
    times = iter((STARTED_AT, COMPLETED_AT))

    result = execute_tool(
        source,
        ToolCall(
            call_id="call-internal-error",
            tool_name="get_order",
            arguments={"order_id": "order-1"},
        ),
        clock=times.__next__,
    )

    assert source.calls == 1
    assert result.error is not None
    assert result.error.code is ToolErrorCode.INTERNAL_ERROR
    assert "secret-token" not in result.model_dump_json()
    assert result.trace.status is ToolTraceStatus.FAILED
    assert result.trace.error_code is ToolErrorCode.INTERNAL_ERROR


def test_trace_clamps_negative_clock_duration_to_zero() -> None:
    source, records = make_source_and_records()
    times = iter((COMPLETED_AT, STARTED_AT))

    result = execute_tool(
        source,
        ToolCall(
            call_id="call-backwards-clock",
            tool_name="get_order",
            arguments={"order_id": "order-1"},
        ),
        clock=times.__next__,
    )

    assert result.data == records["get_order"]
    assert result.trace.duration_ms == 0


def test_tool_definitions_are_generated_from_the_registered_query_models() -> None:
    definitions = tool_definitions()
    by_name = {definition.name: definition for definition in definitions}

    assert set(by_name) == {
        "get_order",
        "get_payment",
        "get_logistics",
        "get_messages",
    }
    assert by_name["get_order"].parameters_schema["properties"]["order_id"]


def test_duplicate_tool_calls_are_rejected_before_any_source_call() -> None:
    source = RaisingSource(AssertionError("The source must not be called."))
    result = execute_tool_calls(
        source,
        (
            ToolCall(
                call_id="call-1",
                tool_name="get_order",
                arguments={"order_id": "order-1"},
            ),
            ToolCall(
                call_id="call-1",
                tool_name="get_order",
                arguments={"order_id": "order-1"},
            ),
        ),
        allowed_tool_names={"get_order"},
    )

    assert source.calls == 0
    assert result.results == ()
    assert result.error is not None
    assert result.error.code is ToolCallBatchErrorCode.DUPLICATE_TOOL_CALL


def test_unauthorized_tool_is_rejected_before_dispatch() -> None:
    source = RaisingSource(AssertionError("The source must not be called."))
    result = execute_tool_calls(
        source,
        (
            ToolCall(
                call_id="call-1",
                tool_name="get_payment",
                arguments={"payment_id": "payment-1"},
            ),
        ),
        allowed_tool_names={"get_order"},
    )

    assert source.calls == 0
    assert result.error is not None
    assert result.error.code is ToolCallBatchErrorCode.UNAUTHORIZED_TOOL


def test_valid_batch_preserves_day5_result_and_trace_for_each_call() -> None:
    source, records = make_source_and_records()
    result = execute_tool_calls(
        source,
        (
            ToolCall(
                call_id="call-1",
                tool_name="get_order",
                arguments={"order_id": "order-1"},
            ),
        ),
        allowed_tool_names={"get_order"},
        clock=iter((STARTED_AT, COMPLETED_AT)).__next__,
    )

    assert result.error is None
    assert result.results[0].data == records["get_order"]
    assert result.results[0].trace.call_id == "call-1"
