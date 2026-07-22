"""Pure contracts at the durable outbox to gateway transport boundary."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from enum import Enum
from typing import Protocol, runtime_checkable

from quant.domain.enums import ExecutionMode
from quant.execution.contracts import (
    ExecutionEvent,
    OrderCommand,
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
    "GatewayDispatchResult",
    "GatewayTransport",
    "validate_gateway_submit",
    "verify_gateway_dispatch_result",
]
