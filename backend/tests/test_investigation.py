import pytest
from pydantic import ValidationError

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


def make_customer_evidence() -> Evidence:
    return Evidence.model_validate(
        {
            "evidence_id": "EVIDENCE-CUSTOMER",
            "kind": "customer_statement",
            "source_record_id": "CASE-006",
            "collected_at": "2026-07-28T21:21:00+08:00",
            "facts": [
                {
                    "fact_id": "FACT-CUSTOMER-RECEIVED",
                    "key": "refund_received",
                    "value": False,
                }
            ],
        }
    )


def make_refund_evidence(*, received: bool = True) -> Evidence:
    return Evidence.model_validate(
        {
            "evidence_id": "EVIDENCE-REFUND",
            "kind": "refund_record",
            "source_record_id": "REFUND-006",
            "collected_at": "2026-07-28T21:22:00+08:00",
            "facts": [
                {
                    "fact_id": "FACT-REFUND-RECEIVED",
                    "key": "refund_received",
                    "value": received,
                }
            ],
        }
    )


def test_complete_material_has_complete_status() -> None:
    bundle = EvidenceBundle(
        case_id="CASE-006",
        evidence=(make_refund_evidence(),),
    )

    assert bundle.status is EvidenceStatus.COMPLETE


def test_rejects_empty_evidence_bundle() -> None:
    with pytest.raises(ValidationError):
        EvidenceBundle(case_id="CASE-006")


def test_missing_refund_record_has_incomplete_status() -> None:
    bundle = EvidenceBundle(
        case_id="CASE-006",
        evidence=(make_customer_evidence(),),
        missing_evidence=(
            MissingEvidence(
                kind=EvidenceKind.REFUND_RECORD,
                reason="The refund record has not been retrieved.",
            ),
        ),
    )

    assert bundle.status is EvidenceStatus.INCOMPLETE


def test_conflicting_material_has_traceable_conflict() -> None:
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
    bundle = EvidenceBundle(
        case_id="CASE-006",
        evidence=(make_customer_evidence(), make_refund_evidence()),
        conflicts=(conflict,),
    )

    assert bundle.status is EvidenceStatus.CONFLICTED
    assert bundle.conflicts == (conflict,)
    assert bundle.model_dump(mode="json")["status"] == "conflicted"


def test_conflict_takes_priority_over_missing_evidence() -> None:
    bundle = EvidenceBundle(
        case_id="CASE-006",
        evidence=(make_customer_evidence(), make_refund_evidence()),
        missing_evidence=(
            MissingEvidence(
                kind=EvidenceKind.REFUND_RECORD,
                reason="A second refund record is still missing.",
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

    assert bundle.status is EvidenceStatus.CONFLICTED


def test_rejects_unknown_fact_fields() -> None:
    with pytest.raises(ValidationError):
        Fact.model_validate(
            {
                "fact_id": "FACT-001",
                "key": "refund_received",
                "value": True,
                "confidence": 1,
            }
        )


@pytest.mark.parametrize(
    "fact",
    [
        {
            "fact_id": "FACT-WRONG-RECEIVED",
            "key": "refund_received",
            "value": "false",
        },
        {
            "fact_id": "FACT-WRONG-STATUS",
            "key": "refund_status",
            "value": True,
        },
        {
            "fact_id": "FACT-WRONG-AMOUNT",
            "key": "refund_amount",
            "value": 0,
        },
        {
            "fact_id": "FACT-NUMERIC-RECEIVED-INT",
            "key": "refund_received",
            "value": 1,
        },
        {
            "fact_id": "FACT-NUMERIC-RECEIVED-FLOAT",
            "key": "refund_received",
            "value": 0.0,
        },
    ],
)
def test_rejects_fact_value_with_wrong_business_type(
    fact: dict[str, object],
) -> None:
    with pytest.raises(ValidationError, match="Fact value"):
        Fact.model_validate(fact)


def test_rejects_whitespace_only_identifiers_and_reasons() -> None:
    with pytest.raises(ValidationError):
        Fact(fact_id="   ", key="refund_received", value=True)

    with pytest.raises(ValidationError):
        MissingEvidence(kind="refund_record", reason="   ")


def test_rejects_unknown_evidence_bundle_fields() -> None:
    with pytest.raises(ValidationError):
        EvidenceBundle.model_validate(
            {
                "case_id": "CASE-006",
                "evidence": [make_refund_evidence()],
                "decision": "approve",
            }
        )


def test_evidence_bundle_is_immutable() -> None:
    bundle = EvidenceBundle(
        case_id="CASE-006",
        evidence=(make_refund_evidence(),),
    )

    with pytest.raises(ValidationError):
        bundle.case_id = "CASE-CHANGED"


def test_rejects_evidence_without_facts() -> None:
    with pytest.raises(ValidationError):
        Evidence.model_validate(
            {
                "evidence_id": "EVIDENCE-EMPTY",
                "kind": "refund_record",
                "source_record_id": "REFUND-EMPTY",
                "collected_at": "2026-07-28T21:22:00+08:00",
                "facts": [],
            }
        )


def test_rejects_evidence_time_without_timezone() -> None:
    with pytest.raises(ValidationError):
        Evidence.model_validate(
            {
                "evidence_id": "EVIDENCE-TIME",
                "kind": "refund_record",
                "source_record_id": "REFUND-TIME",
                "collected_at": "2026-07-28T21:22:00",
                "facts": [
                    {
                        "fact_id": "FACT-TIME",
                        "key": "refund_received",
                        "value": True,
                    }
                ],
            }
        )


def test_rejects_duplicate_fact_ids_inside_evidence() -> None:
    fact = Fact(
        fact_id="FACT-DUPLICATE",
        key="refund_received",
        value=True,
    )

    with pytest.raises(ValidationError, match="Duplicate fact ID"):
        Evidence(
            evidence_id="EVIDENCE-DUPLICATE-FACT",
            kind="refund_record",
            source_record_id="REFUND-DUPLICATE-FACT",
            collected_at="2026-07-28T21:22:00+08:00",
            facts=(fact, fact),
        )


def test_rejects_duplicate_evidence_ids() -> None:
    evidence = make_refund_evidence()

    with pytest.raises(ValidationError, match="Duplicate evidence ID"):
        EvidenceBundle(
            case_id="CASE-006",
            evidence=(evidence, evidence),
        )


@pytest.mark.parametrize(
    ("left", "right", "message"),
    [
        (
            FactReference(
                evidence_id="EVIDENCE-MISSING",
                fact_id="FACT-CUSTOMER-RECEIVED",
            ),
            FactReference(
                evidence_id="EVIDENCE-REFUND",
                fact_id="FACT-REFUND-RECEIVED",
            ),
            "unknown fact",
        ),
        (
            FactReference(
                evidence_id="EVIDENCE-CUSTOMER",
                fact_id="FACT-MISSING",
            ),
            FactReference(
                evidence_id="EVIDENCE-REFUND",
                fact_id="FACT-REFUND-RECEIVED",
            ),
            "unknown fact",
        ),
        (
            FactReference(
                evidence_id="EVIDENCE-CUSTOMER",
                fact_id="FACT-CUSTOMER-RECEIVED",
            ),
            FactReference(
                evidence_id="EVIDENCE-CUSTOMER",
                fact_id="FACT-CUSTOMER-RECEIVED",
            ),
            "distinct facts",
        ),
    ],
)
def test_rejects_untraceable_conflict_references(
    left: FactReference,
    right: FactReference,
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        EvidenceBundle(
            case_id="CASE-006",
            evidence=(make_customer_evidence(), make_refund_evidence()),
            conflicts=(
                EvidenceConflict(
                    key="refund_received",
                    left=left,
                    right=right,
                ),
            ),
        )


def test_rejects_conflict_between_different_fact_keys() -> None:
    refund_evidence = Evidence.model_validate(
        {
            "evidence_id": "EVIDENCE-REFUND",
            "kind": "refund_record",
            "source_record_id": "REFUND-006",
            "collected_at": "2026-07-28T21:22:00+08:00",
            "facts": [
                {
                    "fact_id": "FACT-REFUND-STATUS",
                    "key": "refund_status",
                    "value": "succeeded",
                }
            ],
        }
    )

    with pytest.raises(ValidationError, match="declared conflict key"):
        EvidenceBundle(
            case_id="CASE-006",
            evidence=(make_customer_evidence(), refund_evidence),
            conflicts=(
                EvidenceConflict(
                    key="refund_received",
                    left=FactReference(
                        evidence_id="EVIDENCE-CUSTOMER",
                        fact_id="FACT-CUSTOMER-RECEIVED",
                    ),
                    right=FactReference(
                        evidence_id="EVIDENCE-REFUND",
                        fact_id="FACT-REFUND-STATUS",
                    ),
                ),
            ),
        )


def test_rejects_conflict_between_equal_values() -> None:
    with pytest.raises(ValidationError, match="different values"):
        EvidenceBundle(
            case_id="CASE-006",
            evidence=(
                make_customer_evidence(),
                make_refund_evidence(received=False),
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
