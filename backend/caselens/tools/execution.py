import json
from collections.abc import Callable
from datetime import UTC, datetime

from pydantic import JsonValue, ValidationError

from caselens.tools.models import LogisticsQuery, MessageQuery, OrderQuery, PaymentQuery
from caselens.tools.protocol import (
    ToolCall,
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
ToolHandler = Callable[[BusinessDataSource, dict[str, JsonValue]], ToolData]


def utc_now() -> datetime:
    return datetime.now(UTC)


def _run_order(source: BusinessDataSource, arguments: dict[str, JsonValue]) -> ToolData:
    return get_order(source, OrderQuery.model_validate(arguments))


def _run_payment(
    source: BusinessDataSource, arguments: dict[str, JsonValue]
) -> ToolData:
    return get_payment(source, PaymentQuery.model_validate(arguments))


def _run_logistics(
    source: BusinessDataSource, arguments: dict[str, JsonValue]
) -> ToolData:
    return get_logistics(source, LogisticsQuery.model_validate(arguments))


def _run_messages(
    source: BusinessDataSource, arguments: dict[str, JsonValue]
) -> ToolData:
    return get_messages(source, MessageQuery.model_validate(arguments))


_TOOL_HANDLERS: dict[str, ToolHandler] = {
    "get_order": _run_order,
    "get_payment": _run_payment,
    "get_logistics": _run_logistics,
    "get_messages": _run_messages,
}

_ERROR_MESSAGES: dict[ToolErrorCode, str] = {
    ToolErrorCode.UNKNOWN_TOOL: "The requested tool is not registered.",
    ToolErrorCode.INVALID_INPUT: "The tool arguments are invalid.",
    ToolErrorCode.NOT_FOUND: "The requested business record was not found.",
    ToolErrorCode.TIMEOUT: "The business data source timed out.",
    ToolErrorCode.SOURCE_ERROR: "The business data source query failed.",
    ToolErrorCode.INTERNAL_ERROR: "The tool call failed unexpectedly.",
}


def _arguments_json(call: ToolCall) -> str:
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
    arguments_json = _arguments_json(call)
    handler = _TOOL_HANDLERS.get(call.tool_name)
    if handler is None:
        return _failure_result(
            call,
            arguments_json,
            started_at,
            clock(),
            ToolErrorCode.UNKNOWN_TOOL,
        )
    try:
        data = handler(source, call.arguments)
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
