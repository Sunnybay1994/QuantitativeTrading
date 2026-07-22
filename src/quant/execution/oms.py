"""M4-P1 pure in-memory OMS order reducer (no network/DB IO).

Based on pending-main-acceptance M4-D0 contracts. Does not claim Gate pass.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, replace

from quant.domain.enums import ExecutionEventType, OrderStatus
from quant.execution.contracts import (
    ContractError,
    ExecutionEvent,
    OrderCommand,
    build_execution_event_identity,
    build_order_command_identity,
    build_order_intent_identity,
)

_HEX64 = frozenset("0123456789abcdef")

_TERMINAL = frozenset(
    {
        OrderStatus.FILLED,
        OrderStatus.CANCELLED,
        OrderStatus.REJECTED,
    }
)

_FILL_TYPES = frozenset(
    {
        ExecutionEventType.PARTIAL_FILL,
        ExecutionEventType.FILL,
    }
)


class OmsError(ValueError):
    """OMS state-machine or idempotency violation (fail closed)."""


def _require_hex64(name: str, value: object) -> str:
    if type(value) is not str or len(value) != 64 or any(char not in _HEX64 for char in value):
        raise OmsError(f"{name} must be bare 64-char lowercase hex")
    return value


def _require_int(name: str, value: object, *, minimum: int | None = None) -> int:
    if type(value) is not int or isinstance(value, bool):
        raise TypeError(f"{name} must be int")
    if minimum is not None and value < minimum:
        raise OmsError(f"{name} must be >= {minimum}")
    return value


def _require_utc_datetime(name: str, value: object) -> dt.datetime:
    if type(value) is not dt.datetime:
        raise TypeError(f"{name} must be datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise OmsError(f"{name} must be timezone-aware UTC")
    if value.utcoffset() != dt.timedelta(0):
        raise OmsError(f"{name} must be timezone-aware UTC")
    return value


def _require_optional_non_empty_str(name: str, value: object) -> str | None:
    if value is None:
        return None
    if type(value) is not str or not value:
        raise OmsError(f"{name} must be None or non-empty str")
    return value


@dataclass(frozen=True, slots=True)
class OrderAggregate:
    """In-memory OMS order projection; immutable reduce result."""

    command_id: str
    status: OrderStatus
    filled_quantity: int
    broker_order_id: str | None
    reject_code: str | None
    applied_event_ids: tuple[str, ...]
    command_quantity: int
    last_event_at: dt.datetime | None

    def __post_init__(self) -> None:
        _require_hex64("command_id", self.command_id)
        if not isinstance(self.status, OrderStatus):
            raise TypeError("status must be OrderStatus")
        qty = _require_int("command_quantity", self.command_quantity, minimum=1)
        filled = _require_int("filled_quantity", self.filled_quantity, minimum=0)
        if filled > qty:
            raise OmsError("filled_quantity exceeds command_quantity")
        _require_optional_non_empty_str("broker_order_id", self.broker_order_id)
        reject = _require_optional_non_empty_str("reject_code", self.reject_code)
        if type(self.applied_event_ids) is not tuple:
            raise TypeError("applied_event_ids must be tuple[str, ...]")
        seen: set[str] = set()
        for event_id in self.applied_event_ids:
            _require_hex64("applied_event_id", event_id)
            if event_id in seen:
                raise OmsError("duplicate applied_event_id")
            seen.add(event_id)
        if self.applied_event_ids:
            if self.last_event_at is None:
                raise OmsError("non-empty applied_event_ids require last_event_at")
            _require_utc_datetime("last_event_at", self.last_event_at)
        elif self.last_event_at is not None:
            raise OmsError("empty applied_event_ids require last_event_at is None")

        status = self.status
        if status is OrderStatus.CREATED:
            if filled != 0:
                raise OmsError("CREATED requires filled_quantity == 0")
            if self.applied_event_ids:
                raise OmsError("CREATED requires empty applied_event_ids")
            if reject is not None:
                raise OmsError("CREATED must not set reject_code")
            if self.broker_order_id is not None:
                raise OmsError("CREATED must not set broker_order_id")
        elif status is OrderStatus.SUBMITTED:
            if filled != 0:
                raise OmsError("SUBMITTED requires filled_quantity == 0")
            if not self.applied_event_ids:
                raise OmsError("SUBMITTED requires applied events")
            if reject is not None:
                raise OmsError("SUBMITTED must not set reject_code")
        elif status is OrderStatus.PARTIAL_FILLED:
            if not (0 < filled < qty):
                raise OmsError("PARTIAL_FILLED requires filled in (0, command_quantity)")
            if not self.applied_event_ids:
                raise OmsError("PARTIAL_FILLED requires applied events")
            if reject is not None:
                raise OmsError("PARTIAL_FILLED must not set reject_code")
        elif status is OrderStatus.FILLED:
            if filled != qty:
                raise OmsError("FILLED requires filled_quantity == command_quantity")
            if not self.applied_event_ids:
                raise OmsError("FILLED requires applied events")
            if reject is not None:
                raise OmsError("FILLED must not set reject_code")
        elif status is OrderStatus.CANCELLING:
            if filled >= qty:
                raise OmsError("CANCELLING requires filled_quantity < command_quantity")
            if not self.applied_event_ids:
                raise OmsError("CANCELLING requires applied events")
            if reject is not None:
                raise OmsError("CANCELLING must not set reject_code")
        elif status is OrderStatus.CANCELLED:
            if filled >= qty:
                raise OmsError("CANCELLED requires filled_quantity < command_quantity")
            if not self.applied_event_ids:
                raise OmsError("CANCELLED requires applied events")
            if reject is not None:
                raise OmsError("CANCELLED must not set reject_code")
        elif status is OrderStatus.REJECTED:
            if filled != 0:
                raise OmsError("REJECTED must not carry fills")
            if reject is None:
                raise OmsError("REJECTED requires reject_code")
            if not self.applied_event_ids:
                raise OmsError("REJECTED requires applied events")
        else:
            raise OmsError(f"unsupported status: {status}")


def new_order_aggregate(command: OrderCommand) -> OrderAggregate:
    """Seed CREATED aggregate bound to a command (pure; no IO)."""
    if not isinstance(command, OrderCommand):
        raise TypeError("new_order_aggregate requires OrderCommand")
    return OrderAggregate(
        command_id=command.command_id,
        status=OrderStatus.CREATED,
        filled_quantity=0,
        broker_order_id=None,
        reject_code=None,
        applied_event_ids=(),
        command_quantity=command.intent.quantity,
        last_event_at=None,
    )


def _reassert_aggregate(aggregate: OrderAggregate) -> None:
    """Re-run aggregate structure/cross-field checks on current field values."""
    aggregate.__post_init__()


def _prove_command_and_event_identity(command: OrderCommand, event: ExecutionEvent) -> None:
    """Recompute D0 identities from current payloads before membership/no-op.

    Maps ordinary contract/attribute failures to a stable OmsError without
    echoing forged fields or chaining the original exception.
    """
    failure: OmsError | None = None
    try:
        build_order_intent_identity(command.intent)
        build_order_command_identity(command)
        build_execution_event_identity(event)
    except ContractError:
        failure = OmsError("input identity rejected")
    except AttributeError:
        failure = OmsError("input identity rejected")
    if failure is not None:
        raise failure from None

def reduce_order(
    aggregate: OrderAggregate,
    command: OrderCommand,
    event: ExecutionEvent,
) -> OrderAggregate:
    """Apply one ExecutionEvent to an OrderAggregate; pure and idempotent.

    Content identity is re-proven before event_id membership. Same verified
    event_id already applied → no-op. Illegal transition / non-monotonic fill /
    terminal rollback → OmsError.
    """
    if not isinstance(aggregate, OrderAggregate):
        raise TypeError("reduce_order requires OrderAggregate")
    if not isinstance(command, OrderCommand):
        raise TypeError("reduce_order requires OrderCommand")
    if not isinstance(event, ExecutionEvent):
        raise TypeError("reduce_order requires ExecutionEvent")

    _reassert_aggregate(aggregate)
    _prove_command_and_event_identity(command, event)

    if aggregate.command_id != command.command_id:
        raise OmsError("command_id mismatch between aggregate and command")
    if aggregate.command_quantity != command.intent.quantity:
        raise OmsError("command_quantity mismatch between aggregate and command")
    if event.command_id != aggregate.command_id:
        raise OmsError("command_id mismatch between event and aggregate")

    if event.event_id in aggregate.applied_event_ids:
        return aggregate

    if event.occurred_at < command.intent.generated_at:
        raise OmsError("event occurred_at before command generated_at")
    if aggregate.last_event_at is not None and event.occurred_at < aggregate.last_event_at:
        raise OmsError("event occurred_at before last_event_at")

    qty = command.intent.quantity
    status = aggregate.status

    if status in _TERMINAL:
        raise OmsError(f"illegal event on terminal status {status.value}")

    if event.event_type is ExecutionEventType.ACCEPTED:
        return _apply_accepted(aggregate, event)
    if event.event_type is ExecutionEventType.REJECTED:
        return _apply_rejected(aggregate, event)
    if event.event_type in _FILL_TYPES:
        return _apply_fill(aggregate, event, command_quantity=qty)
    if event.event_type is ExecutionEventType.CANCEL_ACCEPTED:
        return _apply_cancel_accepted(aggregate, event)
    if event.event_type is ExecutionEventType.CANCELLED:
        return _apply_cancelled(aggregate, event)

    raise OmsError(f"unsupported event_type: {event.event_type}")


def _resolve_broker_order_id(aggregate: OrderAggregate, event: ExecutionEvent) -> str | None:
    """Single-bind broker order id at the central reducer boundary."""
    existing = aggregate.broker_order_id
    incoming = event.broker_order_id
    if existing is None:
        return incoming
    if incoming is None:
        return existing
    if incoming != existing:
        raise OmsError("broker_order_id mismatch with bound aggregate identity")
    return existing


def _with_event(aggregate: OrderAggregate, event: ExecutionEvent, **changes: object) -> OrderAggregate:
    broker = _resolve_broker_order_id(aggregate, event)
    return replace(
        aggregate,
        applied_event_ids=(*aggregate.applied_event_ids, event.event_id),
        last_event_at=event.occurred_at,
        broker_order_id=broker,
        **changes,  # type: ignore[arg-type]
    )


def _apply_accepted(aggregate: OrderAggregate, event: ExecutionEvent) -> OrderAggregate:
    if aggregate.status is not OrderStatus.CREATED:
        raise OmsError("illegal ACCEPTED/NEW after ACK or non-CREATED status")
    if event.cumulative_quantity != 0:
        raise OmsError("ACCEPTED requires cumulative_quantity == 0")
    return _with_event(
        aggregate,
        event,
        status=OrderStatus.SUBMITTED,
    )


def _apply_rejected(aggregate: OrderAggregate, event: ExecutionEvent) -> OrderAggregate:
    if aggregate.status is not OrderStatus.CREATED:
        raise OmsError("illegal REJECTED after non-CREATED status")
    if event.reject_code is None:
        raise OmsError("REJECTED requires reject_code")
    return _with_event(
        aggregate,
        event,
        status=OrderStatus.REJECTED,
        reject_code=event.reject_code,
    )


def _apply_fill(
    aggregate: OrderAggregate,
    event: ExecutionEvent,
    *,
    command_quantity: int,
) -> OrderAggregate:
    if aggregate.status not in (
        OrderStatus.SUBMITTED,
        OrderStatus.PARTIAL_FILLED,
        OrderStatus.CANCELLING,
    ):
        raise OmsError(f"illegal fill from status {aggregate.status.value}")

    prev = aggregate.filled_quantity
    cum = event.cumulative_quantity
    last = event.last_quantity

    if cum > command_quantity:
        raise OmsError("cumulative fill exceeds command quantity")
    if cum <= prev:
        raise OmsError("fill cumulative_quantity must be strictly monotonic")
    if last != cum - prev:
        raise OmsError("last_quantity must equal cumulative delta")

    if event.event_type is ExecutionEventType.PARTIAL_FILL:
        if cum >= command_quantity:
            raise OmsError("PARTIAL_FILL must not reach full command quantity")
        new_status = (
            OrderStatus.CANCELLING
            if aggregate.status is OrderStatus.CANCELLING
            else OrderStatus.PARTIAL_FILLED
        )
    else:
        # FILL
        if cum != command_quantity:
            raise OmsError("FILL must reach full command quantity")
        new_status = OrderStatus.FILLED

    return _with_event(
        aggregate,
        event,
        status=new_status,
        filled_quantity=cum,
    )


def _apply_cancel_accepted(aggregate: OrderAggregate, event: ExecutionEvent) -> OrderAggregate:
    if aggregate.status not in (
        OrderStatus.SUBMITTED,
        OrderStatus.PARTIAL_FILLED,
        OrderStatus.CANCELLING,
    ):
        raise OmsError(f"illegal CANCEL_ACCEPTED from status {aggregate.status.value}")
    if event.cumulative_quantity != aggregate.filled_quantity:
        raise OmsError("CANCEL_ACCEPTED cumulative_quantity must match filled_quantity")
    if aggregate.status is OrderStatus.CANCELLING:
        # Duplicate cancel-accept with new event_id is illegal; same id already no-op.
        raise OmsError("illegal duplicate CANCEL_ACCEPTED while CANCELLING")
    return _with_event(
        aggregate,
        event,
        status=OrderStatus.CANCELLING,
    )


def _apply_cancelled(aggregate: OrderAggregate, event: ExecutionEvent) -> OrderAggregate:
    if aggregate.status not in (
        OrderStatus.SUBMITTED,
        OrderStatus.PARTIAL_FILLED,
        OrderStatus.CANCELLING,
    ):
        raise OmsError(f"illegal CANCELLED from status {aggregate.status.value}")
    if event.cumulative_quantity != aggregate.filled_quantity:
        raise OmsError("CANCELLED cumulative_quantity must match filled_quantity")
    return _with_event(
        aggregate,
        event,
        status=OrderStatus.CANCELLED,
    )


__all__ = [
    "OmsError",
    "OrderAggregate",
    "new_order_aggregate",
    "reduce_order",
]
