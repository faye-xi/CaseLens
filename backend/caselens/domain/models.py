from decimal import Decimal
from enum import StrEnum

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class CaseType(StrEnum):
    REFUND_NOT_RECEIVED = "refund_not_received"


class Case(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1)
    case_type: CaseType
    occurred_at: AwareDatetime
    customer_statement: str = Field(min_length=1)
    claim_amount: Decimal = Field(gt=0)
    currency: str = Field(min_length=1)
    order_id: str = Field(min_length=1)
    payment_id: str = Field(min_length=1)
    refund_id: str | None = None
