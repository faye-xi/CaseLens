"""Deterministic model interfaces used by the CaseLens investigation flow."""

from caselens.model.mock import MockModel
from caselens.model.protocol import (
    ModelClient,
    ModelError,
    ModelErrorCode,
    ModelFinishReason,
    ModelInvocationResult,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelRole,
    ModelTrace,
    ModelTraceStatus,
    StructuredOutputResult,
    ToolDefinition,
    parse_structured_output,
)

__all__ = [
    "MockModel",
    "ModelClient",
    "ModelError",
    "ModelErrorCode",
    "ModelFinishReason",
    "ModelInvocationResult",
    "ModelMessage",
    "ModelRequest",
    "ModelResponse",
    "ModelRole",
    "ModelTrace",
    "ModelTraceStatus",
    "StructuredOutputResult",
    "ToolDefinition",
    "parse_structured_output",
]
