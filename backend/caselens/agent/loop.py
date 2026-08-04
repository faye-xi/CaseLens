from collections.abc import Collection

from caselens.agent.protocol import (
    InvestigationResult,
    InvestigationStatus,
    InvestigationTerminationReason,
)
from caselens.model.protocol import (
    ModelClient,
    ModelFinishReason,
    ModelMessage,
    ModelRequest,
    ModelTrace,
)
from caselens.tools.execution import execute_tool_calls, tool_definitions
from caselens.tools.source import BusinessDataSource

DEFAULT_MAX_STEPS = 8


def run_investigation(
    model: ModelClient,
    source: BusinessDataSource,
    messages: Collection[ModelMessage],
    *,
    max_steps: int = DEFAULT_MAX_STEPS,
    request_id_prefix: str = "investigation",
) -> InvestigationResult:
    if max_steps < 1:
        raise ValueError("max_steps must be at least 1.")
    if not request_id_prefix.strip():
        raise ValueError("request_id_prefix must not be blank.")

    history = list(messages)
    if not history:
        raise ValueError("Investigation messages must not be empty.")

    definitions = tool_definitions()
    allowed_tool_names = frozenset(definition.name for definition in definitions)
    model_traces: list[ModelTrace] = []

    for step in range(1, max_steps + 1):
        invocation = model.complete(
            ModelRequest(
                request_id=f"{request_id_prefix}-step-{step}",
                messages=tuple(history),
                tools=definitions,
            )
        )
        model_traces.append(invocation.trace)

        if invocation.error is not None:
            return InvestigationResult(
                status=InvestigationStatus.ERROR,
                termination_reason=InvestigationTerminationReason.MODEL_ERROR,
                steps=step,
                messages=tuple(history),
                model_traces=tuple(model_traces),
                model_error=invocation.error,
            )

        response = invocation.response
        assert response is not None
        history.append(response.message)

        if response.finish_reason is ModelFinishReason.STOP:
            return InvestigationResult(
                status=InvestigationStatus.COMPLETED,
                termination_reason=InvestigationTerminationReason.COMPLETED,
                steps=step,
                messages=tuple(history),
                final_response=response,
                model_traces=tuple(model_traces),
            )

        batch = execute_tool_calls(
            source,
            response.message.tool_calls,
            allowed_tool_names=allowed_tool_names,
        )
        if batch.error is not None:
            return InvestigationResult(
                status=InvestigationStatus.SAFE_TERMINATED,
                termination_reason=InvestigationTerminationReason.TOOL_BATCH_ERROR,
                steps=step,
                messages=tuple(history),
                model_traces=tuple(model_traces),
                tool_batch_error=batch.error,
            )

        for tool_result in batch.results:
            history.append(
                ModelMessage(
                    role="tool",
                    tool_call_id=tool_result.trace.call_id,
                    tool_result=tool_result,
                )
            )

        if step == max_steps:
            return InvestigationResult(
                status=InvestigationStatus.SAFE_TERMINATED,
                termination_reason=InvestigationTerminationReason.MAX_STEPS,
                steps=step,
                messages=tuple(history),
                model_traces=tuple(model_traces),
            )

    raise AssertionError("The investigation loop must return before exhausting steps.")
