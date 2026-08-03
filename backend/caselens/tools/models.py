from decimal import Decimal
from enum import StrEnum
from typing import Annotated

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
)

Identifier = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
]
NonBlankText = Identifier
PositiveAmount = Annotated[Decimal, Field(gt=0)]


class ToolModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class OrderStatus(StrEnum):
    CREATED = "created"
    PAID = "paid"
    SHIPPED = "shipped"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class PaymentStatus(StrEnum):
    PENDING = "pending"
    PAID = "paid"
    FAILED = "failed"
    REFUNDED = "refunded"
    PARTIALLY_REFUNDED = "partially_refunded"


class RefundStatus(StrEnum):
    REQUESTED = "requested"
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ShipmentStatus(StrEnum):
    PENDING = "pending"
    IN_TRANSIT = "in_transit"
    DELIVERED = "delivered"
    EXCEPTION = "exception"
    RETURNED = "returned"


class MessageSender(StrEnum):
    CUSTOMER = "customer"
    AGENT = "agent"
    SYSTEM = "system"


class OrderQuery(ToolModel):
    order_id: Identifier


class PaymentQuery(ToolModel):
    payment_id: Identifier


class LogisticsQuery(ToolModel):
    order_id: Identifier


class MessageQuery(ToolModel):
    order_id: Identifier


class OrderRecord(ToolModel):
    order_id: Identifier
    customer_id: Identifier
    status: OrderStatus
    total_amount: PositiveAmount
    currency: NonBlankText
    placed_at: AwareDatetime


class RefundRecord(ToolModel):
    refund_id: Identifier
    status: RefundStatus
    amount: PositiveAmount
    currency: NonBlankText
    requested_at: AwareDatetime
    completed_at: AwareDatetime | None = None


class PaymentRecord(ToolModel):
    payment_id: Identifier
    order_id: Identifier
    status: PaymentStatus
    amount: PositiveAmount
    currency: NonBlankText
    paid_at: AwareDatetime | None = None
    refunds: tuple[RefundRecord, ...] = ()


class TrackingEvent(ToolModel):
    status: NonBlankText
    occurred_at: AwareDatetime
    location: str | None = None


class ShipmentRecord(ToolModel):
    shipment_id: Identifier
    order_id: Identifier
    status: ShipmentStatus
    carrier: NonBlankText
    tracking_number: Identifier
    events: tuple[TrackingEvent, ...] = ()


class Message(ToolModel):
    message_id: Identifier
    sender: MessageSender
    content: NonBlankText
    sent_at: AwareDatetime


class MessageHistory(ToolModel):
    order_id: Identifier
    messages: tuple[Message, ...] = ()
