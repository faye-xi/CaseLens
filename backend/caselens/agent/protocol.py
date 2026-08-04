from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from caselens.model.protocol import (
    ModelError,
    ModelMessage,
    ModelResponse,
    ModelTrace,
)
from caselens.tools.protocol import ToolCallBatchError


class AgentProtocolModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class InvestigationStatus(StrEnum):
    COMPLETED = "completed"
    ERROR = "error"
    SAFE_TERMINATED = "safe_terminated"


class InvestigationTerminationReason(StrEnum):
    COMPLETED = "completed"
    MODEL_ERROR = "model_error"
    TOOL_BATCH_ERROR = "tool_batch_error"
    MAX_STEPS = "max_steps"


class InvestigationResult(AgentProtocolModel):
    status: InvestigationStatus
    termination_reason: InvestigationTerminationReason
    steps: int = Field(ge=0)
    messages: tuple[ModelMessage, ...] = ()
    final_response: ModelResponse | None = None
    model_traces: tuple[ModelTrace, ...] = ()
    model_error: ModelError | None = None
    tool_batch_error: ToolCallBatchError | None = None

    @model_validator(mode="after")
    def validate_outcome(self) -> "InvestigationResult":
        if self.status is InvestigationStatus.COMPLETED:
            if (
                self.termination_reason is not InvestigationTerminationReason.COMPLETED
                or self.final_response is None
                or self.model_error is not None
                or self.tool_batch_error is not None
            ):
                raise ValueError(
                    "Completed investigations require a final model response only."
                )
            return self

        if self.final_response is not None:
            raise ValueError(
                "Terminated investigations cannot contain a final response."
            )

        if self.status is InvestigationStatus.ERROR:
            if (
                self.termination_reason
                is not InvestigationTerminationReason.MODEL_ERROR
                or self.model_error is None
                or self.tool_batch_error is not None
            ):
                raise ValueError(
                    "Model errors require an error status and model error only."
                )
            return self

        if self.termination_reason is InvestigationTerminationReason.TOOL_BATCH_ERROR:
            if self.tool_batch_error is None or self.model_error is not None:
                raise ValueError("Tool batch termination requires a tool batch error.")
            return self

        if (
            self.termination_reason is not InvestigationTerminationReason.MAX_STEPS
            or self.model_error is not None
            or self.tool_batch_error is not None
        ):
            raise ValueError(
                "Safe termination requires a maximum-step or batch reason."
            )
        return self
