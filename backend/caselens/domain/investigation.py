from decimal import Decimal
from enum import StrEnum
from typing import Annotated

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictStr,
    StringConstraints,
    computed_field,
    model_validator,
)


class FactKey(StrEnum):
    REFUND_RECEIVED = "refund_received"
    REFUND_STATUS = "refund_status"
    REFUND_AMOUNT = "refund_amount"


class EvidenceKind(StrEnum):
    CUSTOMER_STATEMENT = "customer_statement"
    REFUND_RECORD = "refund_record"


class EvidenceStatus(StrEnum):
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"
    CONFLICTED = "conflicted"


FactValue = StrictStr | StrictBool | Decimal
NonBlankText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
]
Identifier = NonBlankText


class Fact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    fact_id: Identifier
    key: FactKey
    value: FactValue

    @model_validator(mode="after")
    def validate_value_for_key(self) -> "Fact":
        if self.key is FactKey.REFUND_RECEIVED and type(self.value) is not bool:
            raise ValueError("Fact value for refund_received must be boolean.")
        if self.key is FactKey.REFUND_STATUS and (
            type(self.value) is not str or not self.value.strip()
        ):
            raise ValueError("Fact value for refund_status must be non-blank text.")
        if self.key is FactKey.REFUND_AMOUNT and (
            not isinstance(self.value, Decimal) or self.value <= 0
        ):
            raise ValueError("Fact value for refund_amount must be a positive amount.")
        return self


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_id: Identifier
    kind: EvidenceKind
    source_record_id: Identifier
    collected_at: AwareDatetime
    facts: tuple[Fact, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_fact_ids(self) -> "Evidence":
        fact_ids = [fact.fact_id for fact in self.facts]
        if len(fact_ids) != len(set(fact_ids)):
            raise ValueError("Duplicate fact ID within evidence.")
        return self


class MissingEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: EvidenceKind
    reason: NonBlankText


class FactReference(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_id: Identifier
    fact_id: Identifier


class EvidenceConflict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    key: FactKey
    left: FactReference
    right: FactReference


class EvidenceBundle(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: Identifier
    evidence: tuple[Evidence, ...] = Field(min_length=1)
    missing_evidence: tuple[MissingEvidence, ...] = ()
    conflicts: tuple[EvidenceConflict, ...] = ()

    @model_validator(mode="after")
    def validate_audit_references(self) -> "EvidenceBundle":
        evidence_ids = [item.evidence_id for item in self.evidence]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("Duplicate evidence ID.")

        facts = {
            (item.evidence_id, fact.fact_id): fact
            for item in self.evidence
            for fact in item.facts
        }
        for conflict in self.conflicts:
            if conflict.left == conflict.right:
                raise ValueError("A conflict must reference two distinct facts.")

            left_fact = facts.get((conflict.left.evidence_id, conflict.left.fact_id))
            right_fact = facts.get((conflict.right.evidence_id, conflict.right.fact_id))
            if left_fact is None or right_fact is None:
                raise ValueError("A conflict references an unknown fact.")
            if left_fact.key is not conflict.key or right_fact.key is not conflict.key:
                raise ValueError("Both facts must match the declared conflict key.")
            if left_fact.value == right_fact.value:
                raise ValueError(
                    "A conflict must reference facts with different values."
                )

        return self

    @computed_field
    @property
    def status(self) -> EvidenceStatus:
        if self.conflicts:
            return EvidenceStatus.CONFLICTED
        if self.missing_evidence:
            return EvidenceStatus.INCOMPLETE
        return EvidenceStatus.COMPLETE
