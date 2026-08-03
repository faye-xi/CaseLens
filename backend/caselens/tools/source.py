from collections.abc import Iterable
from collections.abc import Set as AbstractSet
from typing import Protocol

from caselens.tools.models import (
    MessageHistory,
    OrderRecord,
    PaymentRecord,
    ShipmentRecord,
)


class BusinessDataError(RuntimeError):
    """A read-only business data lookup could not return a record."""


class RecordNotFoundError(BusinessDataError):
    """The requested business record does not exist."""


class SourceQueryError(BusinessDataError):
    """The backing business source failed while executing a query."""


class SourceTimeoutError(BusinessDataError):
    """The backing business source timed out while executing a query."""


class BusinessDataSource(Protocol):
    def get_order(self, order_id: str) -> OrderRecord: ...

    def get_payment(self, payment_id: str) -> PaymentRecord: ...

    def get_logistics(self, order_id: str) -> ShipmentRecord: ...

    def get_messages(self, order_id: str) -> MessageHistory: ...


class InMemoryBusinessDataSource:
    def __init__(
        self,
        *,
        orders: Iterable[OrderRecord] = (),
        payments: Iterable[PaymentRecord] = (),
        shipments: Iterable[ShipmentRecord] = (),
        message_histories: Iterable[MessageHistory] = (),
        failing_operations: AbstractSet[str] = frozenset(),
        timed_out_operations: AbstractSet[str] = frozenset(),
    ) -> None:
        self._orders = _index_records(orders, "order_id")
        self._payments = _index_records(payments, "payment_id")
        self._shipments = _index_records(shipments, "order_id")
        self._message_histories = _index_records(message_histories, "order_id")
        self._failing_operations = frozenset(failing_operations)
        self._timed_out_operations = frozenset(timed_out_operations)

    def get_order(self, order_id: str) -> OrderRecord:
        return self._read("orders", self._orders, order_id)

    def get_payment(self, payment_id: str) -> PaymentRecord:
        return self._read("payments", self._payments, payment_id)

    def get_logistics(self, order_id: str) -> ShipmentRecord:
        shipment = self._read("logistics", self._shipments, order_id)
        return shipment.model_copy(
            update={
                "events": tuple(
                    sorted(shipment.events, key=lambda event: event.occurred_at)
                )
            },
            deep=True,
        )

    def get_messages(self, order_id: str) -> MessageHistory:
        history = self._read("messages", self._message_histories, order_id)
        return history.model_copy(
            update={
                "messages": tuple(
                    sorted(history.messages, key=lambda message: message.sent_at)
                )
            },
            deep=True,
        )

    def _read(self, operation: str, records: dict[str, object], key: str):
        if operation in self._timed_out_operations:
            raise SourceTimeoutError(f"The {operation} source query timed out.")
        if operation in self._failing_operations:
            raise SourceQueryError(f"The {operation} source query failed.")
        record = records.get(key)
        if record is None:
            raise RecordNotFoundError(
                f"No {operation} record was found for identifier {key!r}."
            )
        return record.model_copy(deep=True)  # type: ignore[attr-defined,no-any-return]


def _index_records(records: Iterable[object], key_field: str) -> dict[str, object]:
    indexed: dict[str, object] = {}
    for record in records:
        key = getattr(record, key_field)
        if key in indexed:
            raise ValueError(f"Duplicate source record identifier: {key!r}.")
        indexed[key] = record.model_copy(deep=True)  # type: ignore[attr-defined]
    return indexed
