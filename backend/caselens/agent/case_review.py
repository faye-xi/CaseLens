import json
from datetime import datetime
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints, model_validator

from caselens.agent.loop import DEFAULT_MAX_STEPS, run_investigation
from caselens.agent.protocol import (
    InvestigationResult,
    InvestigationStatus,
    InvestigationTerminationReason,
)
from caselens.domain.decision import (
    DecisionDraft,
    DecisionPacket,
    DecisionPacketValidationError,
    DecisionRecommendation,
    RiskLevel,
    build_decision_packet,
)
from caselens.domain.evidence_assembly import (
    EvidenceAssemblyError,
    assemble_refund_not_received_evidence,
)
from caselens.domain.investigation import EvidenceBundle, EvidenceStatus
from caselens.domain.models import Case
from caselens.domain.policy import PolicyTimeline, PolicyVersionNotFoundError
from caselens.domain.policy_retrieval import (
    PolicyClauseCorpus,
    PolicyRetrievalRequest,
    PolicyRetrievalResult,
    retrieve_policy_clauses,
)
from caselens.model.protocol import (
    ModelClient,
    ModelError,
    ModelFinishReason,
    ModelMessage,
    ModelRequest,
    ModelRole,
    ModelTrace,
    parse_structured_output,
)
from caselens.tools.models import Identifier
from caselens.tools.protocol import ToolExecutionResult
from caselens.tools.source import BusinessDataSource

NonBlankText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
]


class CaseReviewStatus(StrEnum):
    COMPLETED = "completed"
    SAFE_TERMINATED = "safe_terminated"
    ERROR = "error"


class CaseReviewTerminationReason(StrEnum):
    COMPLETED = "completed"
    MISSING_EVIDENCE = "missing_evidence"
    EVIDENCE_CONFLICT = "evidence_conflict"
    POLICY_NO_MATCH = "policy_no_match"
    POLICY_VERSION_NOT_FOUND = "policy_version_not_found"
    MODEL_ERROR = "model_error"
    TOOL_BATCH_ERROR = "tool_batch_error"
    MAX_STEPS = "max_steps"
    EVIDENCE_SOURCE_ERROR = "evidence_source_error"
    INVALID_DRAFT = "invalid_draft"


class CaseReviewErrorCode(StrEnum):
    MODEL_ERROR = "model_error"
    POLICY_VERSION_NOT_FOUND = "policy_version_not_found"
    EVIDENCE_SOURCE_ERROR = "evidence_source_error"
    INVALID_DRAFT = "invalid_draft"


class CaseReviewError(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: CaseReviewErrorCode
    message: NonBlankText


class CaseReviewResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: Identifier
    status: CaseReviewStatus
    termination_reason: CaseReviewTerminationReason
    investigation: InvestigationResult
    evidence_bundle: EvidenceBundle | None = None
    policy_result: PolicyRetrievalResult | None = None
    decision_draft: DecisionDraft | None = None
    decision_packet: DecisionPacket | None = None
    draft_trace: ModelTrace | None = None
    error: CaseReviewError | None = None

    @model_validator(mode="after")
    def validate_outcome(self) -> "CaseReviewResult":
        if self.status is CaseReviewStatus.COMPLETED:
            if (
                self.termination_reason is not CaseReviewTerminationReason.COMPLETED
                or self.evidence_bundle is None
                or self.policy_result is None
                or self.decision_draft is None
                or self.decision_packet is None
                or self.error is not None
            ):
                raise ValueError(
                    "Completed case reviews require a complete decision packet."
                )
        elif self.status is CaseReviewStatus.ERROR:
            if self.error is None or self.decision_packet is not None:
                raise ValueError(
                    "Case review errors require an error without a packet."
                )
        elif self.error is not None:
            raise ValueError("Safe case review results cannot contain an error.")
        return self


def run_case_review(
    case: Case,
    model: ModelClient,
    source: BusinessDataSource,
    policy_timeline: PolicyTimeline,
    policy_corpus: PolicyClauseCorpus,
    *,
    collected_at: datetime,
    max_steps: int = DEFAULT_MAX_STEPS,
    request_id_prefix: str = "case-review",
) -> CaseReviewResult:
    investigation = run_investigation(
        model,
        source,
        _initial_messages(case),
        max_steps=max_steps,
        request_id_prefix=f"{request_id_prefix}-investigation",
    )
    if investigation.status is not InvestigationStatus.COMPLETED:
        return _result_from_investigation(case, investigation)

    tool_results = _tool_results(investigation)
    try:
        evidence_bundle = assemble_refund_not_received_evidence(
            case,
            tool_results,
            collected_at=collected_at,
        )
    except EvidenceAssemblyError as error:
        return CaseReviewResult(
            case_id=case.case_id,
            status=CaseReviewStatus.ERROR,
            termination_reason=CaseReviewTerminationReason.EVIDENCE_SOURCE_ERROR,
            investigation=investigation,
            error=CaseReviewError(
                code=CaseReviewErrorCode.EVIDENCE_SOURCE_ERROR,
                message=str(error),
            ),
        )

    try:
        policy_result = retrieve_policy_clauses(
            policy_timeline,
            policy_corpus,
            PolicyRetrievalRequest(
                query="refund not received",
                occurred_at=case.occurred_at,
            ),
        )
    except PolicyVersionNotFoundError as error:
        return CaseReviewResult(
            case_id=case.case_id,
            status=CaseReviewStatus.ERROR,
            termination_reason=CaseReviewTerminationReason.POLICY_VERSION_NOT_FOUND,
            investigation=investigation,
            evidence_bundle=evidence_bundle,
            error=CaseReviewError(
                code=CaseReviewErrorCode.POLICY_VERSION_NOT_FOUND,
                message=str(error),
            ),
        )

    safe_draft = _safe_draft(evidence_bundle, policy_result)
    if safe_draft is not None:
        return _build_safe_result(
            case,
            investigation,
            evidence_bundle,
            policy_result,
            safe_draft,
        )

    invocation = model.complete(
        _draft_request(
            case,
            evidence_bundle,
            policy_result,
            request_id=f"{request_id_prefix}-draft",
        )
    )
    if invocation.error is not None:
        return _invalid_draft_result(
            case,
            investigation,
            evidence_bundle,
            policy_result,
            invocation.trace,
            invocation.error,
        )

    response = invocation.response
    assert response is not None
    if response.finish_reason is not ModelFinishReason.STOP:
        return _invalid_draft_result(
            case,
            investigation,
            evidence_bundle,
            policy_result,
            invocation.trace,
            ModelError(
                code="invalid_structured_output",
                message="The decision draft model must return a STOP response.",
            ),
        )

    parsed = parse_structured_output(response, DecisionDraft)
    if parsed.error is not None or parsed.data is None:
        return _invalid_draft_result(
            case,
            investigation,
            evidence_bundle,
            policy_result,
            invocation.trace,
            parsed.error
            or ModelError(
                code="invalid_structured_output",
                message="The decision draft is missing.",
            ),
        )

    try:
        packet = build_decision_packet(
            evidence_bundle,
            policy_result,
            parsed.data,
        )
    except DecisionPacketValidationError as error:
        return _invalid_draft_result(
            case,
            investigation,
            evidence_bundle,
            policy_result,
            invocation.trace,
            ModelError(
                code="invalid_structured_output",
                message=f"The decision draft is invalid: {error.code.value}.",
            ),
        )

    return CaseReviewResult(
        case_id=case.case_id,
        status=CaseReviewStatus.COMPLETED,
        termination_reason=CaseReviewTerminationReason.COMPLETED,
        investigation=investigation,
        evidence_bundle=evidence_bundle,
        policy_result=policy_result,
        decision_draft=parsed.data,
        decision_packet=packet,
        draft_trace=invocation.trace,
    )


def _initial_messages(case: Case) -> tuple[ModelMessage, ...]:
    case_payload = json.dumps(
        case.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return (
        ModelMessage(
            role=ModelRole.SYSTEM,
            content=(
                "You are CaseLens read-only investigation agent. "
                "Use only declared read-only tools, never execute side effects, "
                "and never invent business facts. Stop after investigation."
            ),
        ),
        ModelMessage(
            role=ModelRole.USER,
            content=(
                f"Investigate this refund-not-received case. Case JSON: {case_payload}"
            ),
        ),
    )


def _tool_results(
    investigation: InvestigationResult,
) -> tuple[ToolExecutionResult, ...]:
    return tuple(
        message.tool_result
        for message in investigation.messages
        if message.tool_result is not None
    )


def _result_from_investigation(
    case: Case,
    investigation: InvestigationResult,
) -> CaseReviewResult:
    if investigation.termination_reason is InvestigationTerminationReason.MODEL_ERROR:
        return CaseReviewResult(
            case_id=case.case_id,
            status=CaseReviewStatus.ERROR,
            termination_reason=CaseReviewTerminationReason.MODEL_ERROR,
            investigation=investigation,
            error=CaseReviewError(
                code=CaseReviewErrorCode.MODEL_ERROR,
                message=(
                    investigation.model_error.message
                    if investigation.model_error is not None
                    else "The investigation model failed."
                ),
            ),
        )

    reason_by_termination = {
        InvestigationTerminationReason.TOOL_BATCH_ERROR: (
            CaseReviewTerminationReason.TOOL_BATCH_ERROR
        ),
        InvestigationTerminationReason.MAX_STEPS: (
            CaseReviewTerminationReason.MAX_STEPS
        ),
    }
    return CaseReviewResult(
        case_id=case.case_id,
        status=CaseReviewStatus.SAFE_TERMINATED,
        termination_reason=reason_by_termination[investigation.termination_reason],
        investigation=investigation,
    )


def _safe_draft(
    evidence_bundle: EvidenceBundle,
    policy_result: PolicyRetrievalResult,
) -> DecisionDraft | None:
    if evidence_bundle.status is EvidenceStatus.INCOMPLETE:
        return DecisionDraft(
            case_id=evidence_bundle.case_id,
            recommendation=DecisionRecommendation.REQUEST_EVIDENCE,
            rationale="Required refund evidence is missing.",
            risk_level=RiskLevel.LOW,
        )
    if evidence_bundle.status is EvidenceStatus.CONFLICTED:
        return DecisionDraft(
            case_id=evidence_bundle.case_id,
            recommendation=DecisionRecommendation.MANUAL_REVIEW,
            rationale="The investigation contains conflicting refund evidence.",
            risk_level=RiskLevel.MEDIUM,
        )
    if not policy_result.citations:
        return DecisionDraft(
            case_id=evidence_bundle.case_id,
            recommendation=DecisionRecommendation.MANUAL_REVIEW,
            rationale="No matching clause was found in the effective policy version.",
            risk_level=RiskLevel.MEDIUM,
        )
    return None


def _build_safe_result(
    case: Case,
    investigation: InvestigationResult,
    evidence_bundle: EvidenceBundle,
    policy_result: PolicyRetrievalResult,
    draft: DecisionDraft,
) -> CaseReviewResult:
    packet = build_decision_packet(evidence_bundle, policy_result, draft)
    reason = {
        DecisionRecommendation.REQUEST_EVIDENCE: CaseReviewTerminationReason.MISSING_EVIDENCE,
        DecisionRecommendation.MANUAL_REVIEW: (
            CaseReviewTerminationReason.EVIDENCE_CONFLICT
            if evidence_bundle.status is EvidenceStatus.CONFLICTED
            else CaseReviewTerminationReason.POLICY_NO_MATCH
        ),
    }[draft.recommendation]
    return CaseReviewResult(
        case_id=case.case_id,
        status=CaseReviewStatus.SAFE_TERMINATED,
        termination_reason=reason,
        investigation=investigation,
        evidence_bundle=evidence_bundle,
        policy_result=policy_result,
        decision_draft=draft,
        decision_packet=packet,
    )


def _draft_request(
    case: Case,
    evidence_bundle: EvidenceBundle,
    policy_result: PolicyRetrievalResult,
    *,
    request_id: str,
) -> ModelRequest:
    trusted_payload = json.dumps(
        {
            "case_id": case.case_id,
            "evidence_bundle": evidence_bundle.model_dump(mode="json"),
            "policy_result": policy_result.model_dump(mode="json"),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return ModelRequest(
        request_id=request_id,
        messages=(
            ModelMessage(
                role=ModelRole.SYSTEM,
                content=(
                    "You are the CaseLens decision drafting stage. "
                    "Return only the requested DecisionDraft schema. "
                    "Use only evidence and policy IDs present in the trusted context."
                ),
            ),
            ModelMessage(
                role=ModelRole.USER,
                content=f"Trusted case review context JSON: {trusted_payload}",
            ),
        ),
        tools=(),
        response_schema=DecisionDraft.model_json_schema(),
    )


def _invalid_draft_result(
    case: Case,
    investigation: InvestigationResult,
    evidence_bundle: EvidenceBundle,
    policy_result: PolicyRetrievalResult,
    draft_trace: ModelTrace,
    error: ModelError,
) -> CaseReviewResult:
    return CaseReviewResult(
        case_id=case.case_id,
        status=CaseReviewStatus.ERROR,
        termination_reason=CaseReviewTerminationReason.INVALID_DRAFT,
        investigation=investigation,
        evidence_bundle=evidence_bundle,
        policy_result=policy_result,
        draft_trace=draft_trace,
        error=CaseReviewError(
            code=CaseReviewErrorCode.INVALID_DRAFT,
            message=error.message,
        ),
    )
