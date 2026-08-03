from caselens.tools.models import (
    LogisticsQuery,
    MessageHistory,
    MessageQuery,
    OrderQuery,
    OrderRecord,
    PaymentQuery,
    PaymentRecord,
    ShipmentRecord,
)
from caselens.tools.source import BusinessDataSource


def get_order(source: BusinessDataSource, query: OrderQuery) -> OrderRecord:
    return source.get_order(query.order_id)


def get_payment(source: BusinessDataSource, query: PaymentQuery) -> PaymentRecord:
    return source.get_payment(query.payment_id)


def get_logistics(
    source: BusinessDataSource,
    query: LogisticsQuery,
) -> ShipmentRecord:
    return source.get_logistics(query.order_id)


def get_messages(
    source: BusinessDataSource,
    query: MessageQuery,
) -> MessageHistory:
    return source.get_messages(query.order_id)
