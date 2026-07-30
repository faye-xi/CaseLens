from sqlalchemy import (
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class CaseRow(Base):
    __tablename__ = "cases"

    case_id: Mapped[str] = mapped_column(String, primary_key=True)
    case_type: Mapped[str] = mapped_column(String, nullable=False)
    occurred_at: Mapped[str] = mapped_column(String, nullable=False)
    customer_statement: Mapped[str] = mapped_column(Text, nullable=False)
    claim_amount: Mapped[str] = mapped_column(Text, nullable=False)
    currency: Mapped[str] = mapped_column(String, nullable=False)
    order_id: Mapped[str] = mapped_column(String, nullable=False)
    payment_id: Mapped[str] = mapped_column(String, nullable=False)
    refund_id: Mapped[str | None] = mapped_column(String)


class InvestigationRunRow(Base):
    __tablename__ = "investigation_runs"

    run_id: Mapped[str] = mapped_column(String, primary_key=True)
    case_id: Mapped[str] = mapped_column(
        ForeignKey("cases.case_id"),
        nullable=False,
    )
    evidence_status: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[str] = mapped_column(String, nullable=False)


class EvidenceRow(Base):
    __tablename__ = "evidence"

    run_id: Mapped[str] = mapped_column(
        ForeignKey("investigation_runs.run_id"),
        primary_key=True,
    )
    evidence_id: Mapped[str] = mapped_column(String, primary_key=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    source_record_id: Mapped[str] = mapped_column(String, nullable=False)
    collected_at: Mapped[str] = mapped_column(String, nullable=False)


class FactRow(Base):
    __tablename__ = "facts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["run_id", "evidence_id"],
            ["evidence.run_id", "evidence.evidence_id"],
        ),
    )

    run_id: Mapped[str] = mapped_column(String, primary_key=True)
    evidence_id: Mapped[str] = mapped_column(String, primary_key=True)
    fact_id: Mapped[str] = mapped_column(String, primary_key=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    key: Mapped[str] = mapped_column(String, nullable=False)
    value_type: Mapped[str] = mapped_column(String, nullable=False)
    value_payload: Mapped[str] = mapped_column(Text, nullable=False)


class MissingEvidenceRow(Base):
    __tablename__ = "missing_evidence"

    item_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("investigation_runs.run_id"),
        nullable=False,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)


class EvidenceConflictRow(Base):
    __tablename__ = "evidence_conflicts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["run_id", "left_evidence_id", "left_fact_id"],
            ["facts.run_id", "facts.evidence_id", "facts.fact_id"],
        ),
        ForeignKeyConstraint(
            ["run_id", "right_evidence_id", "right_fact_id"],
            ["facts.run_id", "facts.evidence_id", "facts.fact_id"],
        ),
    )

    conflict_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("investigation_runs.run_id"),
        nullable=False,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    key: Mapped[str] = mapped_column(String, nullable=False)
    left_evidence_id: Mapped[str] = mapped_column(String, nullable=False)
    left_fact_id: Mapped[str] = mapped_column(String, nullable=False)
    right_evidence_id: Mapped[str] = mapped_column(String, nullable=False)
    right_fact_id: Mapped[str] = mapped_column(String, nullable=False)
