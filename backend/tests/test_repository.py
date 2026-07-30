from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from caselens.domain.investigation import (
    Evidence,
    EvidenceBundle,
    EvidenceConflict,
    Fact,
    FactReference,
    MissingEvidence,
)
from caselens.domain.models import Case
from caselens.persistence import repository as repository_module
from caselens.persistence.repository import (
    RecordConflictError,
    RecordNotFoundError,
    RepositoryInputError,
    SqliteRepository,
)


def test_saved_investigation_round_trips_after_repository_reopens(tmp_path) -> None:
    database_path = tmp_path / "caselens.db"
    occurred_at = datetime(
        2026,
        7,
        29,
        18,
        30,
        tzinfo=timezone(timedelta(hours=8)),
    )
    collected_at = datetime(
        2026,
        7,
        29,
        19,
        5,
        tzinfo=timezone(timedelta(hours=8)),
    )
    created_at = datetime(
        2026,
        7,
        29,
        19,
        10,
        tzinfo=UTC,
    )
    case = Case(
        case_id="CASE-3001",
        case_type="refund_not_received",
        occurred_at=occurred_at,
        customer_statement="The refund has not reached my account.",
        claim_amount=Decimal("109.90"),
        currency="CNY",
        order_id="ORDER-3001",
        payment_id="PAYMENT-3001",
        refund_id="REFUND-3001",
    )
    bundle = EvidenceBundle(
        case_id=case.case_id,
        evidence=(
            Evidence(
                evidence_id="EVIDENCE-3001",
                kind="refund_record",
                source_record_id="REFUND-3001",
                collected_at=collected_at,
                facts=(
                    Fact(
                        fact_id="FACT-STATUS-3001",
                        key="refund_status",
                        value="processed",
                    ),
                    Fact(
                        fact_id="FACT-AMOUNT-3001",
                        key="refund_amount",
                        value=Decimal("109.90"),
                    ),
                ),
            ),
        ),
    )

    repository = SqliteRepository(database_path)
    expected_record = repository.save_investigation(
        case=case,
        bundle=bundle,
        run_id="RUN-3001",
        created_at=created_at,
    )
    repository.close()

    reopened_repository = SqliteRepository(database_path)
    stored = reopened_repository.get_investigation("RUN-3001")
    reopened_repository.close()

    assert stored.record == expected_record
    assert stored.record.evidence_status == "complete"
    assert stored.case == case
    assert stored.bundle == bundle


def test_missing_records_raise_explicit_not_found_error(tmp_path) -> None:
    repository = SqliteRepository(tmp_path / "caselens.db")

    with pytest.raises(RecordNotFoundError, match="CASE-UNKNOWN"):
        repository.get_case("CASE-UNKNOWN")
    with pytest.raises(RecordNotFoundError, match="RUN-UNKNOWN"):
        repository.get_investigation("RUN-UNKNOWN")

    repository.close()


def test_mismatched_case_and_bundle_are_rejected_before_writing(tmp_path) -> None:
    repository = SqliteRepository(tmp_path / "caselens.db")
    case = _case()
    bundle = EvidenceBundle(
        case_id="CASE-DIFFERENT",
        evidence=_complete_bundle().evidence,
    )

    with pytest.raises(RepositoryInputError, match="same case"):
        repository.save_investigation(
            case=case,
            bundle=bundle,
            run_id="RUN-MISMATCH",
            created_at=_created_at(),
        )
    with pytest.raises(RecordNotFoundError):
        repository.get_case(case.case_id)

    repository.close()


@pytest.mark.parametrize(
    ("run_id", "created_at"),
    [
        ("", datetime(2026, 7, 29, 19, 10, tzinfo=UTC)),
        ("RUN-NAIVE-TIME", datetime(2026, 7, 29, 19, 10)),  # noqa: DTZ001
    ],
)
def test_invalid_run_metadata_is_an_explicit_input_error(
    tmp_path,
    run_id,
    created_at,
) -> None:
    repository = SqliteRepository(tmp_path / f"{run_id or 'blank'}.db")

    with pytest.raises(RepositoryInputError, match="run metadata"):
        repository.save_investigation(
            case=_case(),
            bundle=_complete_bundle(),
            run_id=run_id,
            created_at=created_at,
        )
    with pytest.raises(RecordNotFoundError):
        repository.get_case("CASE-3001")

    repository.close()


def test_duplicate_save_is_explicit_and_preserves_original(tmp_path) -> None:
    repository = SqliteRepository(tmp_path / "caselens.db")
    case = _case()
    bundle = _complete_bundle()
    repository.save_investigation(
        case=case,
        bundle=bundle,
        run_id="RUN-DUPLICATE",
        created_at=_created_at(),
    )

    with pytest.raises(RecordConflictError, match="conflicts"):
        repository.save_investigation(
            case=case,
            bundle=bundle,
            run_id="RUN-DUPLICATE",
            created_at=_created_at(),
        )

    assert repository.get_investigation("RUN-DUPLICATE").bundle == bundle
    repository.close()


def test_same_case_can_have_multiple_investigation_runs(tmp_path) -> None:
    repository = SqliteRepository(tmp_path / "caselens.db")
    case = _case()
    bundle = _complete_bundle()
    repository.save_investigation(
        case=case,
        bundle=bundle,
        run_id="RUN-FIRST",
        created_at=_created_at(),
    )

    second_record = repository.save_investigation(
        case=case,
        bundle=bundle,
        run_id="RUN-SECOND",
        created_at=_created_at(),
    )

    assert second_record.run_id == "RUN-SECOND"
    assert repository.get_investigation("RUN-FIRST").case == case
    assert repository.get_investigation("RUN-SECOND").case == case
    repository.close()


def test_case_amount_round_trips_without_decimal_precision_loss(tmp_path) -> None:
    repository = SqliteRepository(tmp_path / "caselens.db")
    case = _case().model_copy(
        update={"claim_amount": Decimal("109.123456789012345678")},
    )
    repository.save_investigation(
        case=case,
        bundle=_complete_bundle(),
        run_id="RUN-PRECISE-AMOUNT",
        created_at=_created_at(),
    )

    assert repository.get_case(case.case_id).claim_amount == case.claim_amount
    repository.close()


def test_foreign_key_constraints_are_enabled_on_repository_connections(
    tmp_path,
) -> None:
    repository = SqliteRepository(tmp_path / "caselens.db")

    with pytest.raises(IntegrityError), repository._engine.begin() as connection:
        connection.execute(
            text(
                """
                    INSERT INTO investigation_runs
                        (run_id, case_id, evidence_status, created_at)
                    VALUES
                        ('RUN-ORPHAN', 'CASE-ORPHAN', 'complete',
                         '2026-07-29T19:10:00+00:00')
                    """
            )
        )

    repository.close()


def test_mid_write_failure_rolls_back_case_and_all_children(
    tmp_path,
    monkeypatch,
) -> None:
    repository = SqliteRepository(tmp_path / "caselens.db")
    original_add_bundle_rows = repository_module._add_bundle_rows

    def fail_after_bundle_rows(session, run_id, bundle) -> None:
        original_add_bundle_rows(session, run_id, bundle)
        session.flush()
        raise RuntimeError("forced failure after child inserts")

    monkeypatch.setattr(
        repository_module,
        "_add_bundle_rows",
        fail_after_bundle_rows,
    )

    with pytest.raises(RuntimeError, match="forced failure"):
        repository.save_investigation(
            case=_case(),
            bundle=_complete_bundle(),
            run_id="RUN-ROLLBACK",
            created_at=_created_at(),
        )

    with pytest.raises(RecordNotFoundError):
        repository.get_case("CASE-3001")
    with pytest.raises(RecordNotFoundError):
        repository.get_investigation("RUN-ROLLBACK")
    repository.close()


def test_missing_and_conflicting_evidence_round_trip(tmp_path) -> None:
    repository = SqliteRepository(tmp_path / "caselens.db")
    case = _case()
    customer_fact = Fact(
        fact_id="FACT-CUSTOMER-RECEIVED",
        key="refund_received",
        value=False,
    )
    system_fact = Fact(
        fact_id="FACT-SYSTEM-RECEIVED",
        key="refund_received",
        value=True,
    )
    bundle = EvidenceBundle(
        case_id=case.case_id,
        evidence=(
            Evidence(
                evidence_id="EVIDENCE-CUSTOMER",
                kind="customer_statement",
                source_record_id=case.case_id,
                collected_at=_created_at(),
                facts=(customer_fact,),
            ),
            Evidence(
                evidence_id="EVIDENCE-REFUND",
                kind="refund_record",
                source_record_id="REFUND-3001",
                collected_at=_created_at(),
                facts=(system_fact,),
            ),
        ),
        missing_evidence=(
            MissingEvidence(
                kind="refund_record",
                reason="A second refund record has not been retrieved.",
            ),
        ),
        conflicts=(
            EvidenceConflict(
                key="refund_received",
                left=FactReference(
                    evidence_id="EVIDENCE-CUSTOMER",
                    fact_id=customer_fact.fact_id,
                ),
                right=FactReference(
                    evidence_id="EVIDENCE-REFUND",
                    fact_id=system_fact.fact_id,
                ),
            ),
        ),
    )

    record = repository.save_investigation(
        case=case,
        bundle=bundle,
        run_id="RUN-CONFLICT",
        created_at=_created_at(),
    )

    assert record.evidence_status == "conflicted"
    assert repository.get_investigation("RUN-CONFLICT").bundle == bundle
    repository.close()


def _case() -> Case:
    return Case(
        case_id="CASE-3001",
        case_type="refund_not_received",
        occurred_at=datetime(
            2026,
            7,
            29,
            18,
            30,
            tzinfo=timezone(timedelta(hours=8)),
        ),
        customer_statement="The refund has not reached my account.",
        claim_amount=Decimal("109.90"),
        currency="CNY",
        order_id="ORDER-3001",
        payment_id="PAYMENT-3001",
        refund_id="REFUND-3001",
    )


def _complete_bundle() -> EvidenceBundle:
    return EvidenceBundle(
        case_id="CASE-3001",
        evidence=(
            Evidence(
                evidence_id="EVIDENCE-3001",
                kind="refund_record",
                source_record_id="REFUND-3001",
                collected_at=_created_at(),
                facts=(
                    Fact(
                        fact_id="FACT-STATUS-3001",
                        key="refund_status",
                        value="processed",
                    ),
                ),
            ),
        ),
    )


def _created_at() -> datetime:
    return datetime(2026, 7, 29, 19, 10, tzinfo=UTC)
