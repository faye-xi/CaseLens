from caselens.agent.case_review import CaseReviewResult, CaseReviewStatus
from caselens.domain.decision import DecisionRecommendation
from caselens.domain.investigation import EvidenceKind, FactKey
from caselens.domain.models import Case
from caselens.resolution.models import RefundActionCommand, packet_fingerprint


class ResolutionPlanningError(ValueError):
    """Trusted review material cannot produce a safe resolution plan."""


def plan_refund_action(
    case: Case,
    review: CaseReviewResult,
    *,
    workflow_id: str,
) -> RefundActionCommand | None:
    packet = review.decision_packet
    bundle = review.evidence_bundle
    if packet is None or bundle is None:
        raise ResolutionPlanningError(
            "Resolution planning requires a decision packet and trusted evidence."
        )
    if (
        review.case_id != case.case_id
        or packet.case_id != case.case_id
        or bundle.case_id != case.case_id
    ):
        raise ResolutionPlanningError(
            "The case, review, packet, and evidence must reference the same case."
        )
    if packet.recommendation is not DecisionRecommendation.APPROVE_REFUND:
        return None
    if review.status is not CaseReviewStatus.COMPLETED:
        raise ResolutionPlanningError("Refund completion requires a completed review.")
    if not packet.requires_approval:
        raise ResolutionPlanningError("Refund approval must require human approval.")

    refund_evidence = tuple(
        evidence
        for evidence in bundle.evidence
        if evidence.kind is EvidenceKind.REFUND_RECORD
    )
    if len(refund_evidence) != 1:
        raise ResolutionPlanningError(
            "Refund completion requires exactly one trusted refund record."
        )
    trusted_refund = refund_evidence[0]
    trusted_amounts = tuple(
        fact.value for fact in trusted_refund.facts if fact.key is FactKey.REFUND_AMOUNT
    )
    if len(trusted_amounts) != 1 or trusted_amounts[0] != case.claim_amount:
        raise ResolutionPlanningError(
            "The trusted refund amount must match the case claim amount."
        )

    fingerprint = packet_fingerprint(packet)
    refund_id = trusted_refund.source_record_id
    return RefundActionCommand(
        action_id=f"{workflow_id}:complete-refund",
        workflow_id=workflow_id,
        case_id=case.case_id,
        payment_id=case.payment_id,
        refund_id=refund_id,
        amount=case.claim_amount,
        currency=case.currency,
        packet_fingerprint=fingerprint,
        idempotency_key=f"complete_refund:{case.payment_id}:{refund_id}",
    )
