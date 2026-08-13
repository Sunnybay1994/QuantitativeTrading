"""Pure contracts at the durable outbox to gateway transport boundary."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from enum import Enum
from typing import Protocol, runtime_checkable

from quant.domain.enums import ExecutionMode
from quant.execution.contracts import (
    CancelCommand,
    ExecutionEvent,
    OrderCommand,
    build_cancel_command_identity,
    build_execution_event_identity,
    build_order_command_identity,
    build_order_intent_identity,
)

_HEX64 = frozenset("0123456789abcdef")


class GatewayContractError(ValueError):
    """Stable, sanitized violation of the gateway transport contract."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class DispatchCertainty(str, Enum):
    """Whether a submit request crossed the gateway adapter boundary."""

    NOT_SENT = "NOT_SENT"
    SENT = "SENT"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class GatewayDispatchResult:
    """Immutable adapter observation fenced by one durable delivery attempt."""

    command_id: str
    dispatch_attempt: int
    certainty: DispatchCertainty
    callbacks: tuple[ExecutionEvent, ...]

    def __post_init__(self) -> None:
        if not _is_hex64(self.command_id):
            raise GatewayContractError("GATEWAY_RESULT_INVALID")
        if not _is_positive_int(self.dispatch_attempt):
            raise GatewayContractError("GATEWAY_ATTEMPT_INVALID")
        if not isinstance(self.certainty, DispatchCertainty):
            raise GatewayContractError("GATEWAY_RESULT_INVALID")
        if type(self.callbacks) is not tuple or any(
            not isinstance(item, ExecutionEvent) for item in self.callbacks
        ):
            raise GatewayContractError("GATEWAY_RESULT_INVALID")
        if self.certainty is not DispatchCertainty.SENT and self.callbacks:
            raise GatewayContractError("GATEWAY_CALLBACKS_FORBIDDEN")


@dataclass(frozen=True, slots=True)
class GatewayCancelResult:
    """One fenced cancel dispatch observation; UNKNOWN is terminal for automation."""

    cancel_id: str
    dispatch_attempt: int
    certainty: DispatchCertainty
    callbacks: tuple[ExecutionEvent, ...]

    def __post_init__(self) -> None:
        if not _is_hex64(self.cancel_id):
            raise GatewayContractError("GATEWAY_CANCEL_RESULT_INVALID")
        if not _is_positive_int(self.dispatch_attempt):
            raise GatewayContractError("GATEWAY_CANCEL_ATTEMPT_INVALID")
        if not isinstance(self.certainty, DispatchCertainty):
            raise GatewayContractError("GATEWAY_CANCEL_RESULT_INVALID")
        if type(self.callbacks) is not tuple or any(
            not isinstance(item, ExecutionEvent) for item in self.callbacks
        ):
            raise GatewayContractError("GATEWAY_CANCEL_RESULT_INVALID")
        if self.certainty is not DispatchCertainty.SENT and self.callbacks:
            raise GatewayContractError("GATEWAY_CANCEL_CALLBACKS_FORBIDDEN")


@runtime_checkable
class GatewayTransport(Protocol):
    """Narrow transport implemented by future PAPER gateway adapters."""

    def submit(
        self,
        *,
        command: OrderCommand,
        dispatch_attempt: int,
        now: dt.datetime,
    ) -> GatewayDispatchResult:
        """Submit one command under a fenced delivery attempt."""
        ...


@runtime_checkable
class GatewayCancelTransport(Protocol):
    """Narrow PAPER cancel transport; retry policy remains above the adapter."""

    def cancel(
        self,
        *,
        command: CancelCommand,
        dispatch_attempt: int,
        now: dt.datetime,
    ) -> GatewayCancelResult:
        """Dispatch one durable cancel under a fenced delivery attempt."""
        ...


def validate_gateway_submit(
    command: OrderCommand,
    dispatch_attempt: int,
    now: dt.datetime,
) -> None:
    """Fail closed before an adapter is called."""
    if not isinstance(command, OrderCommand):
        raise GatewayContractError("GATEWAY_COMMAND_INVALID")
    identity_invalid = False
    try:
        build_order_intent_identity(command.intent)
        build_order_command_identity(command)
    except Exception:
        identity_invalid = True
    if identity_invalid:
        raise GatewayContractError("GATEWAY_COMMAND_INVALID")
    if command.mode is not ExecutionMode.PAPER:
        raise GatewayContractError("GATEWAY_MODE_UNSUPPORTED")
    if not _is_positive_int(dispatch_attempt):
        raise GatewayContractError("GATEWAY_ATTEMPT_INVALID")
    if not _is_utc(now):
        raise GatewayContractError("GATEWAY_TIME_INVALID")


def validate_gateway_cancel(
    command: CancelCommand,
    dispatch_attempt: int,
    now: dt.datetime,
) -> None:
    """Fail closed before dispatching a durable PAPER cancel."""
    if not isinstance(command, CancelCommand):
        raise GatewayContractError("GATEWAY_CANCEL_COMMAND_INVALID")
    identity_invalid = False
    try:
        build_cancel_command_identity(command)
    except Exception:
        identity_invalid = True
    if identity_invalid:
        raise GatewayContractError("GATEWAY_CANCEL_COMMAND_INVALID")
    if command.mode is not ExecutionMode.PAPER:
        raise GatewayContractError("GATEWAY_MODE_UNSUPPORTED")
    if not _is_positive_int(dispatch_attempt):
        raise GatewayContractError("GATEWAY_CANCEL_ATTEMPT_INVALID")
    if not _is_utc(now) or now < command.as_of:
        raise GatewayContractError("GATEWAY_CANCEL_TIME_INVALID")


def verify_gateway_dispatch_result(
    command: OrderCommand,
    dispatch_attempt: int,
    observed_at: dt.datetime,
    result: GatewayDispatchResult,
) -> GatewayDispatchResult:
    """Verify attempt fencing, certainty and callback identity closure."""
    validate_gateway_submit(command, dispatch_attempt, observed_at)
    if not isinstance(result, GatewayDispatchResult):
        raise GatewayContractError("GATEWAY_RESULT_INVALID")
    if not _is_hex64(result.command_id) or not isinstance(
        result.certainty, DispatchCertainty
    ):
        raise GatewayContractError("GATEWAY_RESULT_INVALID")
    if type(result.callbacks) is not tuple or any(
        not isinstance(item, ExecutionEvent) for item in result.callbacks
    ):
        raise GatewayContractError("GATEWAY_RESULT_INVALID")
    if result.command_id != command.command_id:
        raise GatewayContractError("GATEWAY_RESULT_COMMAND_MISMATCH")
    if not _is_positive_int(result.dispatch_attempt):
        raise GatewayContractError("GATEWAY_ATTEMPT_INVALID")
    if result.dispatch_attempt != dispatch_attempt:
        raise GatewayContractError("GATEWAY_RESULT_ATTEMPT_MISMATCH")
    if result.certainty is not DispatchCertainty.SENT and result.callbacks:
        raise GatewayContractError("GATEWAY_CALLBACKS_FORBIDDEN")

    callbacks_by_id: dict[str, ExecutionEvent] = {}
    for event in result.callbacks:
        if event.command_id != command.command_id:
            raise GatewayContractError("GATEWAY_CALLBACK_COMMAND_MISMATCH")
        if not _is_utc(event.occurred_at) or event.occurred_at > observed_at:
            raise GatewayContractError("GATEWAY_CALLBACK_TIME_INVALID")
        identity_invalid = False
        try:
            build_execution_event_identity(event)
        except Exception:
            identity_invalid = True
        if identity_invalid:
            raise GatewayContractError("GATEWAY_CALLBACK_INVALID")
        previous = callbacks_by_id.get(event.event_id)
        if previous is not None and previous != event:
            raise GatewayContractError("GATEWAY_CALLBACK_CONFLICT")
        callbacks_by_id[event.event_id] = event
    return result


def verify_gateway_cancel_result(
    order_command: OrderCommand,
    cancel_command: CancelCommand,
    aggregate: object,
    dispatch_attempt: int,
    observed_at: dt.datetime,
    result: GatewayCancelResult,
) -> GatewayCancelResult:
    """Prove ordered cancel callbacks are consumable from the frozen OMS snapshot."""
    validate_gateway_cancel(cancel_command, dispatch_attempt, observed_at)

    source_invalid = False
    try:
        build_order_intent_identity(order_command.intent)
        build_order_command_identity(order_command)
    except Exception:
        source_invalid = True
    if source_invalid:
        raise GatewayContractError("GATEWAY_CANCEL_SOURCE_COMMAND_INVALID")
    if order_command.mode is not ExecutionMode.PAPER:
        raise GatewayContractError("GATEWAY_MODE_UNSUPPORTED")
    if order_command.command_id != cancel_command.command_id:
        raise GatewayContractError("GATEWAY_CANCEL_SOURCE_COMMAND_MISMATCH")

    from quant.domain.enums import ExecutionEventType, OrderStatus
    from quant.execution.oms import OrderAggregate, reduce_order

    snapshot_invalid = False
    snapshot: OrderAggregate | None = None
    if isinstance(aggregate, OrderAggregate):
        try:
            snapshot = OrderAggregate(
                command_id=aggregate.command_id,
                status=aggregate.status,
                filled_quantity=aggregate.filled_quantity,
                broker_order_id=aggregate.broker_order_id,
                reject_code=aggregate.reject_code,
                applied_event_ids=aggregate.applied_event_ids,
                command_quantity=aggregate.command_quantity,
                last_event_at=aggregate.last_event_at,
            )
        except Exception:
            snapshot_invalid = True
    else:
        snapshot_invalid = True
    if snapshot_invalid or snapshot is None:
        raise GatewayContractError("GATEWAY_CANCEL_SNAPSHOT_INVALID")
    if (
        snapshot.command_id != order_command.command_id
        or snapshot.command_quantity != order_command.intent.quantity
        or snapshot.broker_order_id != cancel_command.broker_order_id
        or snapshot.status is not cancel_command.aggregate_status
        or snapshot.status not in (OrderStatus.SUBMITTED, OrderStatus.PARTIAL_FILLED)
        or snapshot.filled_quantity != cancel_command.observed_filled_quantity
        or snapshot.applied_event_ids != cancel_command.observed_event_ids
        or snapshot.last_event_at != cancel_command.observed_last_event_at
    ):
        raise GatewayContractError("GATEWAY_CANCEL_SNAPSHOT_MISMATCH")

    if not isinstance(result, GatewayCancelResult):
        raise GatewayContractError("GATEWAY_CANCEL_RESULT_INVALID")
    if not _is_hex64(result.cancel_id) or not isinstance(result.certainty, DispatchCertainty):
        raise GatewayContractError("GATEWAY_CANCEL_RESULT_INVALID")
    if type(result.callbacks) is not tuple or any(
        not isinstance(item, ExecutionEvent) for item in result.callbacks
    ):
        raise GatewayContractError("GATEWAY_CANCEL_RESULT_INVALID")
    if result.cancel_id != cancel_command.cancel_id:
        raise GatewayContractError("GATEWAY_CANCEL_RESULT_COMMAND_MISMATCH")
    if not _is_positive_int(result.dispatch_attempt):
        raise GatewayContractError("GATEWAY_CANCEL_ATTEMPT_INVALID")
    if result.dispatch_attempt != dispatch_attempt:
        raise GatewayContractError("GATEWAY_CANCEL_RESULT_ATTEMPT_MISMATCH")
    if result.certainty is not DispatchCertainty.SENT and result.callbacks:
        raise GatewayContractError("GATEWAY_CANCEL_CALLBACKS_FORBIDDEN")

    callbacks_by_id: dict[str, ExecutionEvent] = {}
    projected = snapshot
    allowed = frozenset(
        {
            ExecutionEventType.CANCEL_ACCEPTED,
            ExecutionEventType.CANCELLED,
            ExecutionEventType.PARTIAL_FILL,
            ExecutionEventType.FILL,
        }
    )
    for event in result.callbacks:
        identity_invalid = False
        try:
            build_execution_event_identity(event)
        except Exception:
            identity_invalid = True
        if identity_invalid:
            raise GatewayContractError("GATEWAY_CANCEL_CALLBACK_INVALID")
        previous = callbacks_by_id.get(event.event_id)
        if previous is not None and previous != event:
            raise GatewayContractError("GATEWAY_CANCEL_CALLBACK_CONFLICT")
        callbacks_by_id[event.event_id] = event
        if event.event_type not in allowed:
            raise GatewayContractError("GATEWAY_CANCEL_CALLBACK_TYPE_INVALID")
        if event.command_id != cancel_command.command_id:
            raise GatewayContractError("GATEWAY_CANCEL_CALLBACK_COMMAND_MISMATCH")
        if event.broker_order_id != cancel_command.broker_order_id:
            raise GatewayContractError("GATEWAY_CANCEL_CALLBACK_BROKER_MISMATCH")
        if (
            not _is_utc(event.occurred_at)
            or event.occurred_at < cancel_command.as_of
            or event.occurred_at > observed_at
        ):
            raise GatewayContractError("GATEWAY_CANCEL_CALLBACK_TIME_INVALID")
        reducer_invalid = False
        try:
            projected = reduce_order(projected, order_command, event)
        except Exception:
            reducer_invalid = True
        if reducer_invalid:
            raise GatewayContractError("GATEWAY_CANCEL_CALLBACK_SEQUENCE_INVALID")
    return result


def _is_positive_int(value: object) -> bool:
    return type(value) is int and value > 0


def _is_hex64(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(character in _HEX64 for character in value)
    )


def _is_utc(value: object) -> bool:
    if type(value) is not dt.datetime or value.tzinfo is None:
        return False
    offset_failed = False
    offset: dt.timedelta | None = None
    try:
        offset = value.utcoffset()
    except Exception:
        offset_failed = True
    return not offset_failed and offset == dt.timedelta(0)


__all__ = [
    "DispatchCertainty",
    "GatewayContractError",
    "GatewayCancelResult",
    "GatewayCancelTransport",
    "GatewayDispatchResult",
    "GatewayTransport",
    "validate_gateway_submit",
    "validate_gateway_cancel",
    "verify_gateway_dispatch_result",
    "verify_gateway_cancel_result",
]
