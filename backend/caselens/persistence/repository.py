import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, ValidationError
from sqlalchemy import create_engine, event, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from caselens.domain.investigation import (
    Evidence,
    EvidenceBundle,
    EvidenceConflict,
    EvidenceStatus,
    Fact,
    FactReference,
    Identifier,
    MissingEvidence,
)
from caselens.domain.models import Case
from caselens.persistence.models import (
    Base,
    CaseRow,
    EvidenceConflictRow,
    EvidenceRow,
    FactRow,
    InvestigationRunRow,
    MissingEvidenceRow,
)


class PersistenceError(RuntimeError):
    """The database could not safely complete a repository operation."""


class RecordConflictError(PersistenceError):
    """The write conflicts with records already stored."""


class RecordNotFoundError(PersistenceError):
    """The requested repository record does not exist."""


class RepositoryInputError(PersistenceError):
    """The supplied domain objects cannot form one stored aggregate."""


class InvestigationRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: Identifier
    case_id: Identifier
    evidence_status: EvidenceStatus
    created_at: AwareDatetime


class StoredInvestigation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    record: InvestigationRecord
    case: Case
    bundle: EvidenceBundle


class SqliteRepository:
    def __init__(self, database_path: str | Path) -> None:
        path = Path(database_path)
        self._engine = create_engine(f"sqlite:///{path.as_posix()}")
        event.listen(self._engine, "connect", _enable_sqlite_foreign_keys)
        Base.metadata.create_all(self._engine)
        self._session_factory = sessionmaker(self._engine)

    def close(self) -> None:
        self._engine.dispose()

    def save_investigation(
        self,
        *,
        case: Case,
        bundle: EvidenceBundle,
        run_id: str,
        created_at: datetime,
    ) -> InvestigationRecord:
        if bundle.case_id != case.case_id:
            raise RepositoryInputError(
                "The case and evidence bundle must reference the same case."
            )
        try:
            record = InvestigationRecord(
                run_id=run_id,
                case_id=case.case_id,
                evidence_status=bundle.status,
                created_at=created_at,
            )
        except ValidationError as error:
            raise RepositoryInputError(
                "The investigation run metadata is invalid."
            ) from error
        try:
            with self._session_factory.begin() as session:
                stored_case = session.get(CaseRow, case.case_id)
                if stored_case is None:
                    session.add(_case_to_row(case))
                    session.flush()
                elif _row_to_case(stored_case) != case:
                    raise RecordConflictError(
                        "The case ID conflicts with different stored case data."
                    )
                session.add(
                    InvestigationRunRow(
                        run_id=record.run_id,
                        case_id=record.case_id,
                        evidence_status=record.evidence_status.value,
                        created_at=record.created_at.isoformat(),
                    )
                )
                session.flush()
                _add_bundle_rows(session, record.run_id, bundle)
        except IntegrityError as error:
            raise RecordConflictError(
                "The investigation conflicts with stored records."
            ) from error
        except SQLAlchemyError as error:
            raise PersistenceError("The investigation could not be saved.") from error
        return record

    def get_case(self, case_id: str) -> Case:
        try:
            with self._session_factory() as session:
                row = session.get(CaseRow, case_id)
                if row is None:
                    raise RecordNotFoundError(f"Case {case_id!r} was not found.")
                return _row_to_case(row)
        except RecordNotFoundError:
            raise
        except SQLAlchemyError as error:
            raise PersistenceError("The case could not be loaded.") from error

    def get_investigation(self, run_id: str) -> StoredInvestigation:
        try:
            with self._session_factory() as session:
                run = session.get(InvestigationRunRow, run_id)
                if run is None:
                    raise RecordNotFoundError(
                        f"Investigation {run_id!r} was not found."
                    )
                case_row = session.get(CaseRow, run.case_id)
                if case_row is None:
                    raise PersistenceError(
                        "The investigation references a missing case."
                    )
                return StoredInvestigation(
                    record=_row_to_record(run),
                    case=_row_to_case(case_row),
                    bundle=_load_bundle(session, run),
                )
        except (PersistenceError, RecordNotFoundError):
            raise
        except SQLAlchemyError as error:
            raise PersistenceError("The investigation could not be loaded.") from error


def _enable_sqlite_foreign_keys(
    dbapi_connection: object,
    _connection_record: object,
) -> None:
    cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def _case_to_row(case: Case) -> CaseRow:
    return CaseRow(
        case_id=case.case_id,
        case_type=case.case_type.value,
        occurred_at=case.occurred_at.isoformat(),
        customer_statement=case.customer_statement,
        claim_amount=str(case.claim_amount),
        currency=case.currency,
        order_id=case.order_id,
        payment_id=case.payment_id,
        refund_id=case.refund_id,
    )


def _row_to_case(row: CaseRow) -> Case:
    return Case(
        case_id=row.case_id,
        case_type=row.case_type,
        occurred_at=datetime.fromisoformat(row.occurred_at),
        customer_statement=row.customer_statement,
        claim_amount=Decimal(row.claim_amount),
        currency=row.currency,
        order_id=row.order_id,
        payment_id=row.payment_id,
        refund_id=row.refund_id,
    )


def _add_bundle_rows(session: Session, run_id: str, bundle: EvidenceBundle) -> None:
    for evidence_position, evidence in enumerate(bundle.evidence):
        session.add(
            EvidenceRow(
                run_id=run_id,
                evidence_id=evidence.evidence_id,
                position=evidence_position,
                kind=evidence.kind.value,
                source_record_id=evidence.source_record_id,
                collected_at=evidence.collected_at.isoformat(),
            )
        )
    session.flush()

    for evidence in bundle.evidence:
        for fact_position, fact in enumerate(evidence.facts):
            value_type, value_payload = _serialize_fact_value(fact.value)
            session.add(
                FactRow(
                    run_id=run_id,
                    evidence_id=evidence.evidence_id,
                    fact_id=fact.fact_id,
                    position=fact_position,
                    key=fact.key.value,
                    value_type=value_type,
                    value_payload=value_payload,
                )
            )
    for position, missing in enumerate(bundle.missing_evidence):
        session.add(
            MissingEvidenceRow(
                run_id=run_id,
                position=position,
                kind=missing.kind.value,
                reason=missing.reason,
            )
        )
    session.flush()

    for position, conflict in enumerate(bundle.conflicts):
        session.add(
            EvidenceConflictRow(
                run_id=run_id,
                position=position,
                key=conflict.key.value,
                left_evidence_id=conflict.left.evidence_id,
                left_fact_id=conflict.left.fact_id,
                right_evidence_id=conflict.right.evidence_id,
                right_fact_id=conflict.right.fact_id,
            )
        )


def _load_bundle(
    session: Session,
    run: InvestigationRunRow,
) -> EvidenceBundle:
    evidence_rows = session.scalars(
        select(EvidenceRow)
        .where(EvidenceRow.run_id == run.run_id)
        .order_by(EvidenceRow.position)
    ).all()
    evidence = tuple(
        Evidence(
            evidence_id=row.evidence_id,
            kind=row.kind,
            source_record_id=row.source_record_id,
            collected_at=datetime.fromisoformat(row.collected_at),
            facts=tuple(
                Fact(
                    fact_id=fact.fact_id,
                    key=fact.key,
                    value=_deserialize_fact_value(
                        fact.value_type,
                        fact.value_payload,
                    ),
                )
                for fact in session.scalars(
                    select(FactRow)
                    .where(
                        FactRow.run_id == run.run_id,
                        FactRow.evidence_id == row.evidence_id,
                    )
                    .order_by(FactRow.position)
                ).all()
            ),
        )
        for row in evidence_rows
    )
    missing = tuple(
        MissingEvidence(kind=row.kind, reason=row.reason)
        for row in session.scalars(
            select(MissingEvidenceRow)
            .where(MissingEvidenceRow.run_id == run.run_id)
            .order_by(MissingEvidenceRow.position)
        ).all()
    )
    conflicts = tuple(
        EvidenceConflict(
            key=row.key,
            left=FactReference(
                evidence_id=row.left_evidence_id,
                fact_id=row.left_fact_id,
            ),
            right=FactReference(
                evidence_id=row.right_evidence_id,
                fact_id=row.right_fact_id,
            ),
        )
        for row in session.scalars(
            select(EvidenceConflictRow)
            .where(EvidenceConflictRow.run_id == run.run_id)
            .order_by(EvidenceConflictRow.position)
        ).all()
    )
    return EvidenceBundle(
        case_id=run.case_id,
        evidence=evidence,
        missing_evidence=missing,
        conflicts=conflicts,
    )


def _row_to_record(row: InvestigationRunRow) -> InvestigationRecord:
    return InvestigationRecord(
        run_id=row.run_id,
        case_id=row.case_id,
        evidence_status=row.evidence_status,
        created_at=datetime.fromisoformat(row.created_at),
    )


def _serialize_fact_value(
    value: str | bool | Decimal,
) -> tuple[Literal["string", "boolean", "decimal"], str]:
    if type(value) is bool:
        return "boolean", json.dumps(value)
    if isinstance(value, Decimal):
        return "decimal", str(value)
    return "string", value


def _deserialize_fact_value(
    value_type: str,
    payload: str,
) -> str | bool | Decimal:
    if value_type == "boolean":
        return bool(json.loads(payload))
    if value_type == "decimal":
        return Decimal(payload)
    if value_type == "string":
        return payload
    raise PersistenceError(f"Unknown stored fact value type: {value_type!r}.")
