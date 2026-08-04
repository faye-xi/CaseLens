from enum import StrEnum
from typing import Protocol

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    ValidationError,
    model_validator,
)

from caselens.tools.models import Identifier, NonBlankText
from caselens.tools.protocol import ToolCall, ToolExecutionResult


class ModelProtocolModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class ModelRole(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class ModelFinishReason(StrEnum):
    STOP = "stop"
    TOOL_CALLS = "tool_calls"


class ModelTraceStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ModelErrorCode(StrEnum):
    INVALID_RESPONSE = "invalid_response"
    INVALID_STRUCTURED_OUTPUT = "invalid_structured_output"
    MOCK_SCRIPT_EXHAUSTED = "mock_script_exhausted"


class ModelMessage(ModelProtocolModel):
    role: ModelRole
    content: NonBlankText | None = None
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: Identifier | None = None
    tool_result: ToolExecutionResult | None = None

    @model_validator(mode="after")
    def validate_role_fields(self) -> "ModelMessage":
        if self.role in {ModelRole.SYSTEM, ModelRole.USER}:
            if self.content is None or self.tool_calls or self.tool_call_id:
                raise ValueError("System and user messages require text only.")
            if self.tool_result is not None:
                raise ValueError(
                    "System and user messages cannot contain tool results."
                )
            return self

        if self.role is ModelRole.ASSISTANT:
            if self.tool_call_id or self.tool_result is not None:
                raise ValueError("Assistant messages cannot contain tool results.")
            return self

        if (
            self.content is not None
            or not self.tool_call_id
            or self.tool_result is None
            or self.tool_calls
        ):
            raise ValueError(
                "Tool messages require a tool call ID and structured tool result."
            )
        if self.tool_call_id != self.tool_result.trace.call_id:
            raise ValueError("Tool message ID must match the tool result trace.")
        return self


class ToolDefinition(ModelProtocolModel):
    name: Identifier
    description: NonBlankText
    parameters_schema: dict[str, JsonValue]


class ModelRequest(ModelProtocolModel):
    request_id: Identifier
    messages: tuple[ModelMessage, ...] = Field(min_length=1)
    tools: tuple[ToolDefinition, ...] = ()
    response_schema: dict[str, JsonValue] | None = None

    @model_validator(mode="after")
    def validate_unique_tools(self) -> "ModelRequest":
        names = [tool.name for tool in self.tools]
        if len(names) != len(set(names)):
            raise ValueError("Duplicate model tool definition.")
        return self


class ModelResponse(ModelProtocolModel):
    response_id: Identifier
    finish_reason: ModelFinishReason
    message: ModelMessage
    structured_output: dict[str, JsonValue] | None = None

    @model_validator(mode="after")
    def validate_response_shape(self) -> "ModelResponse":
        if self.message.role is not ModelRole.ASSISTANT:
            raise ValueError("Model responses must contain an assistant message.")

        has_tool_calls = bool(self.message.tool_calls)
        if self.finish_reason is ModelFinishReason.STOP and has_tool_calls:
            raise ValueError("Stop responses cannot contain tool calls.")
        if self.finish_reason is ModelFinishReason.TOOL_CALLS and not has_tool_calls:
            raise ValueError("Tool-call responses require at least one tool call.")
        if self.finish_reason is ModelFinishReason.TOOL_CALLS and (
            self.structured_output is not None
        ):
            raise ValueError("Tool-call responses cannot contain structured output.")
        if self.finish_reason is ModelFinishReason.STOP and (
            self.message.content is None and self.structured_output is None
        ):
            raise ValueError("Stop responses require text or structured output.")
        return self


class ModelError(ModelProtocolModel):
    code: ModelErrorCode
    message: NonBlankText


class ModelTrace(ModelProtocolModel):
    request_id: Identifier
    implementation: NonBlankText
    started_at: AwareDatetime
    completed_at: AwareDatetime
    duration_ms: int = Field(ge=0)
    status: ModelTraceStatus
    response_id: Identifier | None = None
    finish_reason: ModelFinishReason | None = None
    tool_call_ids: tuple[Identifier, ...] = ()
    error_code: ModelErrorCode | None = None

    @model_validator(mode="after")
    def validate_outcome(self) -> "ModelTrace":
        is_failed = self.status is ModelTraceStatus.FAILED
        has_error_code = self.error_code is not None
        if is_failed != has_error_code:
            raise ValueError("Failed model traces require exactly one error code.")
        if is_failed and (
            self.response_id is not None or self.finish_reason is not None
        ):
            raise ValueError(
                "Failed model traces cannot contain a successful response."
            )
        return self


class ModelInvocationResult(ModelProtocolModel):
    trace: ModelTrace
    response: ModelResponse | None = None
    error: ModelError | None = None

    @model_validator(mode="after")
    def validate_outcome(self) -> "ModelInvocationResult":
        has_response = self.response is not None
        has_error = self.error is not None
        if has_response == has_error:
            raise ValueError("Exactly one of response or error is required.")
        if has_response:
            if (
                self.trace.status is not ModelTraceStatus.SUCCEEDED
                or self.trace.error_code is not None
            ):
                raise ValueError(
                    "Successful model responses require a successful trace."
                )
            return self
        if (
            self.trace.status is not ModelTraceStatus.FAILED
            or self.trace.error_code is not self.error.code
        ):
            raise ValueError("Model error and failed trace must have matching codes.")
        return self


class StructuredOutputResult[T: BaseModel](ModelProtocolModel):
    data: T | None = None
    error: ModelError | None = None

    @model_validator(mode="after")
    def validate_outcome(self) -> "StructuredOutputResult[T]":
        if (self.data is None) == (self.error is None):
            raise ValueError("Exactly one of structured data or error is required.")
        return self


def parse_structured_output[T: BaseModel](
    response: ModelResponse,
    output_model: type[T],
) -> StructuredOutputResult[T]:
    if response.structured_output is None:
        return StructuredOutputResult(
            error=ModelError(
                code=ModelErrorCode.INVALID_STRUCTURED_OUTPUT,
                message="The model did not return structured output.",
            )
        )
    try:
        data = output_model.model_validate(response.structured_output)
    except ValidationError:
        return StructuredOutputResult(
            error=ModelError(
                code=ModelErrorCode.INVALID_STRUCTURED_OUTPUT,
                message="The model structured output is invalid.",
            )
        )
    return StructuredOutputResult(data=data)


class ModelClient(Protocol):
    def complete(self, request: ModelRequest) -> ModelInvocationResult: ...
