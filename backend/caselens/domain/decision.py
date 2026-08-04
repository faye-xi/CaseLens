from enum import StrEnum
from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    StrictBool,
    StringConstraints,
    model_validator,
)

from caselens.domain.investigation import (
    EvidenceBundle,
    EvidenceConflict,
    EvidenceStatus,
    FactReference,
    MissingEvidence,
)
from caselens.domain.policy import PolicyVersion
from caselens.domain.policy_retrieval import PolicyCitation, PolicyRetrievalResult

NonBlankText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
]


class DecisionRecommendation(StrEnum):
    REQUEST_EVIDENCE = "request_evidence"
    MANUAL_REVIEW = "manual_review"
    APPROVE_REFUND = "approve_refund"
    DENY_REFUND = "deny_refund"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class DecisionPacketErrorCode(StrEnum):
    CASE_MISMATCH = "case_mismatch"
    UNKNOWN_FACT_REFERENCE = "unknown_fact_reference"
    DUPLICATE_FACT_REFERENCE = "duplicate_fact_reference"
    UNKNOWN_POLICY_CITATION = "unknown_policy_citation"
    DUPLICATE_POLICY_CITATION = "duplicate_policy_citation"
    INCOMPLETE_EVIDENCE = "incomplete_evidence"
    CONFLICTED_EVIDENCE = "conflicted_evidence"
    POLICY_NO_MATCH = "policy_no_match"
    REQUEST_EVIDENCE_WITHOUT_MISSING = "request_evidence_without_missing"
    APPROVE_REFUND_MUST_BE_HIGH_RISK = "approve_refund_must_be_high_risk"
    FINAL_WITHOUT_FACT_REFERENCE = "final_without_fact_reference"
    FINAL_WITHOUT_POLICY_CITATION = "final_without_policy_citation"


class DecisionPacketValidationError(ValueError):
    def __init__(self, code: DecisionPacketErrorCode, message: str) -> None:
        self.code = code
        super().__init__(message)


class DecisionDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: NonBlankText
    recommendation: DecisionRecommendation
    rationale: NonBlankText
    risk_level: RiskLevel
    evidence_references: tuple[FactReference, ...] = ()
    policy_clause_ids: tuple[NonBlankText, ...] = ()

    @model_validator(mode="after")
    def validate_unique_references(self) -> "DecisionDraft":
        fact_references = [
            (reference.evidence_id, reference.fact_id)
            for reference in self.evidence_references
        ]
        if len(fact_references) != len(set(fact_references)):
            raise ValueError("Duplicate fact reference.")

        if len(self.policy_clause_ids) != len(set(self.policy_clause_ids)):
            raise ValueError("Duplicate policy clause ID.")

        return self


class DecisionPacket(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: NonBlankText
    recommendation: DecisionRecommendation
    rationale: NonBlankText
    risk_level: RiskLevel
    requires_approval: StrictBool
    evidence_status: EvidenceStatus
    evidence_references: tuple[FactReference, ...] = ()
    missing_evidence: tuple[MissingEvidence, ...] = ()
    evidence_conflicts: tuple[EvidenceConflict, ...] = ()
    selected_policy_version: PolicyVersion
    policy_citations: tuple[PolicyCitation, ...] = ()

    @model_validator(mode="after")
    def validate_invariants(self) -> "DecisionPacket":
        fact_references = [
            (reference.evidence_id, reference.fact_id)
            for reference in self.evidence_references
        ]
        if len(fact_references) != len(set(fact_references)):
            raise ValueError("Duplicate fact reference.")

        citation_ids = [citation.clause_id for citation in self.policy_citations]
        if len(citation_ids) != len(set(citation_ids)):
            raise ValueError("Duplicate policy citation.")

        if self.evidence_status is EvidenceStatus.COMPLETE:
            if self.missing_evidence:
                raise ValueError("Complete evidence cannot contain missing evidence.")
            if self.evidence_conflicts:
                raise ValueError("Complete evidence cannot contain conflicts.")
        elif self.evidence_status is EvidenceStatus.INCOMPLETE:
            if not self.missing_evidence:
                raise ValueError("Incomplete evidence must contain missing evidence.")
            if self.evidence_conflicts:
                raise ValueError("Incomplete evidence cannot contain conflicts.")
        elif not self.evidence_conflicts:
            raise ValueError("Conflicted evidence must contain conflicts.")

        if self.recommendation in {
            DecisionRecommendation.APPROVE_REFUND,
            DecisionRecommendation.DENY_REFUND,
        }:
            if self.evidence_status is not EvidenceStatus.COMPLETE:
                raise ValueError("Final recommendation requires complete evidence.")
            if not self.evidence_references:
                raise ValueError("Final recommendation requires evidence references.")
            if not self.policy_citations:
                raise ValueError("Final recommendation requires a policy citation.")

        if (
            self.evidence_status is EvidenceStatus.CONFLICTED
            and self.recommendation is not DecisionRecommendation.MANUAL_REVIEW
        ):
            raise ValueError("Conflicted evidence requires manual review.")

        if self.recommendation is DecisionRecommendation.REQUEST_EVIDENCE and not (
            self.missing_evidence
        ):
            raise ValueError("request_evidence requires missing evidence.")

        if self.recommendation is DecisionRecommendation.APPROVE_REFUND and (
            self.risk_level is not RiskLevel.HIGH
        ):
            raise ValueError("approve_refund must be high risk.")

        expected_approval = (
            self.risk_level is RiskLevel.HIGH
            or self.recommendation is DecisionRecommendation.APPROVE_REFUND
        )
        if self.requires_approval is not expected_approval:
            raise ValueError("High-risk conclusions require approval.")

        selected_version = self.selected_policy_version
        for citation in self.policy_citations:
            if (
                citation.policy_id != selected_version.policy_id
                or citation.version != selected_version.version
                or citation.effective_from != selected_version.effective_from
                or citation.effective_to != selected_version.effective_to
            ):
                raise ValueError("Policy citation must match selected policy version.")

        return self


def build_decision_packet(
    evidence_bundle: EvidenceBundle,
    policy_result: PolicyRetrievalResult,
    draft: DecisionDraft,
) -> DecisionPacket:
    if draft.case_id != evidence_bundle.case_id:
        raise DecisionPacketValidationError(
            DecisionPacketErrorCode.CASE_MISMATCH,
            "Decision draft case ID does not match the evidence bundle.",
        )

    final_recommendation = draft.recommendation in {
        DecisionRecommendation.APPROVE_REFUND,
        DecisionRecommendation.DENY_REFUND,
    }
    if final_recommendation:
        if evidence_bundle.status is EvidenceStatus.INCOMPLETE:
            raise DecisionPacketValidationError(
                DecisionPacketErrorCode.INCOMPLETE_EVIDENCE,
                "Final recommendation requires complete evidence.",
            )
        if evidence_bundle.status is EvidenceStatus.CONFLICTED:
            raise DecisionPacketValidationError(
                DecisionPacketErrorCode.CONFLICTED_EVIDENCE,
                "Final recommendation cannot use conflicted evidence.",
            )
    elif (
        evidence_bundle.status is EvidenceStatus.CONFLICTED
        and draft.recommendation is not DecisionRecommendation.MANUAL_REVIEW
    ):
        raise DecisionPacketValidationError(
            DecisionPacketErrorCode.CONFLICTED_EVIDENCE,
            "Conflicted evidence requires manual review.",
        )

    fact_lookup = {
        (evidence.evidence_id, fact.fact_id): fact
        for evidence in evidence_bundle.evidence
        for fact in evidence.facts
    }
    for reference in draft.evidence_references:
        if (reference.evidence_id, reference.fact_id) not in fact_lookup:
            raise DecisionPacketValidationError(
                DecisionPacketErrorCode.UNKNOWN_FACT_REFERENCE,
                "Decision draft references an unknown fact.",
            )

    evidence_references = tuple(
        sorted(
            draft.evidence_references,
            key=lambda reference: (reference.evidence_id, reference.fact_id),
        )
    )

    citations_by_clause_id = {
        citation.clause_id: citation for citation in policy_result.citations
    }
    for clause_id in draft.policy_clause_ids:
        if clause_id not in citations_by_clause_id:
            raise DecisionPacketValidationError(
                DecisionPacketErrorCode.UNKNOWN_POLICY_CITATION,
                "Decision draft references an unknown policy citation.",
            )

    requested_clause_ids = set(draft.policy_clause_ids)
    policy_citations = tuple(
        citation
        for citation in policy_result.citations
        if citation.clause_id in requested_clause_ids
    )

    if final_recommendation:
        if not evidence_references:
            raise DecisionPacketValidationError(
                DecisionPacketErrorCode.FINAL_WITHOUT_FACT_REFERENCE,
                "Final recommendation requires evidence references.",
            )
        if not policy_citations:
            raise DecisionPacketValidationError(
                DecisionPacketErrorCode.POLICY_NO_MATCH,
                "Final recommendation requires a matching policy citation.",
            )

    if (
        draft.recommendation is DecisionRecommendation.REQUEST_EVIDENCE
        and not evidence_bundle.missing_evidence
    ):
        raise DecisionPacketValidationError(
            DecisionPacketErrorCode.REQUEST_EVIDENCE_WITHOUT_MISSING,
            "request_evidence requires missing evidence.",
        )

    if (
        draft.recommendation is DecisionRecommendation.APPROVE_REFUND
        and draft.risk_level is not RiskLevel.HIGH
    ):
        raise DecisionPacketValidationError(
            DecisionPacketErrorCode.APPROVE_REFUND_MUST_BE_HIGH_RISK,
            "approve_refund must be high risk.",
        )

    return DecisionPacket(
        case_id=evidence_bundle.case_id,
        recommendation=draft.recommendation,
        rationale=draft.rationale,
        risk_level=draft.risk_level,
        requires_approval=(
            draft.risk_level is RiskLevel.HIGH
            or draft.recommendation is DecisionRecommendation.APPROVE_REFUND
        ),
        evidence_status=evidence_bundle.status,
        evidence_references=evidence_references,
        missing_evidence=evidence_bundle.missing_evidence,
        evidence_conflicts=evidence_bundle.conflicts,
        selected_policy_version=policy_result.selected_version,
        policy_citations=policy_citations,
    )
