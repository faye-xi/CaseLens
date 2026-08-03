from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from caselens.tools.models import (
    LogisticsQuery,
    Message,
    MessageHistory,
    MessageQuery,
    MessageSender,
    OrderQuery,
    OrderRecord,
    OrderStatus,
    PaymentQuery,
    PaymentRecord,
    PaymentStatus,
    RefundRecord,
    RefundStatus,
    ShipmentRecord,
    ShipmentStatus,
    TrackingEvent,
)
from caselens.tools.services import (
    get_logistics,
    get_messages,
    get_order,
    get_payment,
)
from caselens.tools.source import (
    InMemoryBusinessDataSource,
    RecordNotFoundError,
    SourceQueryError,
)

NOW = datetime(2026, 7, 30, 10, 0, tzinfo=UTC)
LATER = datetime(2026, 7, 31, 10, 0, tzinfo=UTC)


def make_records() -> tuple[
    OrderRecord,
    PaymentRecord,
    ShipmentRecord,
    MessageHistory,
]:
    order = OrderRecord(
        order_id="order-1",
        customer_id="customer-1",
        status=OrderStatus.COMPLETED,
        total_amount=Decimal("129.90"),
        currency="CNY",
        placed_at=NOW,
    )
    payment = PaymentRecord(
        payment_id="payment-1",
        order_id="order-1",
        status=PaymentStatus.PAID,
        amount=Decimal("129.90"),
        currency="CNY",
        paid_at=NOW,
        refunds=(
            RefundRecord(
                refund_id="refund-1",
                status=RefundStatus.PROCESSING,
                amount=Decimal("129.90"),
                currency="CNY",
                requested_at=LATER,
            ),
        ),
    )
    shipment = ShipmentRecord(
        shipment_id="shipment-1",
        order_id="order-1",
        status=ShipmentStatus.DELIVERED,
        carrier="SF Express",
        tracking_number="SF001",
        events=(
            TrackingEvent(status="delivered", occurred_at=LATER),
            TrackingEvent(status="shipped", occurred_at=NOW),
        ),
    )
    messages = MessageHistory(
        order_id="order-1",
        messages=(
            Message(
                message_id="message-2",
                sender=MessageSender.AGENT,
                content="Refund is processing.",
                sent_at=LATER,
            ),
            Message(
                message_id="message-1",
                sender=MessageSender.CUSTOMER,
                content="I have not received the refund.",
                sent_at=NOW,
            ),
        ),
    )
    return order, payment, shipment, messages


@pytest.mark.parametrize(
    ("query_type", "field"),
    [
        (OrderQuery, "order_id"),
        (PaymentQuery, "payment_id"),
        (LogisticsQuery, "order_id"),
        (MessageQuery, "order_id"),
    ],
)
def test_queries_reject_blank_identifiers(query_type: type, field: str) -> None:
    with pytest.raises(ValidationError):
        query_type(**{field: "   "})


def test_query_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        OrderQuery(order_id="order-1", unexpected=True)


def test_records_reject_non_positive_amounts() -> None:
    with pytest.raises(ValidationError):
        OrderRecord(
            order_id="order-1",
            customer_id="customer-1",
            status=OrderStatus.COMPLETED,
            total_amount=Decimal(0),
            currency="CNY",
            placed_at=NOW,
        )


def test_records_reject_timezone_naive_times() -> None:
    payload = (
        '{"order_id":"order-1","customer_id":"customer-1",'
        '"status":"completed","total_amount":"129.90","currency":"CNY",'
        '"placed_at":"2026-07-30T10:00:00"}'
    )

    with pytest.raises(ValidationError):
        OrderRecord.model_validate_json(payload)


def test_four_read_tools_return_structured_records_in_time_order() -> None:
    order, payment, shipment, messages = make_records()
    source = InMemoryBusinessDataSource(
        orders=(order,),
        payments=(payment,),
        shipments=(shipment,),
        message_histories=(messages,),
    )

    assert get_order(source, OrderQuery(order_id="order-1")) == order
    assert get_payment(source, PaymentQuery(payment_id="payment-1")) == payment
    assert [
        event.status
        for event in get_logistics(source, LogisticsQuery(order_id="order-1")).events
    ] == ["shipped", "delivered"]
    assert [
        message.message_id
        for message in get_messages(source, MessageQuery(order_id="order-1")).messages
    ] == ["message-1", "message-2"]


def test_known_order_can_have_an_empty_message_history() -> None:
    order, payment, shipment, _ = make_records()
    source = InMemoryBusinessDataSource(
        orders=(order,),
        payments=(payment,),
        shipments=(shipment,),
        message_histories=(MessageHistory(order_id="order-1"),),
    )

    result = get_messages(source, MessageQuery(order_id="order-1"))

    assert result.order_id == "order-1"
    assert result.messages == ()


@pytest.mark.parametrize(
    ("tool", "query"),
    [
        (get_order, OrderQuery(order_id="missing")),
        (get_payment, PaymentQuery(payment_id="missing")),
        (get_logistics, LogisticsQuery(order_id="missing")),
        (get_messages, MessageQuery(order_id="missing")),
    ],
)
def test_missing_records_raise_explicit_not_found(tool: object, query: object) -> None:
    source = InMemoryBusinessDataSource()

    with pytest.raises(RecordNotFoundError):
        tool(source, query)  # type: ignore[operator]


def test_source_failure_is_not_reported_as_missing_or_empty() -> None:
    order, payment, shipment, messages = make_records()
    source = InMemoryBusinessDataSource(
        orders=(order,),
        payments=(payment,),
        shipments=(shipment,),
        message_histories=(messages,),
        failing_operations={"messages"},
    )

    with pytest.raises(SourceQueryError):
        get_messages(source, MessageQuery(order_id="order-1"))


def test_source_copies_inputs_and_repeated_reads_are_stable() -> None:
    order, payment, shipment, messages = make_records()
    source = InMemoryBusinessDataSource(
        orders=(order,),
        payments=(payment,),
        shipments=(shipment,),
        message_histories=(messages,),
    )

    first = get_payment(source, PaymentQuery(payment_id="payment-1"))
    second = get_payment(source, PaymentQuery(payment_id="payment-1"))

    assert first == second
    assert first is not second
    with pytest.raises(ValidationError):
        first.amount = Decimal("1.00")
