from enum import StrEnum

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    model_validator,
)

from caselens.tools.models import (
    Identifier,
    MessageHistory,
    NonBlankText,
    OrderRecord,
    PaymentRecord,
    ShipmentRecord,
)


class ToolProtocolModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class ToolErrorCode(StrEnum):
    UNKNOWN_TOOL = "unknown_tool"
    INVALID_INPUT = "invalid_input"
    NOT_FOUND = "not_found"
    TIMEOUT = "timeout"
    SOURCE_ERROR = "source_error"
    INTERNAL_ERROR = "internal_error"


class ToolTraceStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ToolCall(ToolProtocolModel):
    call_id: Identifier
    tool_name: Identifier
    arguments: dict[str, JsonValue] = Field(default_factory=dict)


class ToolError(ToolProtocolModel):
    code: ToolErrorCode
    message: NonBlankText


class ToolCallBatchErrorCode(StrEnum):
    DUPLICATE_TOOL_CALL = "duplicate_tool_call"
    UNAUTHORIZED_TOOL = "unauthorized_tool"


class ToolCallBatchError(ToolProtocolModel):
    code: ToolCallBatchErrorCode
    message: NonBlankText


class ToolTrace(ToolProtocolModel):
    call_id: Identifier
    tool_name: Identifier
    arguments_json: NonBlankText
    started_at: AwareDatetime
    completed_at: AwareDatetime
    duration_ms: int = Field(ge=0)
    status: ToolTraceStatus
    error_code: ToolErrorCode | None = None

    @model_validator(mode="after")
    def validate_outcome(self) -> "ToolTrace":
        is_failed = self.status is ToolTraceStatus.FAILED
        has_error_code = self.error_code is not None
        if is_failed != has_error_code:
            raise ValueError("Failed traces require exactly one error code.")
        return self


type ToolData = OrderRecord | PaymentRecord | ShipmentRecord | MessageHistory


class ToolExecutionResult(ToolProtocolModel):
    trace: ToolTrace
    data: ToolData | None = None
    error: ToolError | None = None

    @model_validator(mode="after")
    def validate_outcome(self) -> "ToolExecutionResult":
        has_data = self.data is not None
        has_error = self.error is not None
        if has_data == has_error:
            raise ValueError("Exactly one of data or error is required.")
        if has_data:
            if (
                self.trace.status is not ToolTraceStatus.SUCCEEDED
                or self.trace.error_code is not None
            ):
                raise ValueError("Successful data requires a successful trace.")
            return self
        if (
            self.trace.status is not ToolTraceStatus.FAILED
            or self.trace.error_code is not self.error.code
        ):
            raise ValueError("Tool error and failed trace must have matching codes.")
        return self


class ToolCallBatchResult(ToolProtocolModel):
    results: tuple[ToolExecutionResult, ...] = ()
    error: ToolCallBatchError | None = None

    @model_validator(mode="after")
    def validate_outcome(self) -> "ToolCallBatchResult":
        if self.error is not None and self.results:
            raise ValueError("A failed tool-call batch cannot contain results.")
        if self.error is None and not self.results:
            raise ValueError("A successful tool-call batch requires results.")
        return self
