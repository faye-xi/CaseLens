from collections.abc import Callable, Iterable
from datetime import UTC, datetime

from pydantic import ValidationError

from caselens.model.protocol import (
    ModelClient,
    ModelError,
    ModelErrorCode,
    ModelInvocationResult,
    ModelRequest,
    ModelResponse,
    ModelTrace,
    ModelTraceStatus,
)

Clock = Callable[[], datetime]


def utc_now() -> datetime:
    return datetime.now(UTC)


class MockModel(ModelClient):
    def __init__(
        self,
        responses: Iterable[object],
        *,
        model_name: str = "mock",
        clock: Clock = utc_now,
    ) -> None:
        if not model_name.strip():
            raise ValueError("The mock model name must not be blank.")
        self._responses = iter(responses)
        self._model_name = model_name
        self._clock = clock
        self._received_requests: list[ModelRequest] = []

    @property
    def received_requests(self) -> tuple[ModelRequest, ...]:
        return tuple(self._received_requests)

    def complete(self, request: ModelRequest) -> ModelInvocationResult:
        started_at = self._clock()
        self._received_requests.append(request)
        try:
            scripted_response = next(self._responses)
        except StopIteration:
            return self._failure_result(
                request,
                started_at,
                ModelErrorCode.MOCK_SCRIPT_EXHAUSTED,
            )

        try:
            response = ModelResponse.model_validate(scripted_response)
        except ValidationError:
            return self._failure_result(
                request,
                started_at,
                ModelErrorCode.INVALID_RESPONSE,
            )

        completed_at = self._clock()
        trace = self._trace(
            request,
            started_at,
            completed_at,
            status=ModelTraceStatus.SUCCEEDED,
            response=response,
        )
        return ModelInvocationResult(trace=trace, response=response)

    def _failure_result(
        self,
        request: ModelRequest,
        started_at: datetime,
        error_code: ModelErrorCode,
    ) -> ModelInvocationResult:
        completed_at = self._clock()
        trace = self._trace(
            request,
            started_at,
            completed_at,
            status=ModelTraceStatus.FAILED,
            error_code=error_code,
        )
        return ModelInvocationResult(
            trace=trace,
            error=ModelError(
                code=error_code,
                message=_ERROR_MESSAGES[error_code],
            ),
        )

    def _trace(
        self,
        request: ModelRequest,
        started_at: datetime,
        completed_at: datetime,
        *,
        status: ModelTraceStatus,
        response: ModelResponse | None = None,
        error_code: ModelErrorCode | None = None,
    ) -> ModelTrace:
        return ModelTrace(
            request_id=request.request_id,
            implementation=self._model_name,
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=max(
                0,
                int((completed_at - started_at).total_seconds() * 1000),
            ),
            status=status,
            response_id=response.response_id if response is not None else None,
            finish_reason=response.finish_reason if response is not None else None,
            tool_call_ids=(
                tuple(call.call_id for call in response.message.tool_calls)
                if response is not None
                else ()
            ),
            error_code=error_code,
        )


_ERROR_MESSAGES: dict[ModelErrorCode, str] = {
    ModelErrorCode.INVALID_RESPONSE: "The model response is invalid.",
    ModelErrorCode.INVALID_STRUCTURED_OUTPUT: (
        "The model structured output is invalid."
    ),
    ModelErrorCode.MOCK_SCRIPT_EXHAUSTED: "The mock model script is exhausted.",
}
