from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from caselens.agent.case_review import CaseReviewResult, run_case_review
from caselens.application import CaseLensApplication, Clock, utc_now
from caselens.domain.models import Case
from caselens.domain.policy import PolicyTimeline, PolicyVersion
from caselens.domain.policy_retrieval import PolicyClause, PolicyClauseCorpus
from caselens.model import MockModel, ModelFinishReason, ModelMessage, ModelResponse
from caselens.persistence.repository import SqliteRepository
from caselens.resolution.service import ResolutionWorkflow
from caselens.resolution.store import SqliteResolutionStore
from caselens.tools.models import (
    PaymentRecord,
    PaymentStatus,
    RefundRecord,
    RefundStatus,
)
from caselens.tools.protocol import ToolCall
from caselens.tools.source import InMemoryBusinessDataSource

DEMO_OCCURRED_AT = datetime(2026, 6, 15, 13, 21, tzinfo=UTC)


class DemoCaseReviewer:
    def __init__(
        self,
        source: InMemoryBusinessDataSource,
        timeline: PolicyTimeline,
        corpus: PolicyClauseCorpus,
    ) -> None:
        self._source = source
        self._timeline = timeline
        self._corpus = corpus

    def review(
        self,
        case: Case,
        *,
        collected_at: datetime,
        request_id_prefix: str,
    ) -> CaseReviewResult:
        evidence_id = f"{case.case_id}:refund:{case.refund_id}"
        fact_id = f"{evidence_id}:refund_received"
        model = MockModel(
            (
                ModelResponse(
                    response_id=f"{request_id_prefix}:payment-response",
                    finish_reason=ModelFinishReason.TOOL_CALLS,
                    message=ModelMessage(
                        role="assistant",
                        tool_calls=(
                            ToolCall(
                                call_id="call-payment",
                                tool_name="get_payment",
                                arguments={"payment_id": case.payment_id},
                            ),
                        ),
                    ),
                ),
                ModelResponse(
                    response_id=f"{request_id_prefix}:stop-response",
                    finish_reason=ModelFinishReason.STOP,
                    message=ModelMessage(
                        role="assistant",
                        content="Investigation complete.",
                    ),
                ),
                ModelResponse(
                    response_id=f"{request_id_prefix}:draft-response",
                    finish_reason=ModelFinishReason.STOP,
                    message=ModelMessage(role="assistant"),
                    structured_output={
                        "case_id": case.case_id,
                        "recommendation": "approve_refund",
                        "rationale": (
                            "The existing refund remains processing under the "
                            "policy effective when the dispute occurred."
                        ),
                        "risk_level": "high",
                        "evidence_references": [
                            {"evidence_id": evidence_id, "fact_id": fact_id}
                        ],
                        "policy_clause_ids": ["REFUND-DEMO-V1"],
                    },
                ),
            ),
            model_name="deterministic-demo-model",
            clock=lambda: collected_at,
        )
        return run_case_review(
            case,
            model,
            self._source,
            self._timeline,
            self._corpus,
            collected_at=collected_at,
            request_id_prefix=request_id_prefix,
        )


def create_demo_application(
    database_path: str | Path,
    *,
    clock: Clock = utc_now,
) -> CaseLensApplication:
    case = _demo_case()
    payment = _demo_payment()
    repository = SqliteRepository(database_path)
    resolution_store = SqliteResolutionStore(database_path)
    repository.save_case(case)
    resolution_store.seed_refunds((payment,))
    source = InMemoryBusinessDataSource(payments=(payment,))
    reviewer = DemoCaseReviewer(source, _demo_timeline(), _demo_corpus())
    return CaseLensApplication(
        repository,
        resolution_store,
        ResolutionWorkflow(resolution_store),
        reviewer,
        clock=clock,
    )


def _demo_case() -> Case:
    return Case(
        case_id="CASE-DEMO-001",
        case_type="refund_not_received",
        occurred_at=DEMO_OCCURRED_AT,
        customer_statement="The refund has not reached my account.",
        claim_amount=Decimal("50.00"),
        currency="CNY",
        order_id="order-demo-1",
        payment_id="payment-demo-1",
        refund_id="refund-demo-1",
    )


def _demo_payment() -> PaymentRecord:
    return PaymentRecord(
        payment_id="payment-demo-1",
        order_id="order-demo-1",
        status=PaymentStatus.PAID,
        amount=Decimal("50.00"),
        currency="CNY",
        paid_at=DEMO_OCCURRED_AT,
        refunds=(
            RefundRecord(
                refund_id="refund-demo-1",
                status=RefundStatus.PROCESSING,
                amount=Decimal("50.00"),
                currency="CNY",
                requested_at=DEMO_OCCURRED_AT,
            ),
        ),
    )


def _demo_timeline() -> PolicyTimeline:
    return PolicyTimeline(
        policy_id="refund-policy",
        versions=(
            PolicyVersion(
                policy_id="refund-policy",
                version="v1",
                effective_from=datetime(2026, 1, 1, tzinfo=UTC),
                effective_to=datetime(2026, 7, 1, tzinfo=UTC),
            ),
            PolicyVersion(
                policy_id="refund-policy",
                version="v2",
                effective_from=datetime(2026, 7, 1, tzinfo=UTC),
            ),
        ),
    )


def _demo_corpus() -> PolicyClauseCorpus:
    return PolicyClauseCorpus(
        clauses=(
            PolicyClause(
                clause_id="REFUND-DEMO-V1",
                policy_id="refund-policy",
                version="v1",
                text="Refund not received cases allow seven days for completion.",
            ),
        )
    )
