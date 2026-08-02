"""Strict canonical persistence wire for immutable B5 ledger objects."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import cast

from quant.backtest.corporate_actions import EntitlementPosition
from quant.backtest.ledger import (
    AppliedAction,
    CommandProjection,
    LedgerEntry,
    LedgerState,
    PendingKind,
    PendingSettlement,
    TradingCreditLot,
)
from quant.domain.canonical_wire import (
    WireError,
    canonical_json_bytes as _canonical,
    raise_wire_error as _fail,
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
from quant.domain.enums import Currency, EntitlementLegState, Market
from quant.execution.contracts import (
    CashBalance,
    PositionBalance,
    build_cash_balance,
    build_money_amount,
    build_position_balance,
)

_ENTRY_SCHEMA = "m4-ledger-entry-v1"
_STATE_SCHEMA = "m4-ledger-state-v1"

__all__ = [
    "decode_ledger_entry",
    "decode_ledger_state",
    "encode_ledger_entry",
    "encode_ledger_state",
]


def _decimal_text(value: Decimal) -> str:
    if type(value) is not Decimal or not value.is_finite():
        _fail()
    return format(value, "f")


def _optional_date_text(value: dt.date | None) -> str | None:
    return None if value is None else value.isoformat()


def _optional_date(value: object) -> dt.date | None:
    return None if value is None else _date(value)


def _signed_integer(value: object) -> int:
    if type(value) is not int:
        _fail()
    return cast(int, value)


def _position_payload(value: PositionBalance) -> dict[str, object]:
    return {
        "avg_cost": {
            "amount": _decimal_text(value.avg_cost.amount),
            "currency": value.avg_cost.currency.value,
        },
        "market": value.market.value,
        "quantity": value.quantity,
        "sellable_quantity": value.sellable_quantity,
        "symbol": value.symbol,
    }


def _cash_payload(value: CashBalance) -> dict[str, object]:
    return {
        "available": _decimal_text(value.available),
        "currency": value.currency.value,
        "payable": _decimal_text(value.payable),
        "receivable": _decimal_text(value.receivable),
        "settled": _decimal_text(value.settled),
    }


def _pending_payload(value: PendingSettlement) -> dict[str, object]:
    return {
        "amount": _decimal_text(value.amount),
        "currency": value.currency.value,
        "due_session": value.due_session.isoformat(),
        "kind": value.kind,
        "market": value.market.value,
        "pending_id": value.pending_id,
        "quantity": value.quantity,
        "source_event_id": value.source_event_id,
        "symbol": value.symbol,
    }


def _credit_payload(value: TradingCreditLot) -> dict[str, object]:
    return {
        "credit_id": value.credit_id,
        "currency": value.currency.value,
        "due_session": value.due_session.isoformat(),
        "original_amount": _decimal_text(value.original_amount),
        "remaining_amount": _decimal_text(value.remaining_amount),
        "source_event_id": value.source_event_id,
    }


def _entitlement_payload(value: EntitlementPosition) -> dict[str, object]:
    return {
        "cash_entitlement_gross": _decimal_text(value.cash_entitlement_gross),
        "cash_per_share_gross": _decimal_text(value.cash_per_share_gross),
        "cash_settlement_session": _optional_date_text(value.cash_settlement_session),
        "cash_state": value.cash_state.value,
        "event_id": value.event_id,
        "ex_date": value.ex_date.isoformat(),
        "pay_date": _optional_date_text(value.pay_date),
        "record_date": value.record_date.isoformat(),
        "record_quantity": value.record_quantity,
        "stock_entitlement": value.stock_entitlement,
        "stock_list_date": _optional_date_text(value.stock_list_date),
        "stock_ratio": _decimal_text(value.stock_ratio),
        "stock_settlement_session": _optional_date_text(value.stock_settlement_session),
        "stock_state": value.stock_state.value,
        "symbol": value.symbol,
    }


def _action_payload(value: AppliedAction) -> dict[str, object]:
    return {"logical_key": value.logical_key, "payload_identity": value.payload_identity}


def _projection_payload(value: CommandProjection) -> dict[str, object]:
    return {
        "broker_order_id": value.broker_order_id,
        "command_id": value.command_id,
        "cumulative_quantity": value.cumulative_quantity,
        "last_event_at": _datetime_text(value.last_event_at),
        "settlement_rule_id": value.settlement_rule_id,
    }


def _entry_payload(value: LedgerEntry) -> dict[str, object]:
    return {
        "available_delta": _decimal_text(value.available_delta),
        "credit_delta": _decimal_text(value.credit_delta),
        "currency": None if value.currency is None else value.currency.value,
        "effective_date": value.effective_date.isoformat(),
        "entry_id": value.entry_id,
        "kind": value.kind,
        "market": None if value.market is None else value.market.value,
        "payable_delta": _decimal_text(value.payable_delta),
        "pending_action": value.pending_action,
        "pending_id": value.pending_id,
        "quantity_delta": value.quantity_delta,
        "receivable_delta": _decimal_text(value.receivable_delta),
        "rounding_delta": _decimal_text(value.rounding_delta),
        "sellable_delta": value.sellable_delta,
        "settled_delta": _decimal_text(value.settled_delta),
        "source_id": value.source_id,
        "source_type": value.source_type,
        "symbol": value.symbol,
    }


def encode_ledger_entry(value: LedgerEntry) -> bytes:
    """Encode a self-proving ledger entry."""
    try:
        LedgerEntry(**{name: getattr(value, name) for name in value.__dataclass_fields__})
        return _canonical({**_entry_payload(value), "schema_version": _ENTRY_SCHEMA})
    except WireError:
        raise
    except Exception:
        pass
    _fail()


def decode_ledger_entry(payload: bytes) -> LedgerEntry:
    """Decode a ledger entry and re-prove its content identity."""
    root = _root(
        payload,
        schema=_ENTRY_SCHEMA,
        keys={
            "available_delta", "credit_delta", "currency", "effective_date", "entry_id",
            "kind", "market", "payable_delta", "pending_action", "pending_id",
            "quantity_delta", "receivable_delta", "rounding_delta", "sellable_delta",
            "settled_delta", "source_id", "source_type", "symbol",
        },
    )
    try:
        entry = LedgerEntry(
            entry_id=cast(str, _string(root["entry_id"])),
            source_type=cast(str, _string(root["source_type"])),
            source_id=cast(str, _string(root["source_id"])),
            kind=cast(str, _string(root["kind"])),
            effective_date=_date(root["effective_date"]),
            currency=None if root["currency"] is None else _enum(Currency, root["currency"]),
            settled_delta=cast(Decimal, _decimal(root["settled_delta"])),
            available_delta=cast(Decimal, _decimal(root["available_delta"])),
            receivable_delta=cast(Decimal, _decimal(root["receivable_delta"])),
            payable_delta=cast(Decimal, _decimal(root["payable_delta"])),
            credit_delta=cast(Decimal, _decimal(root["credit_delta"])),
            market=None if root["market"] is None else _enum(Market, root["market"]),
            symbol=cast(str | None, _string(root["symbol"], optional=True)),
            quantity_delta=_signed_integer(root["quantity_delta"]),
            sellable_delta=_signed_integer(root["sellable_delta"]),
            pending_id=cast(str | None, _string(root["pending_id"], optional=True)),
            pending_action=cast(str | None, _string(root["pending_action"], optional=True)),
            rounding_delta=cast(Decimal, _decimal(root["rounding_delta"])),
        )
        if encode_ledger_entry(entry) != payload:
            _fail()
        return entry
    except WireError:
        raise
    except Exception:
        pass
    _fail()


def _state_payload(value: LedgerState) -> dict[str, object]:
    return {
        "applied_actions": [_action_payload(item) for item in value.applied_actions],
        "applied_event_ids": list(value.applied_event_ids),
        "as_of_date": value.as_of_date.isoformat(),
        "cash": [_cash_payload(item) for item in value.cash],
        "command_projections": [
            _projection_payload(item) for item in value.command_projections
        ],
        "entitlements": [_entitlement_payload(item) for item in value.entitlements],
        "origin_account_snapshot_id": value.origin_account_snapshot_id,
        "pending": [_pending_payload(item) for item in value.pending],
        "positions": [_position_payload(item) for item in value.positions],
        "state_id": value.state_id,
        "trading_credits": [_credit_payload(item) for item in value.trading_credits],
    }


def encode_ledger_state(value: LedgerState) -> bytes:
    """Encode a self-proving ledger checkpoint."""
    try:
        LedgerState(**{name: getattr(value, name) for name in value.__dataclass_fields__})
        return _canonical({**_state_payload(value), "schema_version": _STATE_SCHEMA})
    except WireError:
        raise
    except Exception:
        pass
    _fail()


def _list(value: object) -> list[object]:
    if type(value) is not list:
        _fail()
    return cast(list[object], value)


def _decode_position(value: object) -> PositionBalance:
    raw = _exact(value, {"avg_cost", "market", "quantity", "sellable_quantity", "symbol"})
    avg = _exact(raw["avg_cost"], {"amount", "currency"})
    return build_position_balance(
        symbol=cast(str, _string(raw["symbol"])),
        market=_enum(Market, raw["market"]),
        quantity=_integer(raw["quantity"]),
        sellable_quantity=_integer(raw["sellable_quantity"]),
        avg_cost=build_money_amount(
            _enum(Currency, avg["currency"]), cast(Decimal, _decimal(avg["amount"]))
        ),
    )


def _decode_cash(value: object) -> CashBalance:
    raw = _exact(value, {"available", "currency", "payable", "receivable", "settled"})
    return build_cash_balance(
        currency=_enum(Currency, raw["currency"]),
        settled=cast(Decimal, _decimal(raw["settled"])),
        available=cast(Decimal, _decimal(raw["available"])),
        receivable=cast(Decimal, _decimal(raw["receivable"])),
        payable=cast(Decimal, _decimal(raw["payable"])),
    )


def _decode_pending(value: object) -> PendingSettlement:
    raw = _exact(
        value,
        {
            "amount", "currency", "due_session", "kind", "market", "pending_id",
            "quantity", "source_event_id", "symbol",
        },
    )
    return PendingSettlement(
        pending_id=cast(str, _string(raw["pending_id"])),
        source_event_id=cast(str, _string(raw["source_event_id"])),
        kind=cast(PendingKind, _string(raw["kind"])),
        due_session=_date(raw["due_session"]),
        currency=_enum(Currency, raw["currency"]),
        amount=cast(Decimal, _decimal(raw["amount"])),
        market=_enum(Market, raw["market"]),
        symbol=cast(str, _string(raw["symbol"])),
        quantity=_integer(raw["quantity"]),
    )


def _decode_credit(value: object) -> TradingCreditLot:
    raw = _exact(
        value,
        {
            "credit_id", "currency", "due_session", "original_amount",
            "remaining_amount", "source_event_id",
        },
    )
    return TradingCreditLot(
        credit_id=cast(str, _string(raw["credit_id"])),
        source_event_id=cast(str, _string(raw["source_event_id"])),
        due_session=_date(raw["due_session"]),
        currency=_enum(Currency, raw["currency"]),
        original_amount=cast(Decimal, _decimal(raw["original_amount"])),
        remaining_amount=cast(Decimal, _decimal(raw["remaining_amount"])),
    )


def _decode_entitlement(value: object) -> EntitlementPosition:
    raw = _exact(
        value,
        {
            "cash_entitlement_gross", "cash_per_share_gross", "cash_settlement_session",
            "cash_state", "event_id", "ex_date", "pay_date", "record_date",
            "record_quantity", "stock_entitlement", "stock_list_date", "stock_ratio",
            "stock_settlement_session", "stock_state", "symbol",
        },
    )
    return EntitlementPosition(
        event_id=cast(str, _string(raw["event_id"])),
        symbol=cast(str, _string(raw["symbol"])),
        record_date=_date(raw["record_date"]),
        ex_date=_date(raw["ex_date"]),
        pay_date=_optional_date(raw["pay_date"]),
        stock_list_date=_optional_date(raw["stock_list_date"]),
        cash_settlement_session=_optional_date(raw["cash_settlement_session"]),
        stock_settlement_session=_optional_date(raw["stock_settlement_session"]),
        record_quantity=_integer(raw["record_quantity"], minimum=1),
        cash_per_share_gross=cast(Decimal, _decimal(raw["cash_per_share_gross"])),
        stock_ratio=cast(Decimal, _decimal(raw["stock_ratio"])),
        cash_entitlement_gross=cast(Decimal, _decimal(raw["cash_entitlement_gross"])),
        stock_entitlement=_integer(raw["stock_entitlement"]),
        cash_state=_enum(EntitlementLegState, raw["cash_state"]),
        stock_state=_enum(EntitlementLegState, raw["stock_state"]),
    )


def _decode_action(value: object) -> AppliedAction:
    raw = _exact(value, {"logical_key", "payload_identity"})
    return AppliedAction(
        logical_key=cast(str, _string(raw["logical_key"])),
        payload_identity=cast(str, _string(raw["payload_identity"])),
    )


def _decode_projection(value: object) -> CommandProjection:
    raw = _exact(
        value,
        {
            "broker_order_id", "command_id", "cumulative_quantity", "last_event_at",
            "settlement_rule_id",
        },
    )
    return CommandProjection(
        command_id=cast(str, _string(raw["command_id"])),
        cumulative_quantity=_integer(raw["cumulative_quantity"]),
        broker_order_id=cast(str | None, _string(raw["broker_order_id"], optional=True)),
        last_event_at=_datetime(raw["last_event_at"]),
        settlement_rule_id=cast(str, _string(raw["settlement_rule_id"])),
    )


def decode_ledger_state(payload: bytes) -> LedgerState:
    """Decode a ledger checkpoint and re-prove all nested identities."""
    root = _root(
        payload,
        schema=_STATE_SCHEMA,
        keys={
            "applied_actions", "applied_event_ids", "as_of_date", "cash",
            "command_projections", "entitlements", "origin_account_snapshot_id", "pending",
            "positions", "state_id", "trading_credits",
        },
    )
    try:
        state = LedgerState(
            state_id=cast(str, _string(root["state_id"])),
            origin_account_snapshot_id=cast(str, _string(root["origin_account_snapshot_id"])),
            as_of_date=_date(root["as_of_date"]),
            positions=tuple(_decode_position(item) for item in _list(root["positions"])),
            cash=tuple(_decode_cash(item) for item in _list(root["cash"])),
            pending=tuple(_decode_pending(item) for item in _list(root["pending"])),
            trading_credits=tuple(
                _decode_credit(item) for item in _list(root["trading_credits"])
            ),
            entitlements=tuple(
                _decode_entitlement(item) for item in _list(root["entitlements"])
            ),
            applied_event_ids=tuple(
                cast(str, _string(item)) for item in _list(root["applied_event_ids"])
            ),
            applied_actions=tuple(
                _decode_action(item) for item in _list(root["applied_actions"])
            ),
            command_projections=tuple(
                _decode_projection(item) for item in _list(root["command_projections"])
            ),
        )
        if encode_ledger_state(state) != payload:
            _fail()
        return state
    except WireError:
        raise
    except Exception:
        pass
    _fail()
