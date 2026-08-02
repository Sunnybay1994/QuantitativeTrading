"""M4-D0 immutable OMS/ledger domain value objects and canonical identities.

Based on pending-main-acceptance M4-C0 trading-config identity conventions.
Does not implement LIVE, store, or engine.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Any, Literal, TypeAlias

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

_HASH_VERSION = "execution-contract-hash-v1"
_HEX64 = frozenset("0123456789abcdef")
_FILL_EVENTS = frozenset({ExecutionEventType.PARTIAL_FILL, ExecutionEventType.FILL})
_NON_FILL_EVENTS = frozenset(
    {
        ExecutionEventType.ACCEPTED,
        ExecutionEventType.CANCEL_ACCEPTED,
        ExecutionEventType.CANCELLED,
        ExecutionEventType.REJECTED,
    }
)


class ContractError(ValueError):
    """Strict domain contract violation (fail closed)."""


def _require_non_empty_str(name: str, value: object) -> str:
    if type(value) is not str or not value:
        raise ContractError(f"{name} must be a non-empty str")
    return value


def _require_hex64(name: str, value: object) -> str:
    if type(value) is not str or len(value) != 64 or any(char not in _HEX64 for char in value):
        raise ContractError(f"{name} must be bare 64-char lowercase hex")
    return value


def _require_utc_datetime(name: str, value: object) -> dt.datetime:
    if type(value) is not dt.datetime:
        raise ContractError(f"{name} must be datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ContractError(f"{name} must be timezone-aware UTC")
    if value.utcoffset() != dt.timedelta(0):
        raise ContractError(f"{name} must be timezone-aware UTC")
    return value


def _require_cancel_utc_datetime(name: str, value: object) -> dt.datetime:
    """Cancel-boundary UTC validator that hides hostile tzinfo failures."""
    invalid = False
    checked: dt.datetime | None = None
    try:
        checked = _require_utc_datetime(name, value)
    except Exception:
        invalid = True
    if invalid or checked is None:
        raise ContractError(f"{name} must be timezone-aware UTC")
    return checked


def _require_date(name: str, value: object) -> dt.date:
    if type(value) is not dt.date or isinstance(value, dt.datetime):
        raise ContractError(f"{name} must be date")
    return value


def _require_bool(name: str, value: object) -> bool:
    if type(value) is not bool:
        raise ContractError(f"{name} must be bool")
    return value


def _require_int(name: str, value: object, *, minimum: int | None = None) -> int:
    if type(value) is not int or isinstance(value, bool):
        raise ContractError(f"{name} must be int")
    if minimum is not None and value < minimum:
        raise ContractError(f"{name} must be >= {minimum}")
    return value


def _require_finite_decimal(name: str, value: object) -> Decimal:
    if type(value) is not Decimal:
        raise ContractError(f"{name} must be Decimal")
    if not value.is_finite():
        raise ContractError(f"{name} must be finite Decimal")
    return value


def _require_positive_decimal(name: str, value: object) -> Decimal:
    amount = _require_finite_decimal(name, value)
    if amount <= 0:
        raise ContractError(f"{name} must be positive")
    return amount


def _require_non_negative_decimal(name: str, value: object) -> Decimal:
    amount = _require_finite_decimal(name, value)
    if amount < 0:
        raise ContractError(f"{name} must be non-negative")
    return amount


def _require_enum(name: str, value: object, enum_cls: type[Enum]) -> Any:
    if not isinstance(value, enum_cls):
        raise ContractError(f"{name} must be {enum_cls.__name__}")
    return value


def _quote_currency_for_market(market: Market) -> Currency:
    if market is Market.HK:
        return Currency.HKD
    return Currency.CNY


def _json_value(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): _json_value(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(child) for child in value]
    if isinstance(value, Enum):
        return value.value
    if type(value) is Decimal:
        return format(value, "f")
    if type(value) is dt.datetime:
        return value.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")
    if type(value) is dt.date:
        return value.isoformat()
    if type(value) is bool or value is None or type(value) is int or type(value) is str:
        return value
    raise ContractError(f"unsupported identity payload type: {type(value)!r}")


def _sha256_envelope(*, type_name: str, payload: dict[str, object]) -> str:
    envelope = {
        "hash_version": _HASH_VERSION,
        "type": type_name,
        "payload": payload,
    }
    encoded = json.dumps(
        _json_value(envelope),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _reject_forged_identity(name: str, actual: str, expected: str) -> None:
    if actual != expected:
        raise ContractError(f"caller-supplied {name} identity/hash rejected")


def _money_payload(money: "MoneyAmount") -> dict[str, object]:
    return {"currency": money.currency, "amount": money.amount}


def _fee_payload(fee: "FeeComponent") -> dict[str, object]:
    return {
        "code": fee.code,
        "amount": _money_payload(fee.amount),
        "statutory": fee.statutory,
        "rule_version": fee.rule_version,
    }


def _position_payload(position: "PositionBalance") -> dict[str, object]:
    return {
        "symbol": position.symbol,
        "market": position.market,
        "quantity": position.quantity,
        "sellable_quantity": position.sellable_quantity,
        "avg_cost": _money_payload(position.avg_cost),
    }


def _cash_payload(cash: "CashBalance") -> dict[str, object]:
    return {
        "currency": cash.currency,
        "settled": cash.settled,
        "available": cash.available,
        "receivable": cash.receivable,
        "payable": cash.payable,
    }


def _state_payload(state: "SymbolMarketState") -> dict[str, object]:
    return {
        "symbol": state.symbol,
        "market": state.market,
        "session_date": state.session_date,
        "quote_currency": state.quote_currency,
        "reference_price": state.reference_price,
        "limit_up": state.limit_up,
        "limit_down": state.limit_down,
        "suspended": state.suspended,
        "board_lot": state.board_lot,
        "tick_size": state.tick_size,
        "rule_version": state.rule_version,
    }


def _connect_context_payload(context: "VerifiedConnectMarketContext") -> dict[str, object]:
    return {
        "context_id": context.context_id,
        "route": context.route,
        "session_date": context.session_date,
        "as_of": context.as_of,
        "mainland_open": context.mainland_open,
        "hong_kong_open": context.hong_kong_open,
        "buy_quota_available": context.buy_quota_available,
        "calendar_identity": context.calendar_identity,
        "quota_identity": context.quota_identity,
        "source_identity": context.source_identity,
    }


def _intent_body_payload(
    *,
    symbol: str,
    market: Market,
    side: OrderSide,
    quantity: int,
    limit_price: Decimal,
    quote_currency: Currency,
    session_date: dt.date,
    generated_at: dt.datetime,
    target_identity: str,
    market_snapshot_id: str,
    account_snapshot_id: str,
    config_identity: str,
    connect_route: ConnectRoute | None,
) -> dict[str, object]:
    return {
        "symbol": symbol,
        "market": market,
        "side": side,
        "quantity": quantity,
        "limit_price": limit_price,
        "quote_currency": quote_currency,
        "session_date": session_date,
        "generated_at": generated_at,
        "target_identity": target_identity,
        "market_snapshot_id": market_snapshot_id,
        "account_snapshot_id": account_snapshot_id,
        "config_identity": config_identity,
        "connect_route": connect_route,
    }


def _rule_decision_payload(decision: "RuleDecision") -> dict[str, object]:
    return {
        "accepted": decision.accepted,
        "code": decision.code,
        "normalized_quantity": decision.normalized_quantity,
        "normalized_limit_price": decision.normalized_limit_price,
        "rule_version": decision.rule_version,
    }


def _order_plan_decision_target_digest(
    *,
    symbol: str,
    market: Market,
    connect_route: ConnectRoute | None,
) -> str:
    return _sha256_envelope(
        type_name="OrderPlanDecisionTarget",
        payload={
            "symbol": symbol,
            "market": market,
            "connect_route": connect_route,
        },
    )


def _order_plan_decision_payload(
    decision: "OrderPlanDecision",
) -> dict[str, object]:
    return {
        "target_key": decision.target_key,
        "symbol": decision.symbol,
        "market": decision.market,
        "connect_route": decision.connect_route,
        "side": decision.side,
        "requested_quantity": decision.requested_quantity,
        "accepted_quantity": decision.accepted_quantity,
        "rejected_quantity": decision.rejected_quantity,
        "zero_delta_quantity": decision.zero_delta_quantity,
        "outcome": _rule_decision_payload(decision.outcome),
        "reason_class": decision.reason_class,
    }


@dataclass(frozen=True, slots=True)
class MoneyAmount:
    """Currency-tagged finite Decimal amount."""

    currency: Currency
    amount: Decimal

    def __post_init__(self) -> None:
        _require_enum("currency", self.currency, Currency)
        _require_finite_decimal("amount", self.amount)

    def __add__(self, other: object) -> MoneyAmount:
        if not isinstance(other, MoneyAmount):
            return NotImplemented
        if self.currency is not other.currency:
            raise ContractError("cross-currency MoneyAmount addition is forbidden")
        return MoneyAmount(currency=self.currency, amount=self.amount + other.amount)


@dataclass(frozen=True, slots=True)
class FeeComponent:
    """Non-negative fee line with rule version."""

    code: str
    amount: MoneyAmount
    statutory: bool
    rule_version: str

    def __post_init__(self) -> None:
        _require_non_empty_str("code", self.code)
        if not isinstance(self.amount, MoneyAmount):
            raise ContractError("amount must be MoneyAmount")
        _require_non_negative_decimal("amount.amount", self.amount.amount)
        _require_bool("statutory", self.statutory)
        _require_non_empty_str("rule_version", self.rule_version)


@dataclass(frozen=True, slots=True)
class PositionBalance:
    """Per-symbol position with sellable and average cost."""

    symbol: str
    market: Market
    quantity: int
    sellable_quantity: int
    avg_cost: MoneyAmount

    def __post_init__(self) -> None:
        _require_non_empty_str("symbol", self.symbol)
        market = _require_enum("market", self.market, Market)
        quantity = _require_int("quantity", self.quantity, minimum=0)
        sellable = _require_int("sellable_quantity", self.sellable_quantity, minimum=0)
        if sellable > quantity:
            raise ContractError("sellable_quantity must be <= quantity")
        if not isinstance(self.avg_cost, MoneyAmount):
            raise ContractError("avg_cost must be MoneyAmount")
        expected = _quote_currency_for_market(market)
        if self.avg_cost.currency is not expected:
            raise ContractError("avg_cost currency must match market quote currency")


@dataclass(frozen=True, slots=True)
class CashBalance:
    """Per-currency cash buckets; available may not exceed settled."""

    currency: Currency
    settled: Decimal
    available: Decimal
    receivable: Decimal
    payable: Decimal

    def __post_init__(self) -> None:
        _require_enum("currency", self.currency, Currency)
        settled = _require_non_negative_decimal("settled", self.settled)
        available = _require_non_negative_decimal("available", self.available)
        _require_non_negative_decimal("receivable", self.receivable)
        _require_non_negative_decimal("payable", self.payable)
        if available > settled:
            raise ContractError("available must be <= settled")


def _ensure_unique_keys(keys: Any, *, label: str) -> None:
    seen: set[object] = set()
    for key in keys:
        if key in seen:
            raise ContractError(f"duplicate {label} key: {key!r}")
        seen.add(key)


def _require_sequence_of(
    name: str,
    value: object,
    element_type: type,
) -> tuple[Any, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ContractError(f"{name} must be a Sequence[{element_type.__name__}]")
    items = tuple(value)
    for item in items:
        if not isinstance(item, element_type):
            raise ContractError(f"{name} elements must be {element_type.__name__}")
    return items


def _sorted_positions(
    positions: Sequence[PositionBalance],
) -> tuple[PositionBalance, ...]:
    return tuple(sorted(positions, key=lambda item: (item.market.value, item.symbol)))


def _sorted_cash(cash: Sequence[CashBalance]) -> tuple[CashBalance, ...]:
    return tuple(sorted(cash, key=lambda item: item.currency.value))


def _sorted_states(states: Sequence["SymbolMarketState"]) -> tuple["SymbolMarketState", ...]:
    return tuple(sorted(states, key=lambda item: (item.market.value, item.symbol)))


def _sorted_connect_contexts(
    contexts: Sequence["VerifiedConnectMarketContext"],
) -> tuple["VerifiedConnectMarketContext", ...]:
    return tuple(sorted(contexts, key=lambda item: item.route.value))


def _sorted_fees(fees: Sequence[FeeComponent]) -> tuple[FeeComponent, ...]:
    return tuple(sorted(fees, key=lambda item: item.code))


def _sorted_money(amounts: Sequence[MoneyAmount]) -> tuple[MoneyAmount, ...]:
    return tuple(sorted(amounts, key=lambda item: (item.currency.value, str(item.amount))))


def _require_plan_intent_source_closure(
    *,
    target_identity: str,
    market_snapshot_id: str,
    account_snapshot_id: str,
    config_identity: str,
    intent_target_identity: str,
    intent_market_snapshot_id: str,
    intent_account_snapshot_id: str,
    intent_config_identity: str,
) -> None:
    if intent_target_identity != target_identity:
        raise ContractError("intent target_identity must match plan target_identity")
    if intent_market_snapshot_id != market_snapshot_id:
        raise ContractError(
            "intent market_snapshot_id must match plan market_snapshot_id"
        )
    if intent_account_snapshot_id != account_snapshot_id:
        raise ContractError(
            "intent account_snapshot_id must match plan account_snapshot_id"
        )
    if intent_config_identity != config_identity:
        raise ContractError("intent config_identity must match plan config_identity")

def _account_snapshot_digest(
    *,
    as_of: dt.datetime,
    positions: tuple[PositionBalance, ...],
    cash: tuple[CashBalance, ...],
) -> str:
    return _sha256_envelope(
        type_name="AccountSnapshot",
        payload={
            "as_of": as_of,
            "positions": [_position_payload(item) for item in positions],
            "cash": [_cash_payload(item) for item in cash],
        },
    )


def _verified_market_snapshot_digest(
    *,
    as_of: dt.datetime,
    session_date: dt.date,
    states: tuple["SymbolMarketState", ...],
    connect_contexts: tuple["VerifiedConnectMarketContext", ...],
    calendar_identity: str,
    source_identity: str,
) -> str:
    return _sha256_envelope(
        type_name="VerifiedMarketSnapshot",
        payload={
            "as_of": as_of,
            "session_date": session_date,
            "states": [_state_payload(item) for item in states],
            "connect_contexts": [
                _connect_context_payload(item) for item in connect_contexts
            ],
            "calendar_identity": calendar_identity,
            "source_identity": source_identity,
        },
    )


def _verified_connect_market_context_digest(
    *,
    route: ConnectRoute,
    session_date: dt.date,
    as_of: dt.datetime,
    mainland_open: bool,
    hong_kong_open: bool,
    buy_quota_available: bool,
    calendar_identity: str,
    quota_identity: str,
    source_identity: str,
) -> str:
    return _sha256_envelope(
        type_name="VerifiedConnectMarketContext",
        payload={
            "route": route,
            "session_date": session_date,
            "as_of": as_of,
            "mainland_open": mainland_open,
            "hong_kong_open": hong_kong_open,
            "buy_quota_available": buy_quota_available,
            "calendar_identity": calendar_identity,
            "quota_identity": quota_identity,
            "source_identity": source_identity,
        },
    )


def _order_intent_digest(*, plan_id: str, body: dict[str, object]) -> str:
    return _sha256_envelope(
        type_name="OrderIntent",
        payload={"plan_id": plan_id, **body},
    )


def _order_command_digest(
    *,
    intent: "OrderIntent",
    mode: ExecutionMode,
    order_type: OrderType,
    time_in_force: TimeInForce,
) -> str:
    return _sha256_envelope(
        type_name="OrderCommand",
        payload={
            "intent_id": intent.intent_id,
            "mode": mode,
            "order_type": order_type,
            "time_in_force": time_in_force,
        },
    )


def _cancel_command_digest(
    *,
    command_id: str,
    broker_order_id: str,
    mode: ExecutionMode,
    aggregate_status: OrderStatus,
    observed_filled_quantity: int,
    observed_event_ids: tuple[str, ...],
    observed_last_event_at: dt.datetime,
    as_of: dt.datetime,
) -> str:
    return _sha256_envelope(
        type_name="CancelCommand",
        payload={
            "command_id": command_id,
            "broker_order_id": broker_order_id,
            "mode": mode,
            "aggregate_status": aggregate_status,
            "observed_filled_quantity": observed_filled_quantity,
            "observed_event_ids": observed_event_ids,
            "observed_last_event_at": observed_last_event_at,
            "as_of": as_of,
        },
    )


def _execution_event_digest(
    *,
    command_id: str,
    broker_order_id: str | None,
    event_type: ExecutionEventType,
    occurred_at: dt.datetime,
    cumulative_quantity: int,
    last_quantity: int,
    last_price: Decimal | None,
    fees: tuple[FeeComponent, ...],
    reject_code: str | None,
) -> str:
    return _sha256_envelope(
        type_name="ExecutionEvent",
        payload={
            "command_id": command_id,
            "broker_order_id": broker_order_id,
            "event_type": event_type,
            "occurred_at": occurred_at,
            "cumulative_quantity": cumulative_quantity,
            "last_quantity": last_quantity,
            "last_price": last_price,
            "fees": [_fee_payload(item) for item in fees],
            "reject_code": reject_code,
        },
    )


def _order_plan_digest(
    *,
    target_identity: str,
    market_snapshot_id: str,
    account_snapshot_id: str,
    config_identity: str,
    intent_bodies: list[dict[str, object]],
    rejections: tuple["RuleDecision", ...],
    residual_cash: tuple[MoneyAmount, ...],
    decisions: tuple["OrderPlanDecision", ...],
) -> str:
    return _sha256_envelope(
        type_name="OrderPlan",
        payload={
            "target_identity": target_identity,
            "market_snapshot_id": market_snapshot_id,
            "account_snapshot_id": account_snapshot_id,
            "config_identity": config_identity,
            "intents": intent_bodies,
            "rejections": [_rule_decision_payload(item) for item in rejections],
            "residual_cash": [_money_payload(item) for item in residual_cash],
            "decisions": [_order_plan_decision_payload(item) for item in decisions],
        },
    )


def _require_connect_route_for_market(
    market: Market,
    connect_route: object,
) -> ConnectRoute | None:
    if market is Market.HK:
        return _require_enum("connect_route", connect_route, ConnectRoute)
    if connect_route is not None:
        raise ContractError("connect_route must be None for non-HK market")
    return None


def _validate_connect_contexts_for_snapshot(
    *,
    connect_contexts: tuple["VerifiedConnectMarketContext", ...],
    states: tuple["SymbolMarketState", ...],
    session_date: dt.date,
    as_of: dt.datetime,
) -> None:
    has_hk = any(state.market is Market.HK for state in states)
    if has_hk:
        if not connect_contexts:
            raise ContractError(
                "HK market state requires at least one connect context"
            )
    elif connect_contexts:
        raise ContractError(
            "connect_contexts must be empty when snapshot has no HK state"
        )
    _ensure_unique_keys(
        (item.route for item in connect_contexts),
        label="connect context route",
    )
    for context in connect_contexts:
        expected = _verified_connect_market_context_digest(
            route=context.route,
            session_date=context.session_date,
            as_of=context.as_of,
            mainland_open=context.mainland_open,
            hong_kong_open=context.hong_kong_open,
            buy_quota_available=context.buy_quota_available,
            calendar_identity=context.calendar_identity,
            quota_identity=context.quota_identity,
            source_identity=context.source_identity,
        )
        _reject_forged_identity("context_id", context.context_id, expected)
        if context.session_date != session_date:
            raise ContractError(
                "connect context session_date must match snapshot session_date"
            )
        if context.as_of > as_of:
            raise ContractError(
                "connect context as_of must be <= snapshot as_of"
            )


def _validate_order_intent_body_fields(
    *,
    symbol: str,
    market: Market,
    side: OrderSide,
    quantity: int,
    limit_price: Decimal,
    quote_currency: Currency,
    session_date: dt.date,
    generated_at: dt.datetime,
    target_identity: str,
    market_snapshot_id: str,
    account_snapshot_id: str,
    config_identity: str,
    connect_route: ConnectRoute | None,
) -> dict[str, object]:
    """Validate intent body fields shared by OrderIntentSpec and OrderIntent."""
    _require_non_empty_str("symbol", symbol)
    market_e = _require_enum("market", market, Market)
    side_e = _require_enum("side", side, OrderSide)
    qty = _require_int("quantity", quantity, minimum=1)
    price = _require_positive_decimal("limit_price", limit_price)
    currency = _require_enum("quote_currency", quote_currency, Currency)
    if currency is not _quote_currency_for_market(market_e):
        raise ContractError("quote_currency must match market")
    session = _require_date("session_date", session_date)
    generated = _require_utc_datetime("generated_at", generated_at)
    target = _require_hex64("target_identity", target_identity)
    market_id = _require_hex64("market_snapshot_id", market_snapshot_id)
    account_id = _require_hex64("account_snapshot_id", account_snapshot_id)
    config_id = _require_hex64("config_identity", config_identity)
    route = _require_connect_route_for_market(market_e, connect_route)
    return _intent_body_payload(
        symbol=symbol,
        market=market_e,
        side=side_e,
        quantity=qty,
        limit_price=price,
        quote_currency=currency,
        session_date=session,
        generated_at=generated,
        target_identity=target,
        market_snapshot_id=market_id,
        account_snapshot_id=account_id,
        config_identity=config_id,
        connect_route=route,
    )


def _validate_order_intent_fields(
    *,
    intent_id: str,
    plan_id: str,
    symbol: str,
    market: Market,
    side: OrderSide,
    quantity: int,
    limit_price: Decimal,
    quote_currency: Currency,
    session_date: dt.date,
    generated_at: dt.datetime,
    target_identity: str,
    market_snapshot_id: str,
    account_snapshot_id: str,
    config_identity: str,
    connect_route: ConnectRoute | None,
) -> None:
    _require_hex64("intent_id", intent_id)
    _require_hex64("plan_id", plan_id)
    body = _validate_order_intent_body_fields(
        symbol=symbol,
        market=market,
        side=side,
        quantity=quantity,
        limit_price=limit_price,
        quote_currency=quote_currency,
        session_date=session_date,
        generated_at=generated_at,
        target_identity=target_identity,
        market_snapshot_id=market_snapshot_id,
        account_snapshot_id=account_snapshot_id,
        config_identity=config_identity,
        connect_route=connect_route,
    )
    expected = _order_intent_digest(plan_id=plan_id, body=body)
    _reject_forged_identity("intent_id", intent_id, expected)

@dataclass(frozen=True, slots=True)
class AccountSnapshot:
    """Canonical account snapshot; snapshot_id is package-computed."""

    snapshot_id: str
    as_of: dt.datetime
    positions: tuple[PositionBalance, ...]
    cash: tuple[CashBalance, ...]

    def __post_init__(self) -> None:
        _require_hex64("snapshot_id", self.snapshot_id)
        _require_utc_datetime("as_of", self.as_of)
        if type(self.positions) is not tuple or any(
            not isinstance(item, PositionBalance) for item in self.positions
        ):
            raise ContractError("positions must be tuple[PositionBalance, ...]")
        if type(self.cash) is not tuple or any(
            not isinstance(item, CashBalance) for item in self.cash
        ):
            raise ContractError("cash must be tuple[CashBalance, ...]")
        _ensure_unique_keys(
            ((item.market, item.symbol) for item in self.positions),
            label="position",
        )
        _ensure_unique_keys((item.currency for item in self.cash), label="cash")
        expected = _account_snapshot_digest(
            as_of=self.as_of,
            positions=self.positions,
            cash=self.cash,
        )
        _reject_forged_identity("snapshot_id", self.snapshot_id, expected)


@dataclass(frozen=True, slots=True)
class SymbolMarketState:
    """Per-symbol verified market state for one session.

    Route-level buy quota lives only on VerifiedConnectMarketContext.
    """

    symbol: str
    market: Market
    session_date: dt.date
    quote_currency: Currency
    reference_price: Decimal
    limit_up: Decimal | None
    limit_down: Decimal | None
    suspended: bool
    board_lot: int
    tick_size: Decimal
    rule_version: str

    def __post_init__(self) -> None:
        _require_non_empty_str("symbol", self.symbol)
        market = _require_enum("market", self.market, Market)
        _require_date("session_date", self.session_date)
        currency = _require_enum("quote_currency", self.quote_currency, Currency)
        if currency is not _quote_currency_for_market(market):
            raise ContractError("quote_currency must match market")
        _require_positive_decimal("reference_price", self.reference_price)
        if self.limit_up is not None:
            _require_positive_decimal("limit_up", self.limit_up)
        if self.limit_down is not None:
            _require_positive_decimal("limit_down", self.limit_down)
        if self.limit_up is not None and self.limit_down is not None:
            if self.limit_up < self.limit_down:
                raise ContractError("limit_up must be >= limit_down")
        _require_bool("suspended", self.suspended)
        _require_int("board_lot", self.board_lot, minimum=1)
        _require_positive_decimal("tick_size", self.tick_size)
        _require_non_empty_str("rule_version", self.rule_version)


@dataclass(frozen=True, slots=True)
class VerifiedMarketSnapshot:
    """Verified multi-symbol market snapshot; snapshot_id is package-computed."""

    snapshot_id: str
    as_of: dt.datetime
    session_date: dt.date
    states: tuple[SymbolMarketState, ...]
    connect_contexts: tuple[VerifiedConnectMarketContext, ...]
    calendar_identity: str
    source_identity: str

    def __post_init__(self) -> None:
        _require_hex64("snapshot_id", self.snapshot_id)
        _require_utc_datetime("as_of", self.as_of)
        _require_date("session_date", self.session_date)
        if type(self.states) is not tuple or any(
            not isinstance(item, SymbolMarketState) for item in self.states
        ):
            raise ContractError("states must be tuple[SymbolMarketState, ...]")
        if type(self.connect_contexts) is not tuple or any(
            not isinstance(item, VerifiedConnectMarketContext)
            for item in self.connect_contexts
        ):
            raise ContractError(
                "connect_contexts must be tuple[VerifiedConnectMarketContext, ...]"
            )
        _ensure_unique_keys(
            ((item.market, item.symbol) for item in self.states),
            label="market state",
        )
        for state in self.states:
            if state.session_date != self.session_date:
                raise ContractError(
                    "state.session_date must match snapshot session_date"
                )
        _validate_connect_contexts_for_snapshot(
            connect_contexts=self.connect_contexts,
            states=self.states,
            session_date=self.session_date,
            as_of=self.as_of,
        )
        _require_hex64("calendar_identity", self.calendar_identity)
        _require_hex64("source_identity", self.source_identity)
        expected = _verified_market_snapshot_digest(
            as_of=self.as_of,
            session_date=self.session_date,
            states=self.states,
            connect_contexts=self.connect_contexts,
            calendar_identity=self.calendar_identity,
            source_identity=self.source_identity,
        )
        _reject_forged_identity("snapshot_id", self.snapshot_id, expected)


@dataclass(frozen=True, slots=True)
class VerifiedConnectMarketContext:
    """Verified route-level connect calendar/quota facts; context_id is package-computed.

    Upstream calendar/quota/source identities are opaque 64-hex provenance only.
    buy_quota_available is route-level and constrains BUY only; connect_open is not stored.
    """

    context_id: str
    route: ConnectRoute
    session_date: dt.date
    as_of: dt.datetime
    mainland_open: bool
    hong_kong_open: bool
    buy_quota_available: bool
    calendar_identity: str
    quota_identity: str
    source_identity: str

    def __post_init__(self) -> None:
        _require_hex64("context_id", self.context_id)
        _require_enum("route", self.route, ConnectRoute)
        _require_date("session_date", self.session_date)
        _require_utc_datetime("as_of", self.as_of)
        _require_bool("mainland_open", self.mainland_open)
        _require_bool("hong_kong_open", self.hong_kong_open)
        _require_bool("buy_quota_available", self.buy_quota_available)
        _require_hex64("calendar_identity", self.calendar_identity)
        _require_hex64("quota_identity", self.quota_identity)
        _require_hex64("source_identity", self.source_identity)
        expected = _verified_connect_market_context_digest(
            route=self.route,
            session_date=self.session_date,
            as_of=self.as_of,
            mainland_open=self.mainland_open,
            hong_kong_open=self.hong_kong_open,
            buy_quota_available=self.buy_quota_available,
            calendar_identity=self.calendar_identity,
            quota_identity=self.quota_identity,
            source_identity=self.source_identity,
        )
        _reject_forged_identity("context_id", self.context_id, expected)


@dataclass(frozen=True, slots=True)
class OrderIntentSpec:
    """Intent fields without plan_id/intent_id for plan construction."""

    symbol: str
    market: Market
    side: OrderSide
    quantity: int
    limit_price: Decimal
    quote_currency: Currency
    session_date: dt.date
    generated_at: dt.datetime
    target_identity: str
    market_snapshot_id: str
    account_snapshot_id: str
    config_identity: str
    connect_route: ConnectRoute | None

    def __post_init__(self) -> None:
        _validate_order_intent_body_fields(
            symbol=self.symbol,
            market=self.market,
            side=self.side,
            quantity=self.quantity,
            limit_price=self.limit_price,
            quote_currency=self.quote_currency,
            session_date=self.session_date,
            generated_at=self.generated_at,
            target_identity=self.target_identity,
            market_snapshot_id=self.market_snapshot_id,
            account_snapshot_id=self.account_snapshot_id,
            config_identity=self.config_identity,
            connect_route=self.connect_route,
        )


@dataclass(frozen=True, slots=True)
class OrderIntent:
    """Canonical order intent; intent_id is package-computed."""

    intent_id: str
    plan_id: str
    symbol: str
    market: Market
    side: OrderSide
    quantity: int
    limit_price: Decimal
    quote_currency: Currency
    session_date: dt.date
    generated_at: dt.datetime
    target_identity: str
    market_snapshot_id: str
    account_snapshot_id: str
    config_identity: str
    connect_route: ConnectRoute | None

    def __post_init__(self) -> None:
        _validate_order_intent_fields(
            intent_id=self.intent_id,
            plan_id=self.plan_id,
            symbol=self.symbol,
            market=self.market,
            side=self.side,
            quantity=self.quantity,
            limit_price=self.limit_price,
            quote_currency=self.quote_currency,
            session_date=self.session_date,
            generated_at=self.generated_at,
            target_identity=self.target_identity,
            market_snapshot_id=self.market_snapshot_id,
            account_snapshot_id=self.account_snapshot_id,
            config_identity=self.config_identity,
            connect_route=self.connect_route,
        )


@dataclass(frozen=True, slots=True)
class OrderCommand:
    """Submit-ready command wrapping an intent; command_id is package-computed."""

    command_id: str
    intent: OrderIntent
    mode: ExecutionMode
    order_type: OrderType = OrderType.LIMIT
    time_in_force: TimeInForce = TimeInForce.DAY

    def __post_init__(self) -> None:
        _require_hex64("command_id", self.command_id)
        if not isinstance(self.intent, OrderIntent):
            raise ContractError("intent must be OrderIntent")
        mode = _require_enum("mode", self.mode, ExecutionMode)
        if mode not in (ExecutionMode.PAPER, ExecutionMode.SHADOW):
            raise ContractError("mode must be PAPER or SHADOW")
        order_type = _require_enum("order_type", self.order_type, OrderType)
        if order_type is not OrderType.LIMIT:
            raise ContractError("order_type must be LIMIT")
        tif = _require_enum("time_in_force", self.time_in_force, TimeInForce)
        if tif is not TimeInForce.DAY:
            raise ContractError("time_in_force must be DAY")
        expected = _order_command_digest(
            intent=self.intent,
            mode=self.mode,
            order_type=self.order_type,
            time_in_force=self.time_in_force,
        )
        _reject_forged_identity("command_id", self.command_id, expected)


@dataclass(frozen=True, slots=True)
class CancelCommand:
    """Durable, content-addressed request to cancel one PAPER order."""

    cancel_id: str
    command_id: str
    broker_order_id: str
    mode: ExecutionMode
    aggregate_status: OrderStatus
    observed_filled_quantity: int
    observed_event_ids: tuple[str, ...]
    observed_last_event_at: dt.datetime
    as_of: dt.datetime

    def __post_init__(self) -> None:
        _require_hex64("cancel_id", self.cancel_id)
        _require_hex64("command_id", self.command_id)
        _require_non_empty_str("broker_order_id", self.broker_order_id)
        mode = _require_enum("mode", self.mode, ExecutionMode)
        if mode is not ExecutionMode.PAPER:
            raise ContractError("cancel mode must be PAPER")
        status = _require_enum("aggregate_status", self.aggregate_status, OrderStatus)
        if status not in (OrderStatus.SUBMITTED, OrderStatus.PARTIAL_FILLED):
            raise ContractError("cancel aggregate_status must be SUBMITTED or PARTIAL_FILLED")
        filled = _require_int("observed_filled_quantity", self.observed_filled_quantity, minimum=0)
        if status is OrderStatus.SUBMITTED and filled != 0:
            raise ContractError("SUBMITTED cancel snapshot requires zero filled quantity")
        if status is OrderStatus.PARTIAL_FILLED and filled <= 0:
            raise ContractError("PARTIAL_FILLED cancel snapshot requires positive filled quantity")
        if type(self.observed_event_ids) is not tuple or not self.observed_event_ids:
            raise ContractError("observed_event_ids must be a non-empty tuple")
        for event_id in self.observed_event_ids:
            _require_hex64("observed_event_id", event_id)
        _ensure_unique_keys(self.observed_event_ids, label="observed event")
        observed_at = _require_cancel_utc_datetime(
            "observed_last_event_at", self.observed_last_event_at
        )
        as_of = _require_cancel_utc_datetime("as_of", self.as_of)
        if as_of < observed_at:
            raise ContractError("cancel as_of must not precede observed_last_event_at")
        expected = _cancel_command_digest(
            command_id=self.command_id,
            broker_order_id=self.broker_order_id,
            mode=self.mode,
            aggregate_status=self.aggregate_status,
            observed_filled_quantity=self.observed_filled_quantity,
            observed_event_ids=self.observed_event_ids,
            observed_last_event_at=self.observed_last_event_at,
            as_of=self.as_of,
        )
        _reject_forged_identity("cancel_id", self.cancel_id, expected)


@dataclass(frozen=True, slots=True)
class ExecutionEvent:
    """Broker/gateway execution event; event_id is package-computed."""

    event_id: str
    command_id: str
    broker_order_id: str | None
    event_type: ExecutionEventType
    occurred_at: dt.datetime
    cumulative_quantity: int
    last_quantity: int
    last_price: Decimal | None
    fees: tuple[FeeComponent, ...]
    reject_code: str | None

    def __post_init__(self) -> None:
        _require_hex64("event_id", self.event_id)
        _require_hex64("command_id", self.command_id)
        if self.broker_order_id is not None:
            _require_non_empty_str("broker_order_id", self.broker_order_id)
        event_type = _require_enum("event_type", self.event_type, ExecutionEventType)
        _require_utc_datetime("occurred_at", self.occurred_at)
        cumulative = _require_int("cumulative_quantity", self.cumulative_quantity, minimum=0)
        last_qty = _require_int("last_quantity", self.last_quantity, minimum=0)
        if type(self.fees) is not tuple or any(
            not isinstance(item, FeeComponent) for item in self.fees
        ):
            raise ContractError("fees must be tuple[FeeComponent, ...]")
        _ensure_unique_keys((item.code for item in self.fees), label="fee")
        if event_type in _FILL_EVENTS:
            if last_qty <= 0:
                raise ContractError("fill events require positive last_quantity")
            if self.last_price is None:
                raise ContractError("fill events require positive last_price")
            _require_positive_decimal("last_price", self.last_price)
            if cumulative < last_qty:
                raise ContractError("cumulative_quantity must be >= last_quantity")
            if self.reject_code is not None:
                raise ContractError("fill events must not set reject_code")
        elif event_type is ExecutionEventType.REJECTED:
            _require_non_empty_str("reject_code", self.reject_code)
            if last_qty != 0 or cumulative != 0 or self.last_price is not None:
                raise ContractError("rejected events must not forge fill fields")
        elif event_type in _NON_FILL_EVENTS:
            if last_qty != 0 or self.last_price is not None:
                raise ContractError("non-fill events must not forge fill fields")
            if self.reject_code is not None:
                raise ContractError("non-reject events must not set reject_code")
            if event_type is ExecutionEventType.ACCEPTED and cumulative != 0:
                raise ContractError("accepted events require cumulative_quantity == 0")
        else:
            raise ContractError(f"unsupported event_type: {event_type}")
        expected = _execution_event_digest(
            command_id=self.command_id,
            broker_order_id=self.broker_order_id,
            event_type=self.event_type,
            occurred_at=self.occurred_at,
            cumulative_quantity=self.cumulative_quantity,
            last_quantity=self.last_quantity,
            last_price=self.last_price,
            fees=self.fees,
            reject_code=self.reject_code,
        )
        _reject_forged_identity("event_id", self.event_id, expected)


@dataclass(frozen=True, slots=True)
class RuleDecision:
    """Pure rule evaluation outcome."""

    accepted: bool
    code: str
    normalized_quantity: int
    normalized_limit_price: Decimal
    rule_version: str

    def __post_init__(self) -> None:
        _require_bool("accepted", self.accepted)
        _require_non_empty_str("code", self.code)
        _require_int("normalized_quantity", self.normalized_quantity, minimum=0)
        _require_finite_decimal("normalized_limit_price", self.normalized_limit_price)
        if self.normalized_limit_price < 0:
            raise ContractError("normalized_limit_price must be non-negative")
        _require_non_empty_str("rule_version", self.rule_version)


OrderPlanReasonClass: TypeAlias = Literal[
    "ACCEPTED",
    "RULE_REJECTED",
    "ECONOMIC_REJECTED",
    "CASH_REJECTED",
    "ZERO_DELTA",
    "PARTIAL_CASH",
]
_ORDER_PLAN_REASON_CLASSES = frozenset(
    {
        "ACCEPTED",
        "RULE_REJECTED",
        "ECONOMIC_REJECTED",
        "CASH_REJECTED",
        "ZERO_DELTA",
        "PARTIAL_CASH",
    }
)
_ORDER_PLAN_REJECTION_CLASSES = frozenset(
    {"RULE_REJECTED", "ECONOMIC_REJECTED", "CASH_REJECTED"}
)


@dataclass(frozen=True, slots=True)
class OrderPlanDecision:
    """Per-target auditable allocation outcome with package-computed target key."""

    target_key: str
    symbol: str
    market: Market
    connect_route: ConnectRoute | None
    side: OrderSide
    requested_quantity: int
    accepted_quantity: int
    rejected_quantity: int
    zero_delta_quantity: int
    outcome: RuleDecision
    reason_class: OrderPlanReasonClass

    def __post_init__(self) -> None:
        _require_hex64("target_key", self.target_key)
        _require_non_empty_str("symbol", self.symbol)
        market = _require_enum("market", self.market, Market)
        route = _require_connect_route_for_market(market, self.connect_route)
        _require_enum("side", self.side, OrderSide)
        requested = _require_int(
            "requested_quantity", self.requested_quantity, minimum=0
        )
        accepted = _require_int(
            "accepted_quantity", self.accepted_quantity, minimum=0
        )
        rejected = _require_int(
            "rejected_quantity", self.rejected_quantity, minimum=0
        )
        zero_delta = _require_int(
            "zero_delta_quantity", self.zero_delta_quantity, minimum=0
        )
        if requested != accepted + rejected + zero_delta:
            raise ContractError("order plan decision quantity conservation failed")
        if type(self.outcome) is not RuleDecision:
            raise ContractError("outcome must be RuleDecision")
        if self.reason_class not in _ORDER_PLAN_REASON_CLASSES:
            raise ContractError("order plan decision reason_class invalid")
        expected_key = _order_plan_decision_target_digest(
            symbol=self.symbol,
            market=market,
            connect_route=route,
        )
        _reject_forged_identity("target_key", self.target_key, expected_key)

        if self.reason_class == "ACCEPTED":
            valid = (
                requested > 0
                and accepted > 0
                and rejected == 0
                and self.outcome.accepted
                and self.outcome.normalized_quantity == accepted
            )
        elif self.reason_class == "PARTIAL_CASH":
            valid = (
                accepted > 0
                and rejected > 0
                and self.outcome.accepted
                and self.outcome.normalized_quantity == accepted
            )
        elif self.reason_class == "ZERO_DELTA":
            valid = (
                accepted == 0
                and rejected == 0
                and zero_delta == requested
                and self.outcome.accepted
                and self.outcome.normalized_quantity == 0
            )
        else:
            valid = (
                requested > 0
                and accepted == 0
                and rejected > 0
                and not self.outcome.accepted
                and self.outcome.normalized_quantity == 0
            )
        if not valid:
            raise ContractError("order plan decision state combination invalid")


@dataclass(frozen=True, slots=True)
class OrderPlan:
    """Sorted unique intents plus rejections; plan_id is package-computed."""

    plan_id: str
    target_identity: str
    market_snapshot_id: str
    account_snapshot_id: str
    config_identity: str
    intents: tuple[OrderIntent, ...]
    rejections: tuple[RuleDecision, ...]
    residual_cash: tuple[MoneyAmount, ...]
    decisions: tuple[OrderPlanDecision, ...] = ()

    def __post_init__(self) -> None:
        _require_hex64("plan_id", self.plan_id)
        _require_hex64("target_identity", self.target_identity)
        _require_hex64("market_snapshot_id", self.market_snapshot_id)
        _require_hex64("account_snapshot_id", self.account_snapshot_id)
        _require_hex64("config_identity", self.config_identity)
        if type(self.intents) is not tuple or any(
            not isinstance(item, OrderIntent) for item in self.intents
        ):
            raise ContractError("intents must be tuple[OrderIntent, ...]")
        if type(self.rejections) is not tuple or any(
            not isinstance(item, RuleDecision) for item in self.rejections
        ):
            raise ContractError("rejections must be tuple[RuleDecision, ...]")
        if type(self.residual_cash) is not tuple or any(
            not isinstance(item, MoneyAmount) for item in self.residual_cash
        ):
            raise ContractError("residual_cash must be tuple[MoneyAmount, ...]")
        if type(self.decisions) is not tuple or any(
            type(item) is not OrderPlanDecision for item in self.decisions
        ):
            raise ContractError("decisions must be tuple[OrderPlanDecision, ...]")
        _ensure_unique_keys(
            ((item.market, item.symbol, item.side) for item in self.intents),
            label="intent",
        )
        _ensure_unique_keys((item.currency for item in self.residual_cash), label="residual cash")
        _ensure_unique_keys(
            (item.target_key for item in self.decisions), label="target decision"
        )
        for intent in self.intents:
            if intent.plan_id != self.plan_id:
                raise ContractError("intent.plan_id must match plan_id")
            _require_plan_intent_source_closure(
                target_identity=self.target_identity,
                market_snapshot_id=self.market_snapshot_id,
                account_snapshot_id=self.account_snapshot_id,
                config_identity=self.config_identity,
                intent_target_identity=intent.target_identity,
                intent_market_snapshot_id=intent.market_snapshot_id,
                intent_account_snapshot_id=intent.account_snapshot_id,
                intent_config_identity=intent.config_identity,
            )
        for decision in self.rejections:
            if decision.accepted:
                raise ContractError("rejections must have accepted=False")
        if self.decisions:
            expected_rejections = tuple(
                item.outcome
                for item in self.decisions
                if item.reason_class in _ORDER_PLAN_REJECTION_CLASSES
            )
            if self.rejections != expected_rejections:
                raise ContractError("rejections must match failed target decisions")
            accepted_decisions = tuple(
                item for item in self.decisions if item.accepted_quantity > 0
            )
            if len(self.intents) != len(accepted_decisions):
                raise ContractError("intents must match accepted target decisions")
            intents_by_key = {
                (item.market, item.symbol, item.connect_route, item.side): item
                for item in self.intents
            }
            for target_decision in accepted_decisions:
                matched_intent = intents_by_key.get(
                    (
                        target_decision.market,
                        target_decision.symbol,
                        target_decision.connect_route,
                        target_decision.side,
                    )
                )
                if (
                    matched_intent is None
                    or matched_intent.quantity != target_decision.accepted_quantity
                ):
                    raise ContractError(
                        "intent quantity must match accepted target decision"
                    )
        expected = _order_plan_digest(
            target_identity=self.target_identity,
            market_snapshot_id=self.market_snapshot_id,
            account_snapshot_id=self.account_snapshot_id,
            config_identity=self.config_identity,
            intent_bodies=[
                _intent_body_payload(
                    symbol=item.symbol,
                    market=item.market,
                    side=item.side,
                    quantity=item.quantity,
                    limit_price=item.limit_price,
                    quote_currency=item.quote_currency,
                    session_date=item.session_date,
                    generated_at=item.generated_at,
                    target_identity=item.target_identity,
                    market_snapshot_id=item.market_snapshot_id,
                    account_snapshot_id=item.account_snapshot_id,
                    config_identity=item.config_identity,
                    connect_route=item.connect_route,
                )
                for item in self.intents
            ],
            rejections=self.rejections,
            residual_cash=self.residual_cash,
            decisions=self.decisions,
        )
        _reject_forged_identity("plan_id", self.plan_id, expected)


def _intent_sort_key(spec: OrderIntentSpec | OrderIntent) -> tuple[str, str, str]:
    return (spec.market.value, spec.symbol, spec.side.value)


def _plan_decision_sort_key(
    decision: OrderPlanDecision,
) -> tuple[str, str, str, str]:
    route = "" if decision.connect_route is None else decision.connect_route.value
    return (decision.market.value, decision.symbol, route, decision.side.value)


def build_money_amount(currency: Currency, amount: Decimal) -> MoneyAmount:
    """Strict MoneyAmount constructor."""
    return MoneyAmount(currency=currency, amount=amount)


def build_money_amount_identity(money: MoneyAmount) -> str:
    """Canonical identity of a MoneyAmount."""
    if not isinstance(money, MoneyAmount):
        raise TypeError("build_money_amount_identity requires MoneyAmount")
    return _sha256_envelope(type_name="MoneyAmount", payload=_money_payload(money))


def build_fee_component(
    *,
    code: str,
    amount: MoneyAmount,
    statutory: bool,
    rule_version: str,
) -> FeeComponent:
    """Strict FeeComponent constructor."""
    return FeeComponent(
        code=code,
        amount=amount,
        statutory=statutory,
        rule_version=rule_version,
    )


def build_fee_component_identity(fee: FeeComponent) -> str:
    """Canonical identity of a FeeComponent."""
    if not isinstance(fee, FeeComponent):
        raise TypeError("build_fee_component_identity requires FeeComponent")
    return _sha256_envelope(type_name="FeeComponent", payload=_fee_payload(fee))


def build_position_balance(
    *,
    symbol: str,
    market: Market,
    quantity: int,
    sellable_quantity: int,
    avg_cost: MoneyAmount,
) -> PositionBalance:
    """Strict PositionBalance constructor."""
    return PositionBalance(
        symbol=symbol,
        market=market,
        quantity=quantity,
        sellable_quantity=sellable_quantity,
        avg_cost=avg_cost,
    )


def build_position_balance_identity(position: PositionBalance) -> str:
    """Canonical identity of a PositionBalance."""
    if not isinstance(position, PositionBalance):
        raise TypeError("build_position_balance_identity requires PositionBalance")
    return _sha256_envelope(type_name="PositionBalance", payload=_position_payload(position))


def build_cash_balance(
    *,
    currency: Currency,
    settled: Decimal,
    available: Decimal,
    receivable: Decimal,
    payable: Decimal,
) -> CashBalance:
    """Strict CashBalance constructor."""
    return CashBalance(
        currency=currency,
        settled=settled,
        available=available,
        receivable=receivable,
        payable=payable,
    )


def build_cash_balance_identity(cash: CashBalance) -> str:
    """Canonical identity of a CashBalance."""
    if not isinstance(cash, CashBalance):
        raise TypeError("build_cash_balance_identity requires CashBalance")
    return _sha256_envelope(type_name="CashBalance", payload=_cash_payload(cash))


def build_account_snapshot(
    *,
    as_of: dt.datetime,
    positions: Sequence[PositionBalance],
    cash: Sequence[CashBalance],
) -> AccountSnapshot:
    """Build AccountSnapshot with canonical sort and computed snapshot_id."""
    position_items = _require_sequence_of("positions", positions, PositionBalance)
    cash_items = _require_sequence_of("cash", cash, CashBalance)
    ordered_positions = _sorted_positions(position_items)
    ordered_cash = _sorted_cash(cash_items)
    snapshot_id = _account_snapshot_digest(
        as_of=as_of,
        positions=ordered_positions,
        cash=ordered_cash,
    )
    return AccountSnapshot(
        snapshot_id=snapshot_id,
        as_of=as_of,
        positions=ordered_positions,
        cash=ordered_cash,
    )


def build_account_snapshot_identity(snapshot: AccountSnapshot) -> str:
    """Return and verify AccountSnapshot identity."""
    if not isinstance(snapshot, AccountSnapshot):
        raise TypeError("build_account_snapshot_identity requires AccountSnapshot")
    digest = _account_snapshot_digest(
        as_of=snapshot.as_of,
        positions=snapshot.positions,
        cash=snapshot.cash,
    )
    _reject_forged_identity("snapshot_id", snapshot.snapshot_id, digest)
    return digest


def build_symbol_market_state(
    *,
    symbol: str,
    market: Market,
    session_date: dt.date,
    quote_currency: Currency,
    reference_price: Decimal,
    limit_up: Decimal | None,
    limit_down: Decimal | None,
    suspended: bool,
    board_lot: int,
    tick_size: Decimal,
    rule_version: str,
) -> SymbolMarketState:
    """Strict SymbolMarketState constructor."""
    return SymbolMarketState(
        symbol=symbol,
        market=market,
        session_date=session_date,
        quote_currency=quote_currency,
        reference_price=reference_price,
        limit_up=limit_up,
        limit_down=limit_down,
        suspended=suspended,
        board_lot=board_lot,
        tick_size=tick_size,
        rule_version=rule_version,
    )


def build_symbol_market_state_identity(state: SymbolMarketState) -> str:
    """Canonical identity of a SymbolMarketState."""
    if not isinstance(state, SymbolMarketState):
        raise TypeError("build_symbol_market_state_identity requires SymbolMarketState")
    return _sha256_envelope(type_name="SymbolMarketState", payload=_state_payload(state))


def build_verified_market_snapshot(
    *,
    as_of: dt.datetime,
    session_date: dt.date,
    states: Sequence[SymbolMarketState],
    connect_contexts: Sequence[VerifiedConnectMarketContext],
    calendar_identity: str,
    source_identity: str,
) -> VerifiedMarketSnapshot:
    """Build VerifiedMarketSnapshot with canonical sort and computed snapshot_id."""
    state_items = _require_sequence_of("states", states, SymbolMarketState)
    context_items = _require_sequence_of(
        "connect_contexts", connect_contexts, VerifiedConnectMarketContext
    )
    for state in state_items:
        if state.session_date != session_date:
            raise ContractError(
                "state.session_date must match snapshot session_date"
            )
    ordered_states = _sorted_states(state_items)
    ordered_contexts = _sorted_connect_contexts(context_items)
    _validate_connect_contexts_for_snapshot(
        connect_contexts=ordered_contexts,
        states=ordered_states,
        session_date=session_date,
        as_of=as_of,
    )
    snapshot_id = _verified_market_snapshot_digest(
        as_of=as_of,
        session_date=session_date,
        states=ordered_states,
        connect_contexts=ordered_contexts,
        calendar_identity=calendar_identity,
        source_identity=source_identity,
    )
    return VerifiedMarketSnapshot(
        snapshot_id=snapshot_id,
        as_of=as_of,
        session_date=session_date,
        states=ordered_states,
        connect_contexts=ordered_contexts,
        calendar_identity=calendar_identity,
        source_identity=source_identity,
    )


def build_verified_market_snapshot_identity(snapshot: VerifiedMarketSnapshot) -> str:
    """Return and verify VerifiedMarketSnapshot identity."""
    if not isinstance(snapshot, VerifiedMarketSnapshot):
        raise TypeError(
            "build_verified_market_snapshot_identity requires VerifiedMarketSnapshot"
        )
    _validate_connect_contexts_for_snapshot(
        connect_contexts=snapshot.connect_contexts,
        states=snapshot.states,
        session_date=snapshot.session_date,
        as_of=snapshot.as_of,
    )
    digest = _verified_market_snapshot_digest(
        as_of=snapshot.as_of,
        session_date=snapshot.session_date,
        states=snapshot.states,
        connect_contexts=snapshot.connect_contexts,
        calendar_identity=snapshot.calendar_identity,
        source_identity=snapshot.source_identity,
    )
    _reject_forged_identity("snapshot_id", snapshot.snapshot_id, digest)
    return digest


def build_verified_connect_market_context(
    *,
    route: ConnectRoute,
    session_date: dt.date,
    as_of: dt.datetime,
    mainland_open: bool,
    hong_kong_open: bool,
    buy_quota_available: bool,
    calendar_identity: str,
    quota_identity: str,
    source_identity: str,
) -> VerifiedConnectMarketContext:
    """Build VerifiedConnectMarketContext with package-computed context_id."""
    context_id = _verified_connect_market_context_digest(
        route=route,
        session_date=session_date,
        as_of=as_of,
        mainland_open=mainland_open,
        hong_kong_open=hong_kong_open,
        buy_quota_available=buy_quota_available,
        calendar_identity=calendar_identity,
        quota_identity=quota_identity,
        source_identity=source_identity,
    )
    return VerifiedConnectMarketContext(
        context_id=context_id,
        route=route,
        session_date=session_date,
        as_of=as_of,
        mainland_open=mainland_open,
        hong_kong_open=hong_kong_open,
        buy_quota_available=buy_quota_available,
        calendar_identity=calendar_identity,
        quota_identity=quota_identity,
        source_identity=source_identity,
    )


def build_verified_connect_market_context_identity(
    context: VerifiedConnectMarketContext,
) -> str:
    """Return and verify VerifiedConnectMarketContext identity."""
    if not isinstance(context, VerifiedConnectMarketContext):
        raise TypeError(
            "build_verified_connect_market_context_identity requires "
            "VerifiedConnectMarketContext"
        )
    digest = _verified_connect_market_context_digest(
        route=context.route,
        session_date=context.session_date,
        as_of=context.as_of,
        mainland_open=context.mainland_open,
        hong_kong_open=context.hong_kong_open,
        buy_quota_available=context.buy_quota_available,
        calendar_identity=context.calendar_identity,
        quota_identity=context.quota_identity,
        source_identity=context.source_identity,
    )
    _reject_forged_identity("context_id", context.context_id, digest)
    return digest


def build_order_intent(
    *,
    plan_id: str,
    symbol: str,
    market: Market,
    side: OrderSide,
    quantity: int,
    limit_price: Decimal,
    quote_currency: Currency,
    session_date: dt.date,
    generated_at: dt.datetime,
    target_identity: str,
    market_snapshot_id: str,
    account_snapshot_id: str,
    config_identity: str,
    connect_route: ConnectRoute | None,
) -> OrderIntent:
    """Build OrderIntent with package-computed intent_id."""
    body = _intent_body_payload(
        symbol=symbol,
        market=market,
        side=side,
        quantity=quantity,
        limit_price=limit_price,
        quote_currency=quote_currency,
        session_date=session_date,
        generated_at=generated_at,
        target_identity=target_identity,
        market_snapshot_id=market_snapshot_id,
        account_snapshot_id=account_snapshot_id,
        config_identity=config_identity,
        connect_route=connect_route,
    )
    intent_id = _order_intent_digest(plan_id=plan_id, body=body)
    return OrderIntent(
        intent_id=intent_id,
        plan_id=plan_id,
        symbol=symbol,
        market=market,
        side=side,
        quantity=quantity,
        limit_price=limit_price,
        quote_currency=quote_currency,
        session_date=session_date,
        generated_at=generated_at,
        target_identity=target_identity,
        market_snapshot_id=market_snapshot_id,
        account_snapshot_id=account_snapshot_id,
        config_identity=config_identity,
        connect_route=connect_route,
    )


def build_order_intent_identity(intent: OrderIntent) -> str:
    """Return and verify OrderIntent identity."""
    if not isinstance(intent, OrderIntent):
        raise TypeError("build_order_intent_identity requires OrderIntent")
    body = _intent_body_payload(
        symbol=intent.symbol,
        market=intent.market,
        side=intent.side,
        quantity=intent.quantity,
        limit_price=intent.limit_price,
        quote_currency=intent.quote_currency,
        session_date=intent.session_date,
        generated_at=intent.generated_at,
        target_identity=intent.target_identity,
        market_snapshot_id=intent.market_snapshot_id,
        account_snapshot_id=intent.account_snapshot_id,
        config_identity=intent.config_identity,
        connect_route=intent.connect_route,
    )
    digest = _order_intent_digest(plan_id=intent.plan_id, body=body)
    _reject_forged_identity("intent_id", intent.intent_id, digest)
    return digest


def build_order_command(
    *,
    intent: OrderIntent,
    mode: ExecutionMode,
    order_type: OrderType = OrderType.LIMIT,
    time_in_force: TimeInForce = TimeInForce.DAY,
) -> OrderCommand:
    """Build OrderCommand with package-computed command_id."""
    command_id = _order_command_digest(
        intent=intent,
        mode=mode,
        order_type=order_type,
        time_in_force=time_in_force,
    )
    return OrderCommand(
        command_id=command_id,
        intent=intent,
        mode=mode,
        order_type=order_type,
        time_in_force=time_in_force,
    )


def build_order_command_identity(command: OrderCommand) -> str:
    """Return and verify OrderCommand identity."""
    if not isinstance(command, OrderCommand):
        raise TypeError("build_order_command_identity requires OrderCommand")
    digest = _order_command_digest(
        intent=command.intent,
        mode=command.mode,
        order_type=command.order_type,
        time_in_force=command.time_in_force,
    )
    _reject_forged_identity("command_id", command.command_id, digest)
    return digest


def build_cancel_command(
    *,
    command: OrderCommand,
    aggregate: object,
    as_of: dt.datetime,
    replay: CancelCommand | None = None,
) -> CancelCommand:
    """Build a first cancel, or prove and return the same command while cancelling."""
    if not isinstance(command, OrderCommand):
        raise ContractError("command must be OrderCommand")
    source_invalid = False
    try:
        build_order_intent_identity(command.intent)
        build_order_command_identity(command)
    except Exception:
        source_invalid = True
    if source_invalid:
        raise ContractError("CANCEL_SOURCE_COMMAND_INVALID")
    if command.mode is not ExecutionMode.PAPER:
        raise ContractError("cancel command requires PAPER OrderCommand")

    # Local import avoids making the foundational value-object module depend on OMS.
    from quant.execution.oms import OrderAggregate

    if not isinstance(aggregate, OrderAggregate):
        raise ContractError("aggregate must be OrderAggregate")
    # Reconstruct to re-run all invariants even if a frozen instance was mutated.
    aggregate_invalid = False
    verified: OrderAggregate | None = None
    try:
        verified = OrderAggregate(
            command_id=aggregate.command_id,
            status=aggregate.status,
            filled_quantity=aggregate.filled_quantity,
            broker_order_id=aggregate.broker_order_id,
            reject_code=aggregate.reject_code,
            applied_event_ids=aggregate.applied_event_ids,
            command_quantity=aggregate.command_quantity,
            last_event_at=aggregate.last_event_at,
        )
    except (TypeError, ValueError):
        aggregate_invalid = True
    if aggregate_invalid or verified is None:
        raise ContractError("CANCEL_SOURCE_AGGREGATE_INVALID")
    if verified.command_id != command.command_id:
        raise ContractError("aggregate command_id must match command")
    if verified.command_quantity != command.intent.quantity:
        raise ContractError("aggregate command_quantity must match command")
    if verified.broker_order_id is None:
        raise ContractError("cancel requires a bound broker_order_id")
    requested_at = _require_cancel_utc_datetime("as_of", as_of)
    if requested_at < command.intent.generated_at:
        raise ContractError("cancel as_of must not precede command generated_at")

    if replay is not None:
        if verified.status not in (
            OrderStatus.CANCELLING,
            OrderStatus.CANCELLED,
            OrderStatus.FILLED,
        ):
            raise ContractError("replay requires CANCELLING, CANCELLED or FILLED aggregate")
        build_cancel_command_identity(replay)
        if replay.command_id != verified.command_id:
            raise ContractError("replayed cancel command_id mismatch")
        if replay.broker_order_id != verified.broker_order_id:
            raise ContractError("replayed cancel broker_order_id mismatch")
        if replay.mode is not command.mode:
            raise ContractError("replayed cancel mode mismatch")
        if replay.observed_filled_quantity > verified.filled_quantity:
            raise ContractError("replayed cancel observes impossible filled quantity")
        observed_ids = replay.observed_event_ids
        if verified.applied_event_ids[: len(observed_ids)] != observed_ids:
            raise ContractError("replayed cancel event closure mismatch")
        if verified.last_event_at is None or verified.last_event_at < replay.observed_last_event_at:
            raise ContractError("replayed cancel last event time mismatch")
        if requested_at < verified.last_event_at:
            raise ContractError("replay as_of must not precede aggregate last_event_at")
        return replay

    if verified.status is OrderStatus.CANCELLING:
        raise ContractError("CANCELLING requires replay of the existing cancel_id")
    if verified.status not in (OrderStatus.SUBMITTED, OrderStatus.PARTIAL_FILLED):
        raise ContractError("first cancel requires SUBMITTED or PARTIAL_FILLED aggregate")
    if verified.last_event_at is None or requested_at < verified.last_event_at:
        raise ContractError("cancel as_of must not precede aggregate last_event_at")
    cancel_id = _cancel_command_digest(
        command_id=verified.command_id,
        broker_order_id=verified.broker_order_id,
        mode=command.mode,
        aggregate_status=verified.status,
        observed_filled_quantity=verified.filled_quantity,
        observed_event_ids=verified.applied_event_ids,
        observed_last_event_at=verified.last_event_at,
        as_of=requested_at,
    )
    return CancelCommand(
        cancel_id=cancel_id,
        command_id=verified.command_id,
        broker_order_id=verified.broker_order_id,
        mode=command.mode,
        aggregate_status=verified.status,
        observed_filled_quantity=verified.filled_quantity,
        observed_event_ids=verified.applied_event_ids,
        observed_last_event_at=verified.last_event_at,
        as_of=requested_at,
    )


def build_cancel_command_identity(command: CancelCommand) -> str:
    """Strictly reconstruct, then return the durable cancel-command identity."""
    if not isinstance(command, CancelCommand):
        raise TypeError("build_cancel_command_identity requires CancelCommand")
    invalid = False
    verified: CancelCommand | None = None
    try:
        verified = CancelCommand(
            cancel_id=command.cancel_id,
            command_id=command.command_id,
            broker_order_id=command.broker_order_id,
            mode=command.mode,
            aggregate_status=command.aggregate_status,
            observed_filled_quantity=command.observed_filled_quantity,
            observed_event_ids=command.observed_event_ids,
            observed_last_event_at=command.observed_last_event_at,
            as_of=command.as_of,
        )
    except Exception:
        invalid = True
    if invalid or verified is None:
        raise ContractError("CANCEL_COMMAND_INVALID")
    return verified.cancel_id


def build_execution_event(
    *,
    command: OrderCommand,
    broker_order_id: str | None,
    event_type: ExecutionEventType,
    occurred_at: dt.datetime,
    cumulative_quantity: int,
    last_quantity: int,
    last_price: Decimal | None,
    fees: Sequence[FeeComponent],
    reject_code: str | None,
) -> ExecutionEvent:
    """Build ExecutionEvent bound to a self-proving OrderCommand."""
    if not isinstance(command, OrderCommand):
        raise ContractError("command must be OrderCommand")
    return _build_execution_event_from_command(
        command,
        broker_order_id=broker_order_id,
        event_type=event_type,
        occurred_at=occurred_at,
        cumulative_quantity=cumulative_quantity,
        last_quantity=last_quantity,
        last_price=last_price,
        fees=fees,
        reject_code=reject_code,
    )


def _build_execution_event_from_command(
    command: OrderCommand,
    *,
    broker_order_id: str | None,
    event_type: ExecutionEventType,
    occurred_at: dt.datetime,
    cumulative_quantity: int,
    last_quantity: int,
    last_price: Decimal | None,
    fees: Sequence[FeeComponent],
    reject_code: str | None,
) -> ExecutionEvent:
    """Module-private builder; only accepts an already-validated OrderCommand."""
    command_id = command.command_id
    quantity = command.intent.quantity
    ordered_fees = _sorted_fees(_require_sequence_of("fees", fees, FeeComponent))
    if cumulative_quantity > quantity:
        raise ContractError("cumulative_quantity must not exceed command quantity")
    event_id = _execution_event_digest(
        command_id=command_id,
        broker_order_id=broker_order_id,
        event_type=event_type,
        occurred_at=occurred_at,
        cumulative_quantity=cumulative_quantity,
        last_quantity=last_quantity,
        last_price=last_price,
        fees=ordered_fees,
        reject_code=reject_code,
    )
    return ExecutionEvent(
        event_id=event_id,
        command_id=command_id,
        broker_order_id=broker_order_id,
        event_type=event_type,
        occurred_at=occurred_at,
        cumulative_quantity=cumulative_quantity,
        last_quantity=last_quantity,
        last_price=last_price,
        fees=ordered_fees,
        reject_code=reject_code,
    )


def build_execution_event_identity(event: ExecutionEvent) -> str:
    """Return and verify ExecutionEvent identity."""
    if not isinstance(event, ExecutionEvent):
        raise TypeError("build_execution_event_identity requires ExecutionEvent")
    digest = _execution_event_digest(
        command_id=event.command_id,
        broker_order_id=event.broker_order_id,
        event_type=event.event_type,
        occurred_at=event.occurred_at,
        cumulative_quantity=event.cumulative_quantity,
        last_quantity=event.last_quantity,
        last_price=event.last_price,
        fees=event.fees,
        reject_code=event.reject_code,
    )
    _reject_forged_identity("event_id", event.event_id, digest)
    return digest


def build_rule_decision(
    *,
    accepted: bool,
    code: str,
    normalized_quantity: int,
    normalized_limit_price: Decimal,
    rule_version: str,
) -> RuleDecision:
    """Strict RuleDecision constructor."""
    return RuleDecision(
        accepted=accepted,
        code=code,
        normalized_quantity=normalized_quantity,
        normalized_limit_price=normalized_limit_price,
        rule_version=rule_version,
    )


def build_rule_decision_identity(decision: RuleDecision) -> str:
    """Canonical identity of a RuleDecision."""
    if not isinstance(decision, RuleDecision):
        raise TypeError("build_rule_decision_identity requires RuleDecision")
    return _sha256_envelope(
        type_name="RuleDecision",
        payload=_rule_decision_payload(decision),
    )


def build_order_plan_decision(
    *,
    symbol: str,
    market: Market,
    connect_route: ConnectRoute | None,
    side: OrderSide,
    requested_quantity: int,
    accepted_quantity: int,
    rejected_quantity: int,
    zero_delta_quantity: int,
    outcome: RuleDecision,
    reason_class: OrderPlanReasonClass,
) -> OrderPlanDecision:
    """Build one strict target-level planning decision."""
    market_e = _require_enum("market", market, Market)
    route = _require_connect_route_for_market(market_e, connect_route)
    target_key = _order_plan_decision_target_digest(
        symbol=symbol,
        market=market_e,
        connect_route=route,
    )
    return OrderPlanDecision(
        target_key=target_key,
        symbol=symbol,
        market=market_e,
        connect_route=route,
        side=side,
        requested_quantity=requested_quantity,
        accepted_quantity=accepted_quantity,
        rejected_quantity=rejected_quantity,
        zero_delta_quantity=zero_delta_quantity,
        outcome=outcome,
        reason_class=reason_class,
    )


def build_order_plan(
    *,
    target_identity: str,
    market_snapshot_id: str,
    account_snapshot_id: str,
    config_identity: str,
    intent_specs: Sequence[OrderIntentSpec],
    rejections: Sequence[RuleDecision],
    residual_cash: Sequence[MoneyAmount],
    decisions: Sequence[OrderPlanDecision] = (),
) -> OrderPlan:
    """Build OrderPlan: compute plan_id, then intents bound to that plan_id."""
    target = _require_hex64("target_identity", target_identity)
    market_id = _require_hex64("market_snapshot_id", market_snapshot_id)
    account_id = _require_hex64("account_snapshot_id", account_snapshot_id)
    config_id = _require_hex64("config_identity", config_identity)
    spec_items = _require_sequence_of("intent_specs", intent_specs, OrderIntentSpec)
    rejection_items = _require_sequence_of("rejections", rejections, RuleDecision)
    cash_items = _require_sequence_of("residual_cash", residual_cash, MoneyAmount)
    decision_items = _require_sequence_of(
        "decisions", decisions, OrderPlanDecision
    )
    for spec in spec_items:
        _require_plan_intent_source_closure(
            target_identity=target,
            market_snapshot_id=market_id,
            account_snapshot_id=account_id,
            config_identity=config_id,
            intent_target_identity=spec.target_identity,
            intent_market_snapshot_id=spec.market_snapshot_id,
            intent_account_snapshot_id=spec.account_snapshot_id,
            intent_config_identity=spec.config_identity,
        )
    ordered_specs = tuple(sorted(spec_items, key=_intent_sort_key))
    ordered_rejections = rejection_items
    ordered_cash = _sorted_money(cash_items)
    ordered_decisions = tuple(sorted(decision_items, key=_plan_decision_sort_key))
    bodies = [
        _intent_body_payload(
            symbol=spec.symbol,
            market=spec.market,
            side=spec.side,
            quantity=spec.quantity,
            limit_price=spec.limit_price,
            quote_currency=spec.quote_currency,
            session_date=spec.session_date,
            generated_at=spec.generated_at,
            target_identity=spec.target_identity,
            market_snapshot_id=spec.market_snapshot_id,
            account_snapshot_id=spec.account_snapshot_id,
            config_identity=spec.config_identity,
            connect_route=spec.connect_route,
        )
        for spec in ordered_specs
    ]
    plan_id = _order_plan_digest(
        target_identity=target,
        market_snapshot_id=market_id,
        account_snapshot_id=account_id,
        config_identity=config_id,
        intent_bodies=bodies,
        rejections=ordered_rejections,
        residual_cash=ordered_cash,
        decisions=ordered_decisions,
    )
    intents = tuple(
        build_order_intent(
            plan_id=plan_id,
            symbol=spec.symbol,
            market=spec.market,
            side=spec.side,
            quantity=spec.quantity,
            limit_price=spec.limit_price,
            quote_currency=spec.quote_currency,
            session_date=spec.session_date,
            generated_at=spec.generated_at,
            target_identity=spec.target_identity,
            market_snapshot_id=spec.market_snapshot_id,
            account_snapshot_id=spec.account_snapshot_id,
            config_identity=spec.config_identity,
            connect_route=spec.connect_route,
        )
        for spec in ordered_specs
    )
    return OrderPlan(
        plan_id=plan_id,
        target_identity=target,
        market_snapshot_id=market_id,
        account_snapshot_id=account_id,
        config_identity=config_id,
        intents=intents,
        rejections=ordered_rejections,
        residual_cash=ordered_cash,
        decisions=ordered_decisions,
    )


def build_order_plan_identity(plan: OrderPlan) -> str:
    """Return and verify OrderPlan identity."""
    if not isinstance(plan, OrderPlan):
        raise TypeError("build_order_plan_identity requires OrderPlan")
    digest = _order_plan_digest(
        target_identity=plan.target_identity,
        market_snapshot_id=plan.market_snapshot_id,
        account_snapshot_id=plan.account_snapshot_id,
        config_identity=plan.config_identity,
        intent_bodies=[
            _intent_body_payload(
                symbol=item.symbol,
                market=item.market,
                side=item.side,
                quantity=item.quantity,
                limit_price=item.limit_price,
                quote_currency=item.quote_currency,
                session_date=item.session_date,
                generated_at=item.generated_at,
                target_identity=item.target_identity,
                market_snapshot_id=item.market_snapshot_id,
                account_snapshot_id=item.account_snapshot_id,
                config_identity=item.config_identity,
                connect_route=item.connect_route,
            )
            for item in plan.intents
        ],
        rejections=plan.rejections,
        residual_cash=plan.residual_cash,
        decisions=plan.decisions,
    )
    _reject_forged_identity("plan_id", plan.plan_id, digest)
    return digest


__all__ = [
    "AccountSnapshot",
    "CashBalance",
    "CancelCommand",
    "ContractError",
    "ExecutionEvent",
    "FeeComponent",
    "MoneyAmount",
    "OrderCommand",
    "OrderIntent",
    "OrderIntentSpec",
    "OrderPlan",
    "OrderPlanDecision",
    "OrderPlanReasonClass",
    "PositionBalance",
    "RuleDecision",
    "SymbolMarketState",
    "VerifiedConnectMarketContext",
    "VerifiedMarketSnapshot",
    "build_account_snapshot",
    "build_account_snapshot_identity",
    "build_cash_balance",
    "build_cash_balance_identity",
    "build_cancel_command",
    "build_cancel_command_identity",
    "build_execution_event",
    "build_execution_event_identity",
    "build_fee_component",
    "build_fee_component_identity",
    "build_money_amount",
    "build_money_amount_identity",
    "build_order_command",
    "build_order_command_identity",
    "build_order_intent",
    "build_order_intent_identity",
    "build_order_plan",
    "build_order_plan_decision",
    "build_order_plan_identity",
    "build_position_balance",
    "build_position_balance_identity",
    "build_rule_decision",
    "build_rule_decision_identity",
    "build_symbol_market_state",
    "build_symbol_market_state_identity",
    "build_verified_connect_market_context",
    "build_verified_connect_market_context_identity",
    "build_verified_market_snapshot",
    "build_verified_market_snapshot_identity",
]
