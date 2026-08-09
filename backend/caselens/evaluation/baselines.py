from collections.abc import Mapping
from datetime import timedelta
from tempfile import TemporaryDirectory
from types import MappingProxyType
from typing import Protocol

from caselens.agent.case_review import (
    CaseReviewResult,
    CaseReviewStatus,
    CaseReviewTerminationReason,
    run_case_review,
)
from caselens.domain.decision import (
    DecisionDraft,
    DecisionRecommendation,
    RiskLevel,
    build_decision_packet,
)
from caselens.domain.evidence_assembly import (
    EvidenceAssemblyError,
    assemble_refund_not_received_evidence,
)
from caselens.domain.investigation import (
    EvidenceKind,
    EvidenceStatus,
    FactKey,
    FactReference,
)
from caselens.domain.policy import PolicyVersionNotFoundError
from caselens.domain.policy_retrieval import (
    PolicyRetrievalRequest,
    retrieve_policy_clauses,
)
from caselens.evaluation.fixtures import build_fixture
from caselens.evaluation.models import (
    Applicability,
    BaselineId,
    EvaluationOutcome,
    GoldenCase,
    ScriptedCandidate,
    VerifierBehavior,
    WorkflowOperation,
)
from caselens.model import (
    MockModel,
    ModelFinishReason,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelRole,
    parse_structured_output,
)
from caselens.resolution.models import (
    ApprovalDecision,
    RefundSnapshot,
)
from caselens.resolution.service import ResolutionWorkflow
from caselens.resolution.store import IllegalTransitionError, SqliteResolutionStore
from caselens.tools.execution import execute_tool
from caselens.tools.models import RefundStatus
from caselens.tools.protocol import ToolCall


class BaselineRunner(Protocol):
    baseline_id: BaselineId

    def run(self, case: GoldenCase) -> EvaluationOutcome: ...


class RulesOnlyBaseline:
    baseline_id = BaselineId.RULES_ONLY

    def run(self, case: GoldenCase) -> EvaluationOutcome:
        if self.baseline_id not in case.applicable_baselines:
            return _not_applicable(case, self.baseline_id)
        fixture = build_fixture(case)
        tool_result = execute_tool(
            fixture.source,
            ToolCall(
                call_id=f"{case.case_id}:rules-payment",
                tool_name="get_payment",
                arguments={"payment_id": case.input.case.payment_id},
            ),
            clock=lambda: fixture.collected_at,
        )
        try:
            evidence = assemble_refund_not_received_evidence(
                case.input.case,
                (tool_result,),
                collected_at=fixture.collected_at,
            )
        except EvidenceAssemblyError:
            return EvaluationOutcome(
                case_id=case.case_id,
                baseline_id=self.baseline_id,
                applicability=Applicability.APPLICABLE,
                review_status=CaseReviewStatus.ERROR,
                termination_reason=CaseReviewTerminationReason.EVIDENCE_SOURCE_ERROR,
                packet_created=False,
                tool_calls=("get_payment",),
            )
        try:
            policy = retrieve_policy_clauses(
                fixture.timeline,
                fixture.corpus,
                PolicyRetrievalRequest(
                    query="refund not received",
                    occurred_at=case.input.case.occurred_at,
                ),
            )
        except PolicyVersionNotFoundError:
            return EvaluationOutcome(
                case_id=case.case_id,
                baseline_id=self.baseline_id,
                applicability=Applicability.APPLICABLE,
                review_status=CaseReviewStatus.ERROR,
                termination_reason=CaseReviewTerminationReason.POLICY_VERSION_NOT_FOUND,
                evidence_status=evidence.status,
                packet_created=False,
                tool_calls=("get_payment",),
            )

        draft, status, termination = _rules_draft(evidence, policy)
        packet = build_decision_packet(evidence, policy, draft)
        return EvaluationOutcome(
            case_id=case.case_id,
            baseline_id=self.baseline_id,
            applicability=Applicability.APPLICABLE,
            review_status=status,
            termination_reason=termination,
            recommendation=packet.recommendation,
            evidence_status=packet.evidence_status,
            policy_version=packet.selected_policy_version.version,
            packet_created=True,
            tool_calls=("get_payment",),
        )


class ModelOnlyScriptedBaseline:
    baseline_id = BaselineId.MODEL_ONLY_SCRIPTED

    def run(self, case: GoldenCase) -> EvaluationOutcome:
        if self.baseline_id not in case.applicable_baselines:
            return _not_applicable(case, self.baseline_id)
        response = ModelResponse(
            response_id=f"{case.case_id}:model-only-response",
            finish_reason=ModelFinishReason.STOP,
            message=ModelMessage(role="assistant"),
            structured_output=case.input.model_only_candidate.model_dump(mode="json"),
        )
        model = MockModel((response,), model_name="scripted-model-only")
        invocation = model.complete(
            ModelRequest(
                request_id=f"{case.case_id}:model-only",
                messages=(
                    ModelMessage(
                        role="user",
                        content=(
                            f"Case: {case.input.case.customer_statement} Policy text: "
                            + " ".join(
                                clause.text for clause in case.input.policy_clauses
                            )
                        ),
                    ),
                ),
                response_schema=ScriptedCandidate.model_json_schema(),
            )
        )
        assert invocation.response is not None
        parsed = parse_structured_output(invocation.response, ScriptedCandidate)
        assert parsed.data is not None
        candidate = parsed.data
        is_final = candidate.recommendation in {
            DecisionRecommendation.APPROVE_REFUND,
            DecisionRecommendation.DENY_REFUND,
        }
        return EvaluationOutcome(
            case_id=case.case_id,
            baseline_id=self.baseline_id,
            applicability=Applicability.APPLICABLE,
            review_status=CaseReviewStatus.COMPLETED,
            termination_reason=CaseReviewTerminationReason.COMPLETED,
            recommendation=candidate.recommendation,
            policy_version=candidate.policy_version,
            packet_created=False,
            ungrounded_finalization_count=int(is_final),
            unverified_success_count=int(candidate.claims_action_succeeded),
        )


class HybridBaseline:
    baseline_id = BaselineId.HYBRID

    def run(self, case: GoldenCase) -> EvaluationOutcome:
        if self.baseline_id not in case.applicable_baselines:
            return _not_applicable(case, self.baseline_id)
        fixture = build_fixture(case)
        review = run_case_review(
            case.input.case,
            fixture.model,
            fixture.source,
            fixture.timeline,
            fixture.corpus,
            collected_at=fixture.collected_at,
            max_steps=fixture.max_steps,
            request_id_prefix=f"eval:{case.case_id}",
        )
        tool_calls = tuple(
            message.tool_result.trace.tool_name
            for message in review.investigation.messages
            if message.role is ModelRole.TOOL and message.tool_result is not None
        )
        illegal_attempts = int(
            review.termination_reason is CaseReviewTerminationReason.TOOL_BATCH_ERROR
        )
        workflow = None
        verifier_status = None
        side_effect_attempts = 0
        illegal_side_effects = 0
        state_changes = 0

        if review.decision_packet is not None and case.input.operation_script:
            (
                workflow,
                verifier_status,
                side_effect_attempts,
                illegal_side_effects,
                state_changes,
            ) = _run_workflow(case, review, fixture.collected_at)

        packet = review.decision_packet
        return EvaluationOutcome(
            case_id=case.case_id,
            baseline_id=self.baseline_id,
            applicability=Applicability.APPLICABLE,
            review_status=review.status,
            termination_reason=review.termination_reason,
            recommendation=packet.recommendation if packet is not None else None,
            evidence_status=(
                review.evidence_bundle.status
                if review.evidence_bundle is not None
                else None
            ),
            policy_version=(
                review.policy_result.selected_version.version
                if review.policy_result is not None
                else None
            ),
            packet_created=packet is not None,
            tool_calls=tool_calls,
            illegal_tool_attempt_count=illegal_attempts,
            illegal_tool_execution_count=0,
            workflow_status=workflow.status if workflow is not None else None,
            verifier_status=verifier_status,
            side_effect_attempt_count=side_effect_attempts,
            illegal_side_effect_count=illegal_side_effects,
            state_change_count=state_changes,
        )


def baseline_runners() -> Mapping[BaselineId, BaselineRunner]:
    return MappingProxyType(
        {
            BaselineId.RULES_ONLY: RulesOnlyBaseline(),
            BaselineId.MODEL_ONLY_SCRIPTED: ModelOnlyScriptedBaseline(),
            BaselineId.HYBRID: HybridBaseline(),
        }
    )


def _not_applicable(case: GoldenCase, baseline_id: BaselineId) -> EvaluationOutcome:
    return EvaluationOutcome(
        case_id=case.case_id,
        baseline_id=baseline_id,
        applicability=Applicability.NOT_APPLICABLE,
        packet_created=False,
    )


def _rules_draft(evidence, policy):
    if evidence.status is EvidenceStatus.INCOMPLETE:
        return (
            DecisionDraft(
                case_id=evidence.case_id,
                recommendation=DecisionRecommendation.REQUEST_EVIDENCE,
                rationale="Required refund evidence is missing.",
                risk_level=RiskLevel.LOW,
            ),
            CaseReviewStatus.SAFE_TERMINATED,
            CaseReviewTerminationReason.MISSING_EVIDENCE,
        )
    if evidence.status is EvidenceStatus.CONFLICTED:
        return (
            DecisionDraft(
                case_id=evidence.case_id,
                recommendation=DecisionRecommendation.MANUAL_REVIEW,
                rationale="Trusted sources conflict.",
                risk_level=RiskLevel.MEDIUM,
            ),
            CaseReviewStatus.SAFE_TERMINATED,
            CaseReviewTerminationReason.EVIDENCE_CONFLICT,
        )
    if not policy.citations:
        return (
            DecisionDraft(
                case_id=evidence.case_id,
                recommendation=DecisionRecommendation.MANUAL_REVIEW,
                rationale="No matching clause exists in the effective policy.",
                risk_level=RiskLevel.MEDIUM,
            ),
            CaseReviewStatus.SAFE_TERMINATED,
            CaseReviewTerminationReason.POLICY_NO_MATCH,
        )
    refund_evidence = next(
        item for item in evidence.evidence if item.kind is EvidenceKind.REFUND_RECORD
    )
    received_fact = next(
        fact for fact in refund_evidence.facts if fact.key is FactKey.REFUND_RECEIVED
    )
    return (
        DecisionDraft(
            case_id=evidence.case_id,
            recommendation=DecisionRecommendation.APPROVE_REFUND,
            rationale="The trusted refund remains incomplete under policy.",
            risk_level=RiskLevel.HIGH,
            evidence_references=(
                FactReference(
                    evidence_id=refund_evidence.evidence_id,
                    fact_id=received_fact.fact_id,
                ),
            ),
            policy_clause_ids=(policy.citations[0].clause_id,),
        ),
        CaseReviewStatus.COMPLETED,
        CaseReviewTerminationReason.COMPLETED,
    )


class _MismatchReader:
    def __init__(self, store: SqliteResolutionStore) -> None:
        self._store = store

    def get_refund(self, payment_id: str, refund_id: str) -> RefundSnapshot:
        actual = self._store.get_refund(payment_id, refund_id)
        return actual.model_copy(
            update={"status": RefundStatus.PROCESSING, "completed_at": None}
        )


def _run_workflow(case: GoldenCase, review: CaseReviewResult, created_at):
    with TemporaryDirectory(prefix="caselens-eval-") as directory:
        store = SqliteResolutionStore(f"{directory}/evaluation.db")
        try:
            store.seed_refunds(case.input.payments)
            reader = (
                _MismatchReader(store)
                if case.input.verifier_behavior is VerifierBehavior.MISMATCH
                else store
            )
            workflow_service = ResolutionWorkflow(store, refund_reader=reader)
            workflow_id = f"workflow:{case.case_id}"
            run = workflow_service.start_resolution(
                case.input.case,
                review,
                review_id=f"review:{case.case_id}",
                workflow_id=workflow_id,
                created_at=created_at,
            )
            side_effect_attempts = 0
            illegal_side_effects = 0
            state_changes = 0
            for index, operation in enumerate(case.input.operation_script, start=1):
                operation_time = created_at + timedelta(minutes=index)
                if operation is WorkflowOperation.APPROVE:
                    run = workflow_service.decide_approval(
                        workflow_id,
                        ApprovalDecision.APPROVED,
                        decided_by="evaluation-reviewer",
                        decided_at=operation_time,
                    )
                elif operation is WorkflowOperation.EXECUTE:
                    side_effect_attempts += 1
                    before = _refund_snapshot(store, case)
                    try:
                        run = workflow_service.execute_action(
                            workflow_id,
                            executed_at=operation_time,
                        )
                    except IllegalTransitionError:
                        run = store.get_run(workflow_id)
                    after = _refund_snapshot(store, case)
                    state_changes += int(before != after)
                else:
                    run = workflow_service.verify_action(
                        workflow_id,
                        verified_at=operation_time,
                    )
            return (
                run,
                run.verification.status if run.verification is not None else None,
                side_effect_attempts,
                illegal_side_effects,
                state_changes,
            )
        finally:
            store.close()


def _refund_snapshot(store: SqliteResolutionStore, case: GoldenCase):
    refund_id = case.input.case.refund_id
    assert refund_id is not None
    return store.get_refund(case.input.case.payment_id, refund_id)
