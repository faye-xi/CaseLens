from decimal import Decimal
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from caselens.agent.case_review import (
    CaseReviewStatus,
    CaseReviewTerminationReason,
)
from caselens.domain.decision import DecisionRecommendation
from caselens.domain.investigation import EvidenceStatus
from caselens.domain.models import Case
from caselens.domain.policy import PolicyVersion
from caselens.domain.policy_retrieval import PolicyClause
from caselens.resolution.models import ResolutionStatus, VerificationStatus
from caselens.tools.models import PaymentRecord

Identifier = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class EvaluationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class BaselineId(StrEnum):
    RULES_ONLY = "rules_only"
    MODEL_ONLY_SCRIPTED = "model_only_scripted"
    HYBRID = "hybrid"


class ScenarioId(StrEnum):
    PROCESSING_REFUND_V1 = "processing_refund_v1"
    POLICY_BOUNDARY_V2 = "policy_boundary_v2"
    REFUND_RECORD_MISSING = "refund_record_missing"
    CUSTOMER_CLAIM_CONFLICT = "customer_claim_conflicts_with_succeeded_refund"
    POLICY_CLAUSE_NO_MATCH = "policy_clause_no_match"
    POLICY_TIMELINE_GAP = "policy_timeline_gap"
    PAYMENT_TOOL_TIMEOUT = "payment_tool_timeout"
    UNAUTHORIZED_TOOL_CALL = "unauthorized_tool_call"
    AGENT_MAX_STEPS = "agent_max_steps"
    INVALID_OR_UNTRUSTED_DRAFT = "invalid_or_untrusted_draft"
    EXECUTE_BEFORE_APPROVAL_AND_RETRY = "execute_before_approval_and_retry"
    VERIFICATION_MISMATCH = "verification_mismatch"


class MeasurementState(StrEnum):
    MEASURED = "measured"
    NOT_MEASURED = "not_measured"


class Applicability(StrEnum):
    APPLICABLE = "applicable"
    NOT_APPLICABLE = "not_applicable"


class SourceFailure(StrEnum):
    NONE = "none"
    TIMEOUT = "timeout"


class HybridBehavior(StrEnum):
    STANDARD = "standard"
    UNAUTHORIZED_TOOL_CALL = "unauthorized_tool_call"
    MAX_STEPS = "max_steps"
    INVALID_DRAFT = "invalid_draft"


class VerifierBehavior(StrEnum):
    ACTUAL = "actual"
    MISMATCH = "mismatch"


class WorkflowOperation(StrEnum):
    APPROVE = "approve"
    EXECUTE = "execute"
    VERIFY = "verify"


class ScriptedCandidate(EvaluationModel):
    recommendation: DecisionRecommendation | None = None
    policy_version: Identifier | None = None
    claims_action_succeeded: bool = False


class EvaluationInput(EvaluationModel):
    case: Case
    payments: tuple[PaymentRecord, ...] = ()
    policy_versions: tuple[PolicyVersion, ...] = Field(min_length=1)
    policy_clauses: tuple[PolicyClause, ...] = ()
    model_only_candidate: ScriptedCandidate
    source_failure: SourceFailure = SourceFailure.NONE
    hybrid_behavior: HybridBehavior = HybridBehavior.STANDARD
    verifier_behavior: VerifierBehavior = VerifierBehavior.ACTUAL
    operation_script: tuple[WorkflowOperation, ...] = ()


class GoldenExpectation(EvaluationModel):
    review_status: CaseReviewStatus | None = None
    termination_reason: CaseReviewTerminationReason | None = None
    recommendation: DecisionRecommendation | None = None
    evidence_status: EvidenceStatus | None = None
    policy_version: Identifier | None = None
    packet_expected: bool
    required_tools: tuple[Identifier, ...] = ()
    forbidden_tools: tuple[Identifier, ...] = ()
    workflow_status: ResolutionStatus | None = None
    verifier_status: VerificationStatus | None = None
    max_illegal_tool_executions: int = Field(default=0, ge=0)
    max_state_changes: int = Field(default=0, ge=0)
    max_unverified_successes: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_tool_sets(self) -> "GoldenExpectation":
        required = set(self.required_tools)
        forbidden = set(self.forbidden_tools)
        if len(required) != len(self.required_tools):
            raise ValueError("Duplicate required tool.")
        if len(forbidden) != len(self.forbidden_tools):
            raise ValueError("Duplicate forbidden tool.")
        if required & forbidden:
            raise ValueError("A tool cannot be both required and forbidden.")
        return self


class GoldenCase(EvaluationModel):
    case_id: Identifier
    scenario: ScenarioId
    description: Identifier
    applicable_baselines: tuple[BaselineId, ...] = Field(min_length=1)
    input: EvaluationInput
    expectation: GoldenExpectation

    @model_validator(mode="after")
    def validate_identity_and_baselines(self) -> "GoldenCase":
        if self.case_id != self.scenario.value:
            raise ValueError("Golden Case ID must match its scenario ID.")
        if len(set(self.applicable_baselines)) != len(self.applicable_baselines):
            raise ValueError("Duplicate applicable baseline.")
        return self


class EvaluationOutcome(EvaluationModel):
    case_id: Identifier
    baseline_id: BaselineId
    applicability: Applicability
    review_status: CaseReviewStatus | None = None
    termination_reason: CaseReviewTerminationReason | None = None
    recommendation: DecisionRecommendation | None = None
    evidence_status: EvidenceStatus | None = None
    policy_version: Identifier | None = None
    packet_created: bool
    tool_calls: tuple[Identifier, ...] = ()
    illegal_tool_attempt_count: int = Field(default=0, ge=0)
    illegal_tool_execution_count: int = Field(default=0, ge=0)
    workflow_status: ResolutionStatus | None = None
    verifier_status: VerificationStatus | None = None
    side_effect_attempt_count: int = Field(default=0, ge=0)
    state_change_count: int = Field(default=0, ge=0)
    ungrounded_finalization_count: int = Field(default=0, ge=0)
    unverified_success_count: int = Field(default=0, ge=0)
    token_measurement: MeasurementState = MeasurementState.NOT_MEASURED
    token_count: int | None = Field(default=None, ge=0)
    latency_measurement: MeasurementState = MeasurementState.NOT_MEASURED
    latency_ms: Decimal | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_measurements_and_applicability(self) -> "EvaluationOutcome":
        if (self.token_measurement is MeasurementState.NOT_MEASURED) != (
            self.token_count is None
        ):
            raise ValueError("token_count must be absent exactly when not measured.")
        if (self.latency_measurement is MeasurementState.NOT_MEASURED) != (
            self.latency_ms is None
        ):
            raise ValueError("latency_ms must be absent exactly when not measured.")
        if self.applicability is Applicability.NOT_APPLICABLE:
            substantive_values = (
                self.review_status,
                self.termination_reason,
                self.recommendation,
                self.evidence_status,
                self.policy_version,
                self.workflow_status,
                self.verifier_status,
            )
            substantive_counts = (
                self.illegal_tool_attempt_count,
                self.illegal_tool_execution_count,
                self.side_effect_attempt_count,
                self.state_change_count,
                self.ungrounded_finalization_count,
                self.unverified_success_count,
            )
            if (
                any(value is not None for value in substantive_values)
                or any(substantive_counts)
                or self.packet_created
                or self.tool_calls
            ):
                raise ValueError("Non-applicable outcomes cannot claim results.")
        return self
