import pytest
from pydantic import ValidationError

from caselens.domain.decision import (
    DecisionDraft,
    DecisionPacket,
    DecisionPacketErrorCode,
    DecisionPacketValidationError,
    DecisionRecommendation,
    RiskLevel,
    build_decision_packet,
)
from caselens.domain.investigation import (
    Evidence,
    EvidenceBundle,
    EvidenceConflict,
    EvidenceKind,
    EvidenceStatus,
    Fact,
    FactReference,
    MissingEvidence,
)
from caselens.domain.policy import PolicyVersion
from caselens.domain.policy_retrieval import PolicyCitation, PolicyRetrievalResult


def make_policy_version() -> PolicyVersion:
    return PolicyVersion(
        policy_id="refund-policy",
        version="v1",
        effective_from="2026-01-01T00:00:00+08:00",
        effective_to=None,
    )


def make_policy_citation() -> PolicyCitation:
    return PolicyCitation(
        clause_id="REFUND-V1",
        policy_id="refund-policy",
        version="v1",
        effective_from="2026-01-01T00:00:00+08:00",
        effective_to=None,
        quote="Refund not received cases allow seven days.",
        score=1,
    )


def make_evidence_bundle() -> EvidenceBundle:
    return EvidenceBundle(
        case_id="CASE-006",
        evidence=(
            Evidence(
                evidence_id="EVIDENCE-REFUND",
                kind=EvidenceKind.REFUND_RECORD,
                source_record_id="REFUND-006",
                collected_at="2026-07-28T21:22:00+08:00",
                facts=(
                    Fact(
                        fact_id="FACT-REFUND-RECEIVED",
                        key="refund_received",
                        value=False,
                    ),
                ),
            ),
        ),
    )


def make_incomplete_bundle() -> EvidenceBundle:
    return EvidenceBundle(
        case_id="CASE-006",
        evidence=(
            Evidence(
                evidence_id="EVIDENCE-CUSTOMER",
                kind=EvidenceKind.CUSTOMER_STATEMENT,
                source_record_id="CASE-006",
                collected_at="2026-07-28T21:21:00+08:00",
                facts=(
                    Fact(
                        fact_id="FACT-CUSTOMER-RECEIVED",
                        key="refund_received",
                        value=False,
                    ),
                ),
            ),
        ),
        missing_evidence=(
            MissingEvidence(
                kind=EvidenceKind.REFUND_RECORD,
                reason="The refund record has not been retrieved.",
            ),
        ),
    )


def make_conflicted_bundle() -> EvidenceBundle:
    return EvidenceBundle(
        case_id="CASE-006",
        evidence=(
            Evidence(
                evidence_id="EVIDENCE-CUSTOMER",
                kind=EvidenceKind.CUSTOMER_STATEMENT,
                source_record_id="CASE-006",
                collected_at="2026-07-28T21:21:00+08:00",
                facts=(
                    Fact(
                        fact_id="FACT-CUSTOMER-RECEIVED",
                        key="refund_received",
                        value=False,
                    ),
                ),
            ),
            Evidence(
                evidence_id="EVIDENCE-REFUND",
                kind=EvidenceKind.REFUND_RECORD,
                source_record_id="REFUND-006",
                collected_at="2026-07-28T21:22:00+08:00",
                facts=(
                    Fact(
                        fact_id="FACT-REFUND-RECEIVED",
                        key="refund_received",
                        value=True,
                    ),
                ),
            ),
        ),
        conflicts=(
            EvidenceConflict(
                key="refund_received",
                left=FactReference(
                    evidence_id="EVIDENCE-CUSTOMER",
                    fact_id="FACT-CUSTOMER-RECEIVED",
                ),
                right=FactReference(
                    evidence_id="EVIDENCE-REFUND",
                    fact_id="FACT-REFUND-RECEIVED",
                ),
            ),
        ),
    )


def make_policy_result(
    *, citations: tuple[PolicyCitation, ...] | None = None
) -> PolicyRetrievalResult:
    return PolicyRetrievalResult(
        query="refund not received",
        selected_version=make_policy_version(),
        citations=(make_policy_citation(),) if citations is None else citations,
    )


def make_draft(**overrides: object) -> DecisionDraft:
    values: dict[str, object] = {
        "case_id": "CASE-006",
        "recommendation": "approve_refund",
        "rationale": "The trusted refund record supports approval.",
        "risk_level": "high",
        "evidence_references": (
            FactReference(
                evidence_id="EVIDENCE-REFUND",
                fact_id="FACT-REFUND-RECEIVED",
            ),
        ),
        "policy_clause_ids": ("REFUND-V1",),
    }
    values.update(overrides)
    return DecisionDraft.model_validate(values)


def make_packet(**overrides: object) -> DecisionPacket:
    values: dict[str, object] = {
        "case_id": "CASE-006",
        "recommendation": "approve_refund",
        "rationale": "The trusted refund record supports approval.",
        "risk_level": "high",
        "requires_approval": True,
        "evidence_status": "complete",
        "evidence_references": (
            FactReference(
                evidence_id="EVIDENCE-REFUND",
                fact_id="FACT-REFUND-RECEIVED",
            ),
        ),
        "missing_evidence": (),
        "evidence_conflicts": (),
        "selected_policy_version": make_policy_version(),
        "policy_citations": (make_policy_citation(),),
    }
    values.update(overrides)
    return DecisionPacket.model_validate(values)


def test_decision_draft_accepts_structured_candidate() -> None:
    draft = DecisionDraft(
        case_id="CASE-006",
        recommendation="approve_refund",
        rationale="The refund record shows the refund was not received.",
        risk_level="high",
        evidence_references=(
            FactReference(
                evidence_id="EVIDENCE-REFUND",
                fact_id="FACT-REFUND-RECEIVED",
            ),
        ),
        policy_clause_ids=("REFUND-V1",),
    )

    assert draft.recommendation is DecisionRecommendation.APPROVE_REFUND
    assert draft.risk_level is RiskLevel.HIGH


def test_decision_draft_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        DecisionDraft.model_validate(
            {
                "case_id": "CASE-006",
                "recommendation": "manual_review",
                "rationale": "Review the case.",
                "risk_level": "medium",
                "unexpected": True,
            }
        )


def test_decision_draft_rejects_duplicate_fact_references() -> None:
    reference = FactReference(
        evidence_id="EVIDENCE-REFUND",
        fact_id="FACT-REFUND-RECEIVED",
    )

    with pytest.raises(ValidationError, match="Duplicate fact reference"):
        DecisionDraft(
            case_id="CASE-006",
            recommendation="manual_review",
            rationale="Review the case.",
            risk_level="medium",
            evidence_references=(reference, reference),
        )


def test_decision_draft_rejects_duplicate_policy_clause_ids() -> None:
    with pytest.raises(ValidationError, match="Duplicate policy clause"):
        DecisionDraft(
            case_id="CASE-006",
            recommendation="manual_review",
            rationale="Review the case.",
            risk_level="medium",
            policy_clause_ids=("REFUND-V1", "REFUND-V1"),
        )


def test_packet_requires_approval_for_high_risk() -> None:
    packet = make_packet(risk_level="high", requires_approval=True)

    assert packet.requires_approval is True


def test_packet_rejects_high_risk_without_approval() -> None:
    with pytest.raises(ValidationError, match="approval"):
        make_packet(risk_level="high", requires_approval=False)


def test_packet_rejects_approve_refund_with_non_high_risk() -> None:
    with pytest.raises(ValidationError, match="high risk"):
        make_packet(risk_level="medium", requires_approval=True)


def test_packet_rejects_final_recommendation_with_incomplete_material() -> None:
    with pytest.raises(ValidationError, match="complete"):
        make_packet(
            recommendation="approve_refund",
            evidence_status="incomplete",
            missing_evidence=(
                MissingEvidence(
                    kind="refund_record",
                    reason="The refund record is missing.",
                ),
            ),
        )


def test_packet_rejects_final_recommendation_without_policy_citation() -> None:
    with pytest.raises(ValidationError, match="policy citation"):
        make_packet(policy_citations=())


def test_packet_rejects_policy_citation_from_another_version() -> None:
    citation = make_policy_citation().model_copy(update={"version": "v2"})

    with pytest.raises(ValidationError, match="selected policy version"):
        make_packet(policy_citations=(citation,))


def test_packet_rejects_inconsistent_missing_and_conflict_status() -> None:
    conflict = EvidenceConflict(
        key="refund_received",
        left=FactReference(
            evidence_id="EVIDENCE-CUSTOMER",
            fact_id="FACT-CUSTOMER-RECEIVED",
        ),
        right=FactReference(
            evidence_id="EVIDENCE-REFUND",
            fact_id="FACT-REFUND-RECEIVED",
        ),
    )

    with pytest.raises(ValidationError, match="conflicts"):
        make_packet(
            evidence_status=EvidenceStatus.COMPLETE, evidence_conflicts=(conflict,)
        )


def test_builds_packet_from_complete_evidence_and_matching_policy() -> None:
    packet = build_decision_packet(
        make_evidence_bundle(),
        make_policy_result(),
        make_draft(),
    )

    assert packet.case_id == "CASE-006"
    assert packet.requires_approval is True
    assert packet.evidence_status is EvidenceStatus.COMPLETE
    assert [
        (reference.evidence_id, reference.fact_id)
        for reference in packet.evidence_references
    ] == [("EVIDENCE-REFUND", "FACT-REFUND-RECEIVED")]
    assert [citation.clause_id for citation in packet.policy_citations] == ["REFUND-V1"]
    assert packet.policy_citations[0].quote == (
        "Refund not received cases allow seven days."
    )


def test_builder_rejects_unknown_fact_reference() -> None:
    with pytest.raises(DecisionPacketValidationError) as error:
        build_decision_packet(
            make_evidence_bundle(),
            make_policy_result(),
            make_draft(
                evidence_references=(
                    FactReference(
                        evidence_id="EVIDENCE-MISSING",
                        fact_id="FACT-MISSING",
                    ),
                )
            ),
        )

    assert error.value.code is DecisionPacketErrorCode.UNKNOWN_FACT_REFERENCE


def test_builder_rejects_unknown_policy_citation() -> None:
    with pytest.raises(DecisionPacketValidationError) as error:
        build_decision_packet(
            make_evidence_bundle(),
            make_policy_result(),
            make_draft(policy_clause_ids=("CLAUSE-MISSING",)),
        )

    assert error.value.code is DecisionPacketErrorCode.UNKNOWN_POLICY_CITATION


def test_builder_rejects_draft_for_another_case() -> None:
    with pytest.raises(DecisionPacketValidationError) as error:
        build_decision_packet(
            make_evidence_bundle(),
            make_policy_result(),
            make_draft(case_id="CASE-OTHER"),
        )

    assert error.value.code is DecisionPacketErrorCode.CASE_MISMATCH


def test_missing_evidence_allows_request_evidence_but_not_approval() -> None:
    packet = build_decision_packet(
        make_incomplete_bundle(),
        make_policy_result(),
        make_draft(
            recommendation="request_evidence",
            evidence_references=(),
            policy_clause_ids=(),
        ),
    )

    assert packet.recommendation is DecisionRecommendation.REQUEST_EVIDENCE
    assert packet.missing_evidence

    with pytest.raises(DecisionPacketValidationError) as error:
        build_decision_packet(
            make_incomplete_bundle(),
            make_policy_result(),
            make_draft(recommendation="approve_refund"),
        )

    assert error.value.code is DecisionPacketErrorCode.INCOMPLETE_EVIDENCE


def test_conflicted_evidence_requires_manual_review() -> None:
    packet = build_decision_packet(
        make_conflicted_bundle(),
        make_policy_result(),
        make_draft(
            recommendation="manual_review",
            evidence_references=(),
            policy_clause_ids=(),
        ),
    )

    assert packet.recommendation is DecisionRecommendation.MANUAL_REVIEW
    assert packet.evidence_conflicts

    with pytest.raises(DecisionPacketValidationError) as error:
        build_decision_packet(
            make_conflicted_bundle(),
            make_policy_result(),
            make_draft(recommendation="deny_refund"),
        )

    assert error.value.code is DecisionPacketErrorCode.CONFLICTED_EVIDENCE


def test_conflicted_evidence_cannot_be_downgraded_to_request_evidence() -> None:
    conflicted_with_missing = make_conflicted_bundle().model_copy(
        update={
            "missing_evidence": (
                MissingEvidence(
                    kind=EvidenceKind.REFUND_RECORD,
                    reason="A second refund record is still missing.",
                ),
            )
        }
    )

    with pytest.raises(DecisionPacketValidationError) as error:
        build_decision_packet(
            conflicted_with_missing,
            make_policy_result(),
            make_draft(
                recommendation="request_evidence",
                evidence_references=(),
                policy_clause_ids=(),
            ),
        )

    assert error.value.code is DecisionPacketErrorCode.CONFLICTED_EVIDENCE


def test_policy_no_match_rejects_final_recommendation() -> None:
    with pytest.raises(DecisionPacketValidationError) as error:
        build_decision_packet(
            make_evidence_bundle(),
            make_policy_result(citations=()),
            make_draft(
                recommendation="deny_refund",
                policy_clause_ids=(),
            ),
        )

    assert error.value.code is DecisionPacketErrorCode.POLICY_NO_MATCH


def test_request_evidence_without_missing_material_is_rejected() -> None:
    with pytest.raises(DecisionPacketValidationError) as error:
        build_decision_packet(
            make_evidence_bundle(),
            make_policy_result(),
            make_draft(
                recommendation="request_evidence",
                evidence_references=(),
                policy_clause_ids=(),
            ),
        )

    assert error.value.code is DecisionPacketErrorCode.REQUEST_EVIDENCE_WITHOUT_MISSING


def test_packet_is_immutable_and_serializes_audit_fields() -> None:
    packet = build_decision_packet(
        make_evidence_bundle(),
        make_policy_result(),
        make_draft(),
    )

    with pytest.raises(ValidationError):
        packet.rationale = "changed"

    dumped = packet.model_dump(mode="json")
    assert dumped["evidence_references"]
    assert dumped["policy_citations"][0]["quote"] == (
        "Refund not received cases allow seven days."
    )
