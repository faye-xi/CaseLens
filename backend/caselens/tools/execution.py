import json
from collections.abc import Callable, Collection
from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType

from pydantic import BaseModel, ValidationError

from caselens.model.protocol import ToolDefinition
from caselens.tools.models import LogisticsQuery, MessageQuery, OrderQuery, PaymentQuery
from caselens.tools.protocol import (
    ToolCall,
    ToolCallBatchError,
    ToolCallBatchErrorCode,
    ToolCallBatchResult,
    ToolData,
    ToolError,
    ToolErrorCode,
    ToolExecutionResult,
    ToolTrace,
    ToolTraceStatus,
)
from caselens.tools.services import (
    get_logistics,
    get_messages,
    get_order,
    get_payment,
)
from caselens.tools.source import (
    BusinessDataSource,
    RecordNotFoundError,
    SourceQueryError,
    SourceTimeoutError,
)

Clock = Callable[[], datetime]
ToolHandler = Callable[[BusinessDataSource, BaseModel], ToolData]


@dataclass(frozen=True)
class RegisteredTool:
    name: str
    description: str
    query_model: type[BaseModel]
    handler: ToolHandler


def utc_now() -> datetime:
    return datetime.now(UTC)


def _run_order(source: BusinessDataSource, query: BaseModel) -> ToolData:
    return get_order(source, query)  # type: ignore[arg-type]


def _run_payment(source: BusinessDataSource, query: BaseModel) -> ToolData:
    return get_payment(source, query)  # type: ignore[arg-type]


def _run_logistics(source: BusinessDataSource, query: BaseModel) -> ToolData:
    return get_logistics(source, query)  # type: ignore[arg-type]


def _run_messages(source: BusinessDataSource, query: BaseModel) -> ToolData:
    return get_messages(source, query)  # type: ignore[arg-type]


TOOL_REGISTRY = MappingProxyType(
    {
        "get_order": RegisteredTool(
            name="get_order",
            description="Read an order record by order ID.",
            query_model=OrderQuery,
            handler=_run_order,
        ),
        "get_payment": RegisteredTool(
            name="get_payment",
            description="Read a payment and refund record by payment ID.",
            query_model=PaymentQuery,
            handler=_run_payment,
        ),
        "get_logistics": RegisteredTool(
            name="get_logistics",
            description="Read shipment tracking for an order.",
            query_model=LogisticsQuery,
            handler=_run_logistics,
        ),
        "get_messages": RegisteredTool(
            name="get_messages",
            description="Read customer and agent messages for an order.",
            query_model=MessageQuery,
            handler=_run_messages,
        ),
    }
)

_ERROR_MESSAGES: dict[ToolErrorCode, str] = {
    ToolErrorCode.UNKNOWN_TOOL: "The requested tool is not registered.",
    ToolErrorCode.INVALID_INPUT: "The tool arguments are invalid.",
    ToolErrorCode.NOT_FOUND: "The requested business record was not found.",
    ToolErrorCode.TIMEOUT: "The business data source timed out.",
    ToolErrorCode.SOURCE_ERROR: "The business data source query failed.",
    ToolErrorCode.INTERNAL_ERROR: "The tool call failed unexpectedly.",
}


def canonical_arguments_json(call: ToolCall) -> str:
    return json.dumps(
        call.arguments,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _trace(
    call: ToolCall,
    arguments_json: str,
    started_at: datetime,
    completed_at: datetime,
    error_code: ToolErrorCode | None = None,
) -> ToolTrace:
    return ToolTrace(
        call_id=call.call_id,
        tool_name=call.tool_name,
        arguments_json=arguments_json,
        started_at=started_at,
        completed_at=completed_at,
        duration_ms=max(
            0,
            int((completed_at - started_at).total_seconds() * 1000),
        ),
        status=(
            ToolTraceStatus.FAILED
            if error_code is not None
            else ToolTraceStatus.SUCCEEDED
        ),
        error_code=error_code,
    )


def _failure_result(
    call: ToolCall,
    arguments_json: str,
    started_at: datetime,
    completed_at: datetime,
    code: ToolErrorCode,
) -> ToolExecutionResult:
    return ToolExecutionResult(
        trace=_trace(
            call,
            arguments_json,
            started_at,
            completed_at,
            error_code=code,
        ),
        error=ToolError(code=code, message=_ERROR_MESSAGES[code]),
    )


def execute_tool(
    source: BusinessDataSource,
    call: ToolCall,
    *,
    clock: Clock = utc_now,
) -> ToolExecutionResult:
    started_at = clock()
    arguments_json = canonical_arguments_json(call)
    registered_tool = TOOL_REGISTRY.get(call.tool_name)
    if registered_tool is None:
        return _failure_result(
            call,
            arguments_json,
            started_at,
            clock(),
            ToolErrorCode.UNKNOWN_TOOL,
        )
    try:
        query = registered_tool.query_model.model_validate(call.arguments)
        data = registered_tool.handler(source, query)
    except ValidationError:
        error_code = ToolErrorCode.INVALID_INPUT
    except RecordNotFoundError:
        error_code = ToolErrorCode.NOT_FOUND
    except SourceTimeoutError:
        error_code = ToolErrorCode.TIMEOUT
    except SourceQueryError:
        error_code = ToolErrorCode.SOURCE_ERROR
    except Exception:  # noqa: BLE001
        # This is the safety boundary: callers receive no raw internal exception.
        error_code = ToolErrorCode.INTERNAL_ERROR
    else:
        completed_at = clock()
        return ToolExecutionResult(
            trace=_trace(
                call,
                arguments_json,
                started_at,
                completed_at,
            ),
            data=data,
        )
    completed_at = clock()
    return _failure_result(
        call,
        arguments_json,
        started_at,
        completed_at,
        error_code,
    )


_BATCH_ERROR_MESSAGES: dict[ToolCallBatchErrorCode, str] = {
    ToolCallBatchErrorCode.DUPLICATE_TOOL_CALL: (
        "The tool-call batch contains a duplicate call."
    ),
    ToolCallBatchErrorCode.UNAUTHORIZED_TOOL: (
        "The tool call is not allowed in this model request."
    ),
}


def execute_tool_calls(
    source: BusinessDataSource,
    calls: Collection[ToolCall],
    *,
    allowed_tool_names: Collection[str],
    clock: Clock = utc_now,
) -> ToolCallBatchResult:
    calls_tuple = tuple(calls)
    call_ids = [call.call_id for call in calls_tuple]
    semantic_calls = [
        (call.tool_name, canonical_arguments_json(call)) for call in calls_tuple
    ]
    if len(call_ids) != len(set(call_ids)) or len(semantic_calls) != len(
        set(semantic_calls)
    ):
        return ToolCallBatchResult(
            error=ToolCallBatchError(
                code=ToolCallBatchErrorCode.DUPLICATE_TOOL_CALL,
                message=_BATCH_ERROR_MESSAGES[
                    ToolCallBatchErrorCode.DUPLICATE_TOOL_CALL
                ],
            )
        )

    allowed_names = frozenset(allowed_tool_names)
    if any(call.tool_name not in allowed_names for call in calls_tuple):
        return ToolCallBatchResult(
            error=ToolCallBatchError(
                code=ToolCallBatchErrorCode.UNAUTHORIZED_TOOL,
                message=_BATCH_ERROR_MESSAGES[ToolCallBatchErrorCode.UNAUTHORIZED_TOOL],
            )
        )

    results = tuple(execute_tool(source, call, clock=clock) for call in calls_tuple)
    return ToolCallBatchResult(results=results)


def tool_definitions() -> tuple[ToolDefinition, ...]:
    return tuple(
        ToolDefinition(
            name=registered_tool.name,
            description=registered_tool.description,
            parameters_schema=registered_tool.query_model.model_json_schema(),
        )
        for registered_tool in sorted(
            TOOL_REGISTRY.values(), key=lambda tool: tool.name
        )
    )
