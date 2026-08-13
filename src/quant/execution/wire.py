"""Strict canonical wire formats shared by execution persistence consumers."""

from __future__ import annotations

from decimal import Decimal
from typing import cast

from quant.domain.canonical_wire import (
    WireError,
    canonical_json_bytes as _canonical,
    raise_wire_error as _fail,
    require_boolean as _boolean,
    require_date as _date,
    require_decimal as _decimal,
    require_enum as _enum,
    require_exact_object as _exact,
    require_integer as _integer,
    require_string as _string,
    require_utc_datetime as _datetime,
    require_wire_root as _root,
    utc_datetime_text as _datetime_text,
)

from quant.domain.enums import (
    ConnectRoute,
    Currency,
    ExecutionEventType,
    ExecutionMode,
    Market,
    OrderSide,
    OrderStatus,
    OrderType,
    TimeInForce,
)
from quant.execution.contracts import (
    CancelCommand,
    ExecutionEvent,
    OrderCommand,
    OrderIntent,
    build_cancel_command_identity,
    build_execution_event,
    build_execution_event_identity,
    build_fee_component,
    build_money_amount,
    build_order_command,
    build_order_command_identity,
    build_order_intent,
)
from quant.execution.oms import OrderAggregate

_COMMAND_SCHEMA = "m4-order-command-v1"
_EVENT_SCHEMA = "m4-execution-event-v1"
_AGGREGATE_SCHEMA = "m4-order-aggregate-v1"
_CANCEL_SCHEMA = "m4-cancel-command-v1"

__all__ = [
    "WireError",
    "decode_cancel_command",
    "decode_execution_event",
    "decode_order_aggregate",
    "decode_order_command",
    "encode_cancel_command",
    "encode_execution_event",
    "encode_order_aggregate",
    "encode_order_command",
]


def encode_cancel_command(value: CancelCommand) -> bytes:
    """Encode one self-proving PAPER cancel request."""
    try:
        build_cancel_command_identity(value)
        return _canonical(
            {
                "aggregate_status": value.aggregate_status.value,
                "as_of": _datetime_text(value.as_of),
                "broker_order_id": value.broker_order_id,
                "cancel_id": value.cancel_id,
                "command_id": value.command_id,
                "mode": value.mode.value,
                "observed_event_ids": list(value.observed_event_ids),
                "observed_filled_quantity": value.observed_filled_quantity,
                "observed_last_event_at": _datetime_text(value.observed_last_event_at),
                "schema_version": _CANCEL_SCHEMA,
            }
        )
    except WireError:
        raise
    except Exception:
        pass
    _fail()


def decode_cancel_command(payload: bytes) -> CancelCommand:
    """Decode and re-prove a canonical PAPER cancel request."""
    root = _root(
        payload,
        schema=_CANCEL_SCHEMA,
        keys={
            "aggregate_status",
            "as_of",
            "broker_order_id",
            "cancel_id",
            "command_id",
            "mode",
            "observed_event_ids",
            "observed_filled_quantity",
            "observed_last_event_at",
        },
    )
    event_ids = root["observed_event_ids"]
    if type(event_ids) is not list:
        _fail()
    try:
        cancel = CancelCommand(
            cancel_id=cast(str, _string(root["cancel_id"])),
            command_id=cast(str, _string(root["command_id"])),
            broker_order_id=cast(str, _string(root["broker_order_id"])),
            mode=_enum(ExecutionMode, root["mode"]),
            aggregate_status=_enum(OrderStatus, root["aggregate_status"]),
            observed_filled_quantity=_integer(
                root["observed_filled_quantity"], minimum=0
            ),
            observed_event_ids=tuple(
                cast(str, _string(item)) for item in cast(list[object], event_ids)
            ),
            observed_last_event_at=_datetime(root["observed_last_event_at"]),
            as_of=_datetime(root["as_of"]),
        )
        if cancel.cancel_id != _string(root["cancel_id"]) or encode_cancel_command(cancel) != payload:
            _fail()
        return cancel
    except WireError:
        raise
    except Exception:
        pass
    _fail()


def _intent_payload(intent: OrderIntent) -> dict[str, object]:
    return {
        "account_snapshot_id": intent.account_snapshot_id,
        "config_identity": intent.config_identity,
        "connect_route": None if intent.connect_route is None else intent.connect_route.value,
        "generated_at": _datetime_text(intent.generated_at),
        "intent_id": intent.intent_id,
        "limit_price": format(intent.limit_price, "f"),
        "market": intent.market.value,
        "market_snapshot_id": intent.market_snapshot_id,
        "plan_id": intent.plan_id,
        "quantity": intent.quantity,
        "quote_currency": intent.quote_currency.value,
        "session_date": intent.session_date.isoformat(),
        "side": intent.side.value,
        "symbol": intent.symbol,
        "target_identity": intent.target_identity,
    }


def encode_order_command(value: OrderCommand) -> bytes:
    """Encode a self-proving command using the frozen P4 byte format."""
    try:
        build_order_command_identity(value)
        return _canonical(
            {
                "command_id": value.command_id,
                "intent": _intent_payload(value.intent),
                "mode": value.mode.value,
                "order_type": value.order_type.value,
                "schema_version": _COMMAND_SCHEMA,
                "time_in_force": value.time_in_force.value,
            }
        )
    except WireError:
        raise
    except Exception:
        pass
    _fail()


def decode_order_command(payload: bytes) -> OrderCommand:
    """Decode and re-prove a canonical command."""
    root = _root(
        payload,
        schema=_COMMAND_SCHEMA,
        keys={"command_id", "intent", "mode", "order_type", "time_in_force"},
    )
    raw = _exact(
        root["intent"],
        {
            "account_snapshot_id", "config_identity", "connect_route", "generated_at",
            "intent_id", "limit_price", "market", "market_snapshot_id", "plan_id",
            "quantity", "quote_currency", "session_date", "side", "symbol",
            "target_identity",
        },
    )
    try:
        route_raw = raw["connect_route"]
        route = None if route_raw is None else _enum(ConnectRoute, route_raw)
        intent = build_order_intent(
            plan_id=cast(str, _string(raw["plan_id"])),
            symbol=cast(str, _string(raw["symbol"])),
            market=_enum(Market, raw["market"]),
            side=_enum(OrderSide, raw["side"]),
            quantity=_integer(raw["quantity"], minimum=1),
            limit_price=cast(Decimal, _decimal(raw["limit_price"])),
            quote_currency=_enum(Currency, raw["quote_currency"]),
            session_date=_date(raw["session_date"]),
            generated_at=_datetime(raw["generated_at"]),
            target_identity=cast(str, _string(raw["target_identity"])),
            market_snapshot_id=cast(str, _string(raw["market_snapshot_id"])),
            account_snapshot_id=cast(str, _string(raw["account_snapshot_id"])),
            config_identity=cast(str, _string(raw["config_identity"])),
            connect_route=route,
        )
        if intent.intent_id != _string(raw["intent_id"]):
            _fail()
        command = build_order_command(
            intent=intent,
            mode=_enum(ExecutionMode, root["mode"]),
            order_type=_enum(OrderType, root["order_type"]),
            time_in_force=_enum(TimeInForce, root["time_in_force"]),
        )
        if command.command_id != _string(root["command_id"]) or encode_order_command(command) != payload:
            _fail()
        return command
    except WireError:
        raise
    except Exception:
        pass
    _fail()


def encode_execution_event(value: ExecutionEvent) -> bytes:
    """Encode a self-proving event using the frozen P4 byte format."""
    try:
        build_execution_event_identity(value)
        return _canonical(
            {
                "broker_order_id": value.broker_order_id,
                "command_id": value.command_id,
                "cumulative_quantity": value.cumulative_quantity,
                "event_id": value.event_id,
                "event_type": value.event_type.value,
                "fees": [
                    {
                        "amount": {
                            "amount": format(fee.amount.amount, "f"),
                            "currency": fee.amount.currency.value,
                        },
                        "code": fee.code,
                        "rule_version": fee.rule_version,
                        "statutory": fee.statutory,
                    }
                    for fee in value.fees
                ],
                "last_price": None if value.last_price is None else format(value.last_price, "f"),
                "last_quantity": value.last_quantity,
                "occurred_at": _datetime_text(value.occurred_at),
                "reject_code": value.reject_code,
                "schema_version": _EVENT_SCHEMA,
            }
        )
    except WireError:
        raise
    except Exception:
        pass
    _fail()


def decode_execution_event(payload: bytes, *, command: OrderCommand) -> ExecutionEvent:
    """Decode an event and prove its command and content identity closure."""
    command_is_valid = False
    try:
        build_order_command_identity(command)
    except Exception:
        pass
    else:
        command_is_valid = True
    if not command_is_valid:
        _fail()
    root = _root(
        payload,
        schema=_EVENT_SCHEMA,
        keys={
            "broker_order_id", "command_id", "cumulative_quantity", "event_id",
            "event_type", "fees", "last_price", "last_quantity", "occurred_at",
            "reject_code",
        },
    )
    fees_raw = root["fees"]
    if type(fees_raw) is not list:
        _fail()
    try:
        fees = []
        for item in cast(list[object], fees_raw):
            fee = _exact(item, {"amount", "code", "rule_version", "statutory"})
            amount = _exact(fee["amount"], {"amount", "currency"})
            fees.append(
                build_fee_component(
                    code=cast(str, _string(fee["code"])),
                    amount=build_money_amount(
                        _enum(Currency, amount["currency"]),
                        cast(Decimal, _decimal(amount["amount"])),
                    ),
                    statutory=_boolean(fee["statutory"]),
                    rule_version=cast(str, _string(fee["rule_version"])),
                )
            )
        if root["command_id"] != command.command_id:
            _fail()
        event = build_execution_event(
            command=command,
            broker_order_id=cast(str | None, _string(root["broker_order_id"], optional=True)),
            event_type=_enum(ExecutionEventType, root["event_type"]),
            occurred_at=_datetime(root["occurred_at"]),
            cumulative_quantity=_integer(root["cumulative_quantity"]),
            last_quantity=_integer(root["last_quantity"]),
            last_price=cast(Decimal | None, _decimal(root["last_price"], optional=True)),
            fees=tuple(fees),
            reject_code=cast(str | None, _string(root["reject_code"], optional=True)),
        )
        if event.event_id != _string(root["event_id"]) or encode_execution_event(event) != payload:
            _fail()
        return event
    except WireError:
        raise
    except Exception:
        pass
    _fail()


def encode_order_aggregate(value: OrderAggregate) -> bytes:
    """Encode an OMS aggregate using the frozen P4 byte format."""
    try:
        return _canonical(
            {
                "applied_event_ids": list(value.applied_event_ids),
                "broker_order_id": value.broker_order_id,
                "command_id": value.command_id,
                "command_quantity": value.command_quantity,
                "filled_quantity": value.filled_quantity,
                "last_event_at": (
                    None if value.last_event_at is None else _datetime_text(value.last_event_at)
                ),
                "reject_code": value.reject_code,
                "schema_version": _AGGREGATE_SCHEMA,
                "status": value.status.value,
            }
        )
    except WireError:
        raise
    except Exception:
        pass
    _fail()


def decode_order_aggregate(payload: bytes, *, command: OrderCommand) -> OrderAggregate:
    """Decode an aggregate and prove its command quantity closure."""
    command_is_valid = False
    try:
        build_order_command_identity(command)
    except Exception:
        pass
    else:
        command_is_valid = True
    if not command_is_valid:
        _fail()
    root = _root(
        payload,
        schema=_AGGREGATE_SCHEMA,
        keys={
            "applied_event_ids", "broker_order_id", "command_id", "command_quantity",
            "filled_quantity", "last_event_at", "reject_code", "status",
        },
    )
    event_ids = root["applied_event_ids"]
    if type(event_ids) is not list:
        _fail()
    try:
        aggregate = OrderAggregate(
            command_id=cast(str, _string(root["command_id"])),
            status=_enum(OrderStatus, root["status"]),
            filled_quantity=_integer(root["filled_quantity"]),
            broker_order_id=cast(str | None, _string(root["broker_order_id"], optional=True)),
            reject_code=cast(str | None, _string(root["reject_code"], optional=True)),
            applied_event_ids=tuple(
                cast(str, _string(item)) for item in cast(list[object], event_ids)
            ),
            command_quantity=_integer(root["command_quantity"], minimum=1),
            last_event_at=(
                None if root["last_event_at"] is None else _datetime(root["last_event_at"])
            ),
        )
        if (
            aggregate.command_id != command.command_id
            or aggregate.command_quantity != command.intent.quantity
            or encode_order_aggregate(aggregate) != payload
        ):
            _fail()
        return aggregate
    except WireError:
        raise
    except Exception:
        pass
    _fail()
    build_cancel_command_identity,
    "encode_cancel_command",
