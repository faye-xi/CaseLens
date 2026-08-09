from dataclasses import dataclass
from datetime import UTC, datetime

from caselens.domain.policy import PolicyTimeline, PolicyVersionNotFoundError
from caselens.domain.policy_retrieval import PolicyClauseCorpus
from caselens.evaluation.models import GoldenCase, HybridBehavior, SourceFailure
from caselens.model import MockModel, ModelFinishReason, ModelMessage, ModelResponse
from caselens.tools.protocol import ToolCall
from caselens.tools.source import InMemoryBusinessDataSource


@dataclass(frozen=True)
class EvaluationFixture:
    case: GoldenCase
    source: InMemoryBusinessDataSource
    timeline: PolicyTimeline
    corpus: PolicyClauseCorpus
    model: MockModel
    collected_at: datetime
    max_steps: int


def build_fixture(case: GoldenCase) -> EvaluationFixture:
    collected_at = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)
    timed_out_operations = (
        frozenset({"payments"})
        if case.input.source_failure is SourceFailure.TIMEOUT
        else frozenset()
    )
    source = InMemoryBusinessDataSource(
        payments=case.input.payments,
        timed_out_operations=timed_out_operations,
    )
    timeline = PolicyTimeline(
        policy_id=case.input.policy_versions[0].policy_id,
        versions=case.input.policy_versions,
    )
    corpus = PolicyClauseCorpus(clauses=case.input.policy_clauses)
    responses, max_steps = _hybrid_script(case, timeline)
    return EvaluationFixture(
        case=case,
        source=source,
        timeline=timeline,
        corpus=corpus,
        model=MockModel(
            responses,
            model_name="deterministic-evaluation-model",
            clock=lambda: collected_at,
        ),
        collected_at=collected_at,
        max_steps=max_steps,
    )


def _hybrid_script(
    case: GoldenCase,
    timeline: PolicyTimeline,
) -> tuple[tuple[ModelResponse, ...], int]:
    behavior = case.input.hybrid_behavior
    if behavior is HybridBehavior.UNAUTHORIZED_TOOL_CALL:
        return (_tool_response(case, "complete_refund"),), 8
    if behavior is HybridBehavior.MAX_STEPS:
        return (_tool_response(case, "get_payment"),), 1

    responses = [_tool_response(case, "get_payment"), _stop_response(case)]
    if behavior is HybridBehavior.INVALID_DRAFT:
        responses.append(_draft_response(case, timeline, trusted=False))
    else:
        responses.append(_draft_response(case, timeline, trusted=True))
    return tuple(responses), 8


def _tool_response(case: GoldenCase, tool_name: str) -> ModelResponse:
    arguments = (
        {"payment_id": case.input.case.payment_id}
        if tool_name == "get_payment"
        else {"case_id": case.input.case.case_id}
    )
    return ModelResponse(
        response_id=f"{case.case_id}:tool-response",
        finish_reason=ModelFinishReason.TOOL_CALLS,
        message=ModelMessage(
            role="assistant",
            tool_calls=(
                ToolCall(
                    call_id=f"{case.case_id}:tool-call",
                    tool_name=tool_name,
                    arguments=arguments,
                ),
            ),
        ),
    )


def _stop_response(case: GoldenCase) -> ModelResponse:
    return ModelResponse(
        response_id=f"{case.case_id}:stop-response",
        finish_reason=ModelFinishReason.STOP,
        message=ModelMessage(role="assistant", content="Investigation complete."),
    )


def _draft_response(
    case: GoldenCase,
    timeline: PolicyTimeline,
    *,
    trusted: bool,
) -> ModelResponse:
    refund_id = case.input.case.refund_id or "missing-refund"
    evidence_id = f"{case.input.case.case_id}:refund:{refund_id}"
    try:
        version = timeline.version_at(case.input.case.occurred_at).version
    except PolicyVersionNotFoundError:
        version = case.input.policy_versions[0].version
    clause_id = next(
        (
            clause.clause_id
            for clause in case.input.policy_clauses
            if clause.version == version
        ),
        "missing-clause",
    )
    structured_output = {
        "case_id": case.input.case.case_id,
        "recommendation": "approve_refund",
        "rationale": "The trusted refund remains processing under effective policy.",
        "risk_level": "high",
        "evidence_references": (
            [
                {
                    "evidence_id": evidence_id,
                    "fact_id": f"{evidence_id}:refund_received",
                }
            ]
            if trusted
            else []
        ),
        "policy_clause_ids": [clause_id],
    }
    return ModelResponse(
        response_id=f"{case.case_id}:draft-response",
        finish_reason=ModelFinishReason.STOP,
        message=ModelMessage(role="assistant"),
        structured_output=structured_output,
    )
