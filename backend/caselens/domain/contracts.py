from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from caselens.domain.evidence import find_missing_evidence
from caselens.domain.models import Case


class InvestigationReadiness(StrEnum):
    READY = "ready_for_investigation"
    NEEDS_EVIDENCE = "needs_evidence"


class RefundNotReceivedAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str
    readiness: InvestigationReadiness
    missing_evidence: tuple[str, ...]


def assess_refund_not_received(case: Case) -> RefundNotReceivedAssessment:
    missing_evidence = tuple(find_missing_evidence(case))
    readiness = (
        InvestigationReadiness.NEEDS_EVIDENCE
        if missing_evidence
        else InvestigationReadiness.READY
    )

    return RefundNotReceivedAssessment(
        case_id=case.case_id,
        readiness=readiness,
        missing_evidence=missing_evidence,
    )
