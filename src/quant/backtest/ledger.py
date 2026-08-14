"""Pure multi-currency trade, settlement, and corporate-action ledger.

Settlement dates are selected only from exact, identity-bound session tuples.
This module performs no I/O and does not infer calendars from natural days.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import dataclass, fields, replace
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from typing import Literal, NoReturn, cast

from quant.backtest.corporate_actions import (
    EntitlementPosition,
    EntitlementPosting,
    EntitlementTransition,
)
from quant.backtest.fx import (
    FxSnapshot,
    convert_money,
    require_fx_snapshot_current,
)
from quant.domain.enums import (
    Currency,
    EntitlementLegState,
    EntitlementPostingType,
    ExecutionEventType,
    ExecutionMode,
    Market,
    OrderSide,
)
from quant.execution.contracts import (
    AccountSnapshot,
    CashBalance,
    ExecutionEvent,
    OrderCommand,
    PositionBalance,
    build_account_snapshot_identity,
    build_cash_balance,
    build_execution_event_identity,
    build_money_amount,
    build_order_command_identity,
    build_order_intent_identity,
    build_position_balance,
)

_HEX = frozenset("0123456789abcdef")
_CENT = Decimal("0.01")
_HASH_VERSION = "m4-ledger-v1"

PendingKind = Literal[
    "BUY_CASH_PAYABLE",
    "BUY_POSITION_RECEIVABLE",
    "BUY_SELLABLE_UNLOCK",
    "SELL_CASH_RECEIVABLE",
    "SELL_POSITION_PAYABLE",
]
_PENDING_KINDS = frozenset(
    {
        "BUY_CASH_PAYABLE",
        "BUY_POSITION_RECEIVABLE",
        "BUY_SELLABLE_UNLOCK",
        "SELL_CASH_RECEIVABLE",
        "SELL_POSITION_PAYABLE",
    }
)


class LedgerError(ValueError):
    """Stable fail-closed B5 contract error."""


def _fail(code: str) -> NoReturn:
    raise LedgerError(code)


def _is_hex64(value: object) -> bool:
    return (
        type(value) is str
        and len(cast(str, value)) == 64
        and set(cast(str, value)).issubset(_HEX)
    )


def _is_utc_datetime(value: object) -> bool:
    if type(value) is not dt.datetime:
        return False
    valid = False
    try:
        checked = cast(dt.datetime, value)
        valid = (
            checked.tzinfo is not None
            and checked.utcoffset() == dt.timedelta(0)
        )
    except Exception:
        valid = False
    return valid


def _normalize_utc_datetime(value: object) -> dt.datetime:
    if not _is_utc_datetime(value):
        _fail("LEDGER_INPUT_INVALID")
    normalized: dt.datetime | None = None
    failed = False
    try:
        normalized = cast(dt.datetime, value).astimezone(dt.UTC)
    except Exception:
        failed = True
    if failed or normalized is None:
        _fail("LEDGER_INPUT_INVALID")
    return normalized


def _canon(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        if not value.is_finite():
            _fail("LEDGER_INPUT_INVALID")
        return format(value, "f")
    if isinstance(value, (dt.datetime, dt.date)):
        return value.isoformat()
    if isinstance(value, tuple):
        return [_canon(item) for item in value]
    if isinstance(value, dict):
        if any(type(key) is not str for key in value):
            _fail("LEDGER_INPUT_INVALID")
        return {cast(str, key): _canon(item) for key, item in value.items()}
    if hasattr(value, "__dataclass_fields__"):
        return {
            field.name: _canon(getattr(value, field.name))
            for field in fields(value)  # type: ignore[arg-type]
        }
    if value is None or type(value) in {str, int, bool}:
        return value
    _fail("LEDGER_INPUT_INVALID")


def _identity(type_name: str, payload: object) -> str:
    encoded = json.dumps(
        {
            "hash_version": _HASH_VERSION,
            "type": type_name,
            "payload": _canon(payload),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _prove_external(prover: object, subject: object, code: str) -> None:
    failed = False
    try:
        cast(object, prover)(subject)  # type: ignore[operator]
    except Exception:
        failed = True
    if failed:
        _fail(code)


@dataclass(frozen=True, slots=True)
class SettlementRule:
    """Versioned rule and exact eligible session domains."""

    rule_id: str
    selector: str
    market: Market
    quote_currency: Currency
    settlement_currency: Currency
    effective_from: dt.date
    effective_to: dt.date | None
    trading_sessions: tuple[dt.date, ...]
    settlement_sessions: tuple[dt.date, ...]
    trading_calendar_source_identity: str
    settlement_calendar_source_identity: str
    settlement_lag_sessions: int
    sellable_lag_sessions: int
    reuse_sell_receivables: bool

    def __post_init__(self) -> None:
        _validate_rule(self)
        if self.rule_id != _rule_identity(self):
            _fail("LEDGER_IDENTITY_INVALID")


def _rule_payload(rule: SettlementRule) -> dict[str, object]:
    return {
        field.name: getattr(rule, field.name)
        for field in fields(rule)
        if field.name != "rule_id"
    }


def _rule_identity(rule: SettlementRule) -> str:
    return _identity("SettlementRule", _rule_payload(rule))


def _validate_rule(rule: SettlementRule) -> None:
    sessions = (rule.trading_sessions, rule.settlement_sessions)
    if (
        type(rule.selector) is not str
        or not rule.selector
        or any(char in "/\\:%" or ord(char) < 32 or ord(char) == 127 for char in rule.selector)
        or type(rule.market) is not Market
        or type(rule.quote_currency) is not Currency
        or type(rule.settlement_currency) is not Currency
        or type(rule.effective_from) is not dt.date
        or (rule.effective_to is not None and type(rule.effective_to) is not dt.date)
        or (rule.effective_to is not None and rule.effective_to < rule.effective_from)
        or any(
            type(items) is not tuple
            or not items
            or any(type(day) is not dt.date for day in items)
            or tuple(sorted(set(items))) != items
            for items in sessions
        )
        or not _is_hex64(rule.trading_calendar_source_identity)
        or not _is_hex64(rule.settlement_calendar_source_identity)
        or type(rule.settlement_lag_sessions) is not int
        or rule.settlement_lag_sessions < 0
        or type(rule.sellable_lag_sessions) is not int
        or rule.sellable_lag_sessions < 0
        or type(rule.reuse_sell_receivables) is not bool
    ):
        _fail("LEDGER_RULE_INVALID")
    if rule.market in {Market.SH, Market.SZ}:
        if (
            rule.quote_currency is not Currency.CNY
            or rule.settlement_currency is not Currency.CNY
            or rule.sellable_lag_sessions != 1
        ):
            _fail("LEDGER_RULE_INVALID")
    elif rule.market is Market.HK:
        if (
            rule.quote_currency is not Currency.HKD
            or rule.settlement_currency is not Currency.CNY
            or rule.sellable_lag_sessions != 0
            or rule.settlement_lag_sessions != 2
        ):
            _fail("LEDGER_RULE_INVALID")
    else:
        _fail("LEDGER_RULE_INVALID")


def build_settlement_rule(
    *,
    selector: str,
    market: Market,
    quote_currency: Currency,
    settlement_currency: Currency,
    effective_from: dt.date,
    effective_to: dt.date | None,
    trading_sessions: tuple[dt.date, ...],
    settlement_sessions: tuple[dt.date, ...],
    trading_calendar_source_identity: str,
    settlement_calendar_source_identity: str,
    settlement_lag_sessions: int,
    sellable_lag_sessions: int,
    reuse_sell_receivables: bool,
) -> SettlementRule:
    """Build a rule whose identity covers the exact eligible sessions."""
    provisional = SettlementRule.__new__(SettlementRule)
    values = {
        "selector": selector,
        "market": market,
        "quote_currency": quote_currency,
        "settlement_currency": settlement_currency,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "trading_sessions": trading_sessions,
        "settlement_sessions": settlement_sessions,
        "trading_calendar_source_identity": trading_calendar_source_identity,
        "settlement_calendar_source_identity": settlement_calendar_source_identity,
        "settlement_lag_sessions": settlement_lag_sessions,
        "sellable_lag_sessions": sellable_lag_sessions,
        "reuse_sell_receivables": reuse_sell_receivables,
    }
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    object.__setattr__(provisional, "rule_id", "0" * 64)
    _validate_rule(provisional)
    return SettlementRule(
        rule_id=_rule_identity(provisional),
        selector=selector,
        market=market,
        quote_currency=quote_currency,
        settlement_currency=settlement_currency,
        effective_from=effective_from,
        effective_to=effective_to,
        trading_sessions=trading_sessions,
        settlement_sessions=settlement_sessions,
        trading_calendar_source_identity=trading_calendar_source_identity,
        settlement_calendar_source_identity=settlement_calendar_source_identity,
        settlement_lag_sessions=settlement_lag_sessions,
        sellable_lag_sessions=sellable_lag_sessions,
        reuse_sell_receivables=reuse_sell_receivables,
    )


@dataclass(frozen=True, slots=True)
class PendingSettlement:
    pending_id: str
    source_event_id: str
    kind: PendingKind
    due_session: dt.date
    currency: Currency
    amount: Decimal
    market: Market
    symbol: str
    quantity: int

    def __post_init__(self) -> None:
        if (
            not _is_hex64(self.pending_id)
            or not _is_hex64(self.source_event_id)
            or self.kind not in _PENDING_KINDS
            or type(self.due_session) is not dt.date
            or type(self.currency) is not Currency
            or type(self.amount) is not Decimal
            or not self.amount.is_finite()
            or self.amount < 0
            or type(self.market) is not Market
            or type(self.symbol) is not str
            or not self.symbol
            or type(self.quantity) is not int
            or self.quantity < 0
            or (("CASH" in self.kind) != (self.amount > 0))
            or (("POSITION" in self.kind or "SELLABLE" in self.kind) != (self.quantity > 0))
            or self.pending_id != _pending_identity(self)
        ):
            _fail("LEDGER_IDENTITY_INVALID")


def _pending_payload(item: PendingSettlement) -> dict[str, object]:
    return {field.name: getattr(item, field.name) for field in fields(item) if field.name != "pending_id"}


def _pending_identity(item: PendingSettlement) -> str:
    return _identity("PendingSettlement", _pending_payload(item))


def _build_pending(
    *, source_event_id: str, kind: PendingKind, due_session: dt.date,
    currency: Currency, amount: Decimal, market: Market, symbol: str, quantity: int,
) -> PendingSettlement:
    provisional = PendingSettlement.__new__(PendingSettlement)
    values = {
        "source_event_id": source_event_id,
        "kind": kind,
        "due_session": due_session,
        "currency": currency,
        "amount": amount,
        "market": market,
        "symbol": symbol,
        "quantity": quantity,
    }
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    object.__setattr__(provisional, "pending_id", "0" * 64)
    return PendingSettlement(
        pending_id=_pending_identity(provisional),
        source_event_id=source_event_id,
        kind=kind,
        due_session=due_session,
        currency=currency,
        amount=amount,
        market=market,
        symbol=symbol,
        quantity=quantity,
    )


@dataclass(frozen=True, slots=True)
class TradingCreditLot:
    credit_id: str
    source_event_id: str
    due_session: dt.date
    currency: Currency
    original_amount: Decimal
    remaining_amount: Decimal

    def __post_init__(self) -> None:
        if (
            not _is_hex64(self.credit_id)
            or not _is_hex64(self.source_event_id)
            or type(self.due_session) is not dt.date
            or type(self.currency) is not Currency
            or any(
                type(value) is not Decimal or not value.is_finite() or value < 0
                for value in (self.original_amount, self.remaining_amount)
            )
            or self.original_amount <= 0
            or self.remaining_amount > self.original_amount
            or self.credit_id != _credit_identity(self)
        ):
            _fail("LEDGER_IDENTITY_INVALID")


def _credit_identity(item: TradingCreditLot) -> str:
    return _identity(
        "TradingCreditLot",
        {
            "source_event_id": item.source_event_id,
            "due_session": item.due_session,
            "currency": item.currency,
            "original_amount": item.original_amount,
        },
    )


def _build_credit(event_id: str, due: dt.date, currency: Currency, amount: Decimal) -> TradingCreditLot:
    provisional = TradingCreditLot.__new__(TradingCreditLot)
    object.__setattr__(provisional, "credit_id", "0" * 64)
    object.__setattr__(provisional, "source_event_id", event_id)
    object.__setattr__(provisional, "due_session", due)
    object.__setattr__(provisional, "currency", currency)
    object.__setattr__(provisional, "original_amount", amount)
    object.__setattr__(provisional, "remaining_amount", amount)
    return TradingCreditLot(
        _credit_identity(provisional), event_id, due, currency, amount, amount
    )


@dataclass(frozen=True, slots=True)
class AppliedAction:
    logical_key: str
    payload_identity: str

    def __post_init__(self) -> None:
        if type(self.logical_key) is not str or not self.logical_key or not _is_hex64(self.payload_identity):
            _fail("LEDGER_INPUT_INVALID")


@dataclass(frozen=True, slots=True)
class CommandProjection:
    command_id: str
    cumulative_quantity: int
    broker_order_id: str | None
    last_event_at: dt.datetime
    settlement_rule_id: str

    def __post_init__(self) -> None:
        if (
            not _is_hex64(self.command_id)
            or type(self.cumulative_quantity) is not int
            or self.cumulative_quantity < 0
            or (
                self.broker_order_id is not None
                and (
                    type(self.broker_order_id) is not str
                    or not self.broker_order_id
                )
            )
            or not _is_utc_datetime(self.last_event_at)
            or not _is_hex64(self.settlement_rule_id)
        ):
            _fail("LEDGER_INPUT_INVALID")


@dataclass(frozen=True, slots=True)
class LedgerState:
    state_id: str
    origin_account_snapshot_id: str
    as_of_date: dt.date
    positions: tuple[PositionBalance, ...]
    cash: tuple[CashBalance, ...]
    pending: tuple[PendingSettlement, ...]
    trading_credits: tuple[TradingCreditLot, ...]
    entitlements: tuple[EntitlementPosition, ...]
    applied_event_ids: tuple[str, ...]
    applied_actions: tuple[AppliedAction, ...]
    command_projections: tuple[CommandProjection, ...]

    def __post_init__(self) -> None:
        _validate_state(self)
        if self.state_id != _state_identity(self):
            _fail("LEDGER_IDENTITY_INVALID")


def _state_payload(state: LedgerState) -> dict[str, object]:
    return {field.name: getattr(state, field.name) for field in fields(state) if field.name != "state_id"}


def _state_identity(state: LedgerState) -> str:
    return _identity("LedgerState", _state_payload(state))


def _validate_state(state: LedgerState) -> None:
    if (
        not _is_hex64(state.origin_account_snapshot_id)
        or type(state.as_of_date) is not dt.date
        or type(state.positions) is not tuple
        or any(type(item) is not PositionBalance for item in state.positions)
        or state.positions != tuple(sorted(state.positions, key=lambda item: (item.market.value, item.symbol)))
        or len({(item.market, item.symbol) for item in state.positions}) != len(state.positions)
        or type(state.cash) is not tuple
        or any(type(item) is not CashBalance for item in state.cash)
        or state.cash != tuple(sorted(state.cash, key=lambda item: item.currency.value))
        or len({item.currency for item in state.cash}) != len(state.cash)
        or type(state.pending) is not tuple
        or any(type(item) is not PendingSettlement for item in state.pending)
        or state.pending != tuple(sorted(state.pending, key=lambda item: (item.due_session, item.kind, item.pending_id)))
        or len({item.pending_id for item in state.pending}) != len(state.pending)
        or type(state.trading_credits) is not tuple
        or any(type(item) is not TradingCreditLot for item in state.trading_credits)
        or state.trading_credits != tuple(sorted(state.trading_credits, key=lambda item: (item.due_session, item.credit_id)))
        or len({item.credit_id for item in state.trading_credits}) != len(state.trading_credits)
        or type(state.entitlements) is not tuple
        or any(type(item) is not EntitlementPosition for item in state.entitlements)
        or state.entitlements != tuple(sorted(state.entitlements, key=lambda item: item.event_id))
        or len({item.event_id for item in state.entitlements}) != len(state.entitlements)
        or type(state.applied_event_ids) is not tuple
        or state.applied_event_ids != tuple(sorted(set(state.applied_event_ids)))
        or any(not _is_hex64(item) for item in state.applied_event_ids)
        or type(state.applied_actions) is not tuple
        or state.applied_actions != tuple(sorted(state.applied_actions, key=lambda item: item.logical_key))
        or len({item.logical_key for item in state.applied_actions}) != len(state.applied_actions)
        or type(state.command_projections) is not tuple
        or any(type(item) is not CommandProjection for item in state.command_projections)
        or state.command_projections != tuple(sorted(state.command_projections, key=lambda item: item.command_id))
        or len({item.command_id for item in state.command_projections}) != len(state.command_projections)
    ):
        _fail("LEDGER_INPUT_INVALID")


def _make_state(**values: object) -> LedgerState:
    provisional = LedgerState.__new__(LedgerState)
    object.__setattr__(provisional, "state_id", "0" * 64)
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    return LedgerState(state_id=_state_identity(provisional), **values)  # type: ignore[arg-type]


def build_ledger_state(account: AccountSnapshot, *, as_of_date: dt.date) -> LedgerState:
    """Open an identity-bound ledger from a proven account snapshot."""
    _prove_external(build_account_snapshot_identity, account, "LEDGER_IDENTITY_INVALID")
    if type(as_of_date) is not dt.date:
        _fail("LEDGER_INPUT_INVALID")
    # Market-local accounting-day conversion is not frozen yet.  Until that
    # SSOT exists, the only deterministic lower bound is the UTC snapshot date.
    if as_of_date < account.as_of.date():
        _fail("LEDGER_BACKDATED")
    return _make_state(
        origin_account_snapshot_id=account.snapshot_id,
        as_of_date=as_of_date,
        positions=account.positions,
        cash=account.cash,
        pending=(),
        trading_credits=(),
        entitlements=(),
        applied_event_ids=(),
        applied_actions=(),
        command_projections=(),
    )


@dataclass(frozen=True, slots=True)
class LedgerEntry:
    entry_id: str
    source_type: str
    source_id: str
    kind: str
    effective_date: dt.date
    currency: Currency | None = None
    settled_delta: Decimal = Decimal(0)
    available_delta: Decimal = Decimal(0)
    receivable_delta: Decimal = Decimal(0)
    payable_delta: Decimal = Decimal(0)
    credit_delta: Decimal = Decimal(0)
    market: Market | None = None
    symbol: str | None = None
    quantity_delta: int = 0
    sellable_delta: int = 0
    pending_id: str | None = None
    pending_action: str | None = None
    rounding_delta: Decimal = Decimal(0)

    def __post_init__(self) -> None:
        decimals = (
            self.settled_delta, self.available_delta, self.receivable_delta,
            self.payable_delta, self.credit_delta, self.rounding_delta,
        )
        if (
            not _is_hex64(self.entry_id)
            or type(self.source_type) is not str
            or self.source_type not in {"EXECUTION", "CORPORATE_ACTION", "ADVANCE"}
            or not _is_hex64(self.source_id)
            or type(self.kind) is not str
            or not self.kind
            or type(self.effective_date) is not dt.date
            or (self.currency is not None and type(self.currency) is not Currency)
            or any(type(item) is not Decimal or not item.is_finite() for item in decimals)
            or (self.market is not None and type(self.market) is not Market)
            or (self.symbol is not None and (type(self.symbol) is not str or not self.symbol))
            or type(self.quantity_delta) is not int
            or type(self.sellable_delta) is not int
            or (self.pending_id is not None and not _is_hex64(self.pending_id))
            or self.pending_action not in {None, "ADD", "REMOVE"}
            or self.entry_id != _entry_identity(self)
        ):
            _fail("LEDGER_IDENTITY_INVALID")


def _entry_identity(entry: LedgerEntry) -> str:
    return _identity(
        "LedgerEntry",
        {field.name: getattr(entry, field.name) for field in fields(entry) if field.name != "entry_id"},
    )


def _entry(**values: object) -> LedgerEntry:
    complete: dict[str, object] = {
        "currency": None,
        "settled_delta": Decimal(0),
        "available_delta": Decimal(0),
        "receivable_delta": Decimal(0),
        "payable_delta": Decimal(0),
        "credit_delta": Decimal(0),
        "market": None,
        "symbol": None,
        "quantity_delta": 0,
        "sellable_delta": 0,
        "pending_id": None,
        "pending_action": None,
        "rounding_delta": Decimal(0),
    }
    complete.update(values)
    provisional = LedgerEntry.__new__(LedgerEntry)
    object.__setattr__(provisional, "entry_id", "0" * 64)
    for name, value in complete.items():
        object.__setattr__(provisional, name, value)
    return LedgerEntry(entry_id=_entry_identity(provisional), **complete)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class LedgerTransition:
    transition_id: str
    previous_state_id: str
    state: LedgerState
    entries: tuple[LedgerEntry, ...]
    no_op: bool

    def __post_init__(self) -> None:
        if (
            not _is_hex64(self.transition_id)
            or not _is_hex64(self.previous_state_id)
            or type(self.state) is not LedgerState
            or type(self.entries) is not tuple
            or any(type(item) is not LedgerEntry for item in self.entries)
            or type(self.no_op) is not bool
            or self.no_op != (not self.entries and self.previous_state_id == self.state.state_id)
            or self.transition_id != _transition_identity(self)
        ):
            _fail("LEDGER_IDENTITY_INVALID")


def _transition_identity(item: LedgerTransition) -> str:
    return _identity(
        "LedgerTransition",
        {
            "previous_state_id": item.previous_state_id,
            "state_id": item.state.state_id,
            "entry_ids": tuple(entry.entry_id for entry in item.entries),
            "no_op": item.no_op,
        },
    )


def _transition(before: LedgerState, after: LedgerState, entries: tuple[LedgerEntry, ...]) -> LedgerTransition:
    _assert_transition_conservation(before, after, entries)
    no_op = not entries and before == after
    provisional = LedgerTransition.__new__(LedgerTransition)
    object.__setattr__(provisional, "transition_id", "0" * 64)
    object.__setattr__(provisional, "previous_state_id", before.state_id)
    object.__setattr__(provisional, "state", after)
    object.__setattr__(provisional, "entries", entries)
    object.__setattr__(provisional, "no_op", no_op)
    return LedgerTransition(
        _transition_identity(provisional), before.state_id, after, entries, no_op
    )


def _assert_transition_conservation(
    before: LedgerState, after: LedgerState, entries: tuple[LedgerEntry, ...]
) -> None:
    currencies = {item.currency for item in before.cash} | {
        item.currency for item in after.cash
    }
    before_cash = _cash_map(before)
    after_cash = _cash_map(after)
    for currency in currencies:
        old = before_cash.get(currency, _zero_cash(currency))
        new = after_cash.get(currency, _zero_cash(currency))
        related = tuple(item for item in entries if item.currency is currency)
        expected = (
            sum((item.settled_delta for item in related), Decimal(0)),
            sum((item.available_delta for item in related), Decimal(0)),
            sum((item.receivable_delta for item in related), Decimal(0)),
            sum((item.payable_delta for item in related), Decimal(0)),
        )
        actual = (
            new.settled - old.settled,
            new.available - old.available,
            new.receivable - old.receivable,
            new.payable - old.payable,
        )
        if actual != expected:
            _fail("LEDGER_CONSERVATION_FAILED")
    position_keys = {(item.market, item.symbol) for item in before.positions} | {
        (item.market, item.symbol) for item in after.positions
    }
    before_positions = {(item.market, item.symbol): item for item in before.positions}
    after_positions = {(item.market, item.symbol): item for item in after.positions}
    for key in position_keys:
        old_position = before_positions.get(key)
        new_position = after_positions.get(key)
        related = tuple(
            item for item in entries if (item.market, item.symbol) == key
        )
        if (
            (0 if new_position is None else new_position.quantity)
            - (0 if old_position is None else old_position.quantity)
            != sum(item.quantity_delta for item in related)
            or (0 if new_position is None else new_position.sellable_quantity)
            - (0 if old_position is None else old_position.sellable_quantity)
            != sum(item.sellable_delta for item in related)
        ):
            _fail("LEDGER_CONSERVATION_FAILED")
    credit_currencies = {item.currency for item in before.trading_credits} | {
        item.currency for item in after.trading_credits
    }
    for currency in credit_currencies:
        actual_credit = sum(
            (
                item.remaining_amount
                for item in after.trading_credits
                if item.currency is currency
            ),
            Decimal(0),
        ) - sum(
            (
                item.remaining_amount
                for item in before.trading_credits
                if item.currency is currency
            ),
            Decimal(0),
        )
        expected_credit = sum(
            (item.credit_delta for item in entries if item.currency is currency),
            Decimal(0),
        )
        if actual_credit != expected_credit:
            _fail("LEDGER_CONSERVATION_FAILED")
    pending_counts = {item.pending_id: 1 for item in before.pending}
    for entry in entries:
        if entry.pending_id is None:
            continue
        pending_counts[entry.pending_id] = pending_counts.get(entry.pending_id, 0) + (
            1 if entry.pending_action == "ADD" else -1
        )
    if {key for key, count in pending_counts.items() if count == 1} != {
        item.pending_id for item in after.pending
    } or any(count not in {0, 1} for count in pending_counts.values()):
        _fail("LEDGER_CONSERVATION_FAILED")


def _prove_state(state: LedgerState) -> None:
    if type(state) is not LedgerState:
        _fail("LEDGER_INPUT_INVALID")
    _validate_state(state)
    if state.state_id != _state_identity(state):
        _fail("LEDGER_IDENTITY_INVALID")


def _cash_map(state: LedgerState) -> dict[Currency, CashBalance]:
    return {item.currency: item for item in state.cash}


def _zero_cash(currency: Currency) -> CashBalance:
    return build_cash_balance(currency=currency, settled=Decimal(0), available=Decimal(0), receivable=Decimal(0), payable=Decimal(0))


def _update_cash(
    cash: dict[Currency, CashBalance], currency: Currency, *,
    settled: Decimal = Decimal(0), available: Decimal = Decimal(0),
    receivable: Decimal = Decimal(0), payable: Decimal = Decimal(0),
    error: str = "LEDGER_CONSERVATION_FAILED",
) -> None:
    current = cash.get(currency, _zero_cash(currency))
    values = (
        current.settled + settled,
        current.available + available,
        current.receivable + receivable,
        current.payable + payable,
    )
    if any(item < 0 for item in values) or values[1] > values[0]:
        _fail(error)
    cash[currency] = build_cash_balance(
        currency=currency, settled=values[0], available=values[1],
        receivable=values[2], payable=values[3],
    )


def _nth_session(session: dt.date, domain: tuple[dt.date, ...], lag: int) -> dt.date:
    if session not in domain:
        _fail("LEDGER_RULE_INVALID")
    if lag == 0:
        return session
    future = tuple(day for day in domain if day > session)
    if len(future) < lag:
        _fail("LEDGER_CALENDAR_INCOMPLETE")
    return future[lag - 1]


def _replace_state(state: LedgerState, **changes: object) -> LedgerState:
    values = _state_payload(state)
    values.update(changes)
    return _make_state(**values)


def advance_ledger_state(state: LedgerState, *, through_date: dt.date) -> LedgerTransition:
    """Mature only already-frozen due sessions; never calculate a new due date."""
    _prove_state(state)
    if type(through_date) is not dt.date:
        _fail("LEDGER_INPUT_INVALID")
    if through_date < state.as_of_date:
        _fail("LEDGER_BACKDATED")
    due = tuple(item for item in state.pending if item.due_session <= through_date)
    if not due:
        if through_date == state.as_of_date:
            return _transition(state, state, ())
        after = _replace_state(state, as_of_date=through_date)
        marker = _entry(
            source_type="ADVANCE", source_id=_identity("Advance", {"from": state.as_of_date, "to": through_date}),
            kind="ADVANCE_DATE", effective_date=through_date,
        )
        return _transition(state, after, (marker,))

    order = {
        "SELL_CASH_RECEIVABLE": 0,
        "BUY_CASH_PAYABLE": 1,
        "BUY_POSITION_RECEIVABLE": 2,
        "SELL_POSITION_PAYABLE": 3,
        "BUY_SELLABLE_UNLOCK": 4,
    }
    pending = list(state.pending)
    credits = list(state.trading_credits)
    cash = _cash_map(state)
    positions = {(item.market, item.symbol): item for item in state.positions}
    entries: list[LedgerEntry] = []
    advance_id = _identity("Advance", {"from": state.as_of_date, "to": through_date})
    for item in sorted(due, key=lambda value: (value.due_session, order[value.kind], value.pending_id)):
        pending.remove(item)
        common = dict(
            source_type="ADVANCE", source_id=advance_id, effective_date=item.due_session,
            currency=item.currency, market=item.market, symbol=item.symbol,
            pending_id=item.pending_id, pending_action="REMOVE",
        )
        if item.kind == "SELL_CASH_RECEIVABLE":
            lot = next((credit for credit in credits if credit.source_event_id == item.source_event_id), None)
            remaining = item.amount if lot is None else lot.remaining_amount
            credit_delta = Decimal(0) if lot is None else -remaining
            if lot is not None:
                credits.remove(lot)
            _update_cash(cash, item.currency, settled=item.amount, available=remaining, receivable=-item.amount)
            entries.append(_entry(kind="SETTLE_SELL_CASH", settled_delta=item.amount, available_delta=remaining, receivable_delta=-item.amount, credit_delta=credit_delta, **common))
        elif item.kind == "BUY_CASH_PAYABLE":
            _update_cash(cash, item.currency, settled=-item.amount, payable=-item.amount)
            entries.append(_entry(kind="SETTLE_BUY_CASH", settled_delta=-item.amount, payable_delta=-item.amount, **common))
        elif item.kind == "BUY_SELLABLE_UNLOCK":
            key = (item.market, item.symbol)
            position = positions.get(key)
            if position is None or position.sellable_quantity + item.quantity > position.quantity:
                _fail("LEDGER_CONSERVATION_FAILED")
            positions[key] = build_position_balance(
                symbol=position.symbol, market=position.market, quantity=position.quantity,
                sellable_quantity=position.sellable_quantity + item.quantity, avg_cost=position.avg_cost,
            )
            entries.append(_entry(kind="UNLOCK_POSITION", quantity_delta=0, sellable_delta=item.quantity, **common))
        else:
            entries.append(_entry(kind="SETTLE_POSITION_MEMO", **common))
    after = _replace_state(
        state,
        as_of_date=through_date,
        positions=tuple(sorted(positions.values(), key=lambda item: (item.market.value, item.symbol))),
        cash=tuple(sorted(cash.values(), key=lambda item: item.currency.value)),
        pending=tuple(sorted(pending, key=lambda item: (item.due_session, item.kind, item.pending_id))),
        trading_credits=tuple(sorted(credits, key=lambda item: (item.due_session, item.credit_id))),
    )
    return _transition(state, after, tuple(entries))


def _prove_command_event(command: OrderCommand, event: ExecutionEvent) -> None:
    if type(command) is not OrderCommand or type(event) is not ExecutionEvent:
        _fail("LEDGER_INPUT_INVALID")
    _prove_external(build_order_intent_identity, command.intent, "LEDGER_IDENTITY_INVALID")
    _prove_external(build_order_command_identity, command, "LEDGER_IDENTITY_INVALID")
    _prove_external(build_execution_event_identity, event, "LEDGER_IDENTITY_INVALID")
    if event.command_id != command.command_id:
        _fail("LEDGER_EVENT_COMMAND_MISMATCH")
    if event.occurred_at < command.intent.generated_at:
        _fail("LEDGER_INPUT_INVALID")


def _prove_rule_for_event(rule: SettlementRule, command: OrderCommand) -> None:
    if type(rule) is not SettlementRule:
        _fail("LEDGER_RULE_INVALID")
    _validate_rule(rule)
    if rule.rule_id != _rule_identity(rule):
        _fail("LEDGER_IDENTITY_INVALID")
    intent = command.intent
    if (
        rule.market is not intent.market
        or rule.quote_currency is not intent.quote_currency
        or intent.session_date < rule.effective_from
        or (rule.effective_to is not None and intent.session_date > rule.effective_to)
        or intent.session_date not in rule.trading_sessions
    ):
        _fail("LEDGER_RULE_INVALID")


def _settlement_notional(
    command: OrderCommand, event: ExecutionEvent, rule: SettlementRule, fx: FxSnapshot | None,
) -> Decimal:
    assert event.last_price is not None
    source = build_money_amount(command.intent.quote_currency, event.last_price * event.last_quantity)
    if rule.quote_currency is rule.settlement_currency:
        if fx is not None:
            _fail("LEDGER_INPUT_INVALID")
        return source.amount
    if fx is None:
        _fail("FX_INPUT_INVALID")
    failed_code: str | None = None
    result: Decimal | None = None
    try:
        current = require_fx_snapshot_current(
            fx, session_date=command.intent.session_date, at=event.occurred_at
        )
        result = convert_money(source, current, rule.settlement_currency).amount
    except Exception as error:
        candidate = str(error)
        failed_code = (
            candidate
            if candidate in {"FX_INPUT_INVALID", "FX_SNAPSHOT_EXPIRED", "FX_RATE_MISSING"}
            else "LEDGER_INPUT_INVALID"
        )
    if failed_code is not None:
        _fail(failed_code)
    if result is None:
        _fail("LEDGER_INPUT_INVALID")
    return result


def _fees(event: ExecutionEvent, currency: Currency) -> Decimal:
    if any(item.amount.currency is not currency for item in event.fees):
        _fail("LEDGER_INPUT_INVALID")
    return sum((item.amount.amount for item in event.fees), Decimal(0))


def apply_execution_event(
    state: LedgerState,
    command: OrderCommand,
    event: ExecutionEvent,
    settlement_rule: SettlementRule,
    fx: FxSnapshot | None,
) -> LedgerTransition:
    """Apply one proven incremental event and freeze all future due sessions."""
    _prove_state(state)
    _prove_command_event(command, event)
    _prove_rule_for_event(settlement_rule, command)
    projection_by_command = {
        item.command_id: item for item in state.command_projections
    }
    projection = projection_by_command.get(command.command_id)
    existing_broker_order_id = (
        None if projection is None else projection.broker_order_id
    )
    if (
        existing_broker_order_id is not None
        and event.broker_order_id is not None
        and event.broker_order_id != existing_broker_order_id
    ):
        _fail("LEDGER_EVENT_PROJECTION_CONFLICT")
    resolved_broker_order_id = existing_broker_order_id or event.broker_order_id
    if event.event_id in state.applied_event_ids:
        if (
            projection is not None
            and settlement_rule.rule_id != projection.settlement_rule_id
        ):
            _fail("LEDGER_EVENT_PROJECTION_CONFLICT")
        return _transition(state, state, ())
    processing_date = max(state.as_of_date, command.intent.session_date)
    advanced = advance_ledger_state(state, through_date=processing_date)
    current = advanced.state
    projection_by_command = {
        item.command_id: item for item in current.command_projections
    }
    projection = projection_by_command.get(command.command_id)
    if projection is not None and (
        event.occurred_at < projection.last_event_at
        or settlement_rule.rule_id != projection.settlement_rule_id
    ):
        _fail("LEDGER_EVENT_PROJECTION_CONFLICT")
    prior = 0 if projection is None else projection.cumulative_quantity
    fill = event.event_type in {ExecutionEventType.PARTIAL_FILL, ExecutionEventType.FILL}
    if fill:
        if event.cumulative_quantity != prior + event.last_quantity:
            _fail("LEDGER_EVENT_SEQUENCE_INVALID")
        if command.mode is ExecutionMode.SHADOW:
            _fail("LEDGER_SHADOW_MUTATION_FORBIDDEN")
    elif event.cumulative_quantity != prior:
        _fail("LEDGER_EVENT_SEQUENCE_INVALID")
    elif event.fees:
        _fail("LEDGER_INPUT_INVALID")

    entries = list(advanced.entries)
    positions = {(item.market, item.symbol): item for item in current.positions}
    cash = _cash_map(current)
    pending = list(current.pending)
    credits = list(current.trading_credits)
    intent = command.intent
    if fill:
        notional = _settlement_notional(command, event, settlement_rule, fx)
        fee_total = _fees(event, settlement_rule.settlement_currency)
        cash_due = _nth_session(intent.session_date, settlement_rule.settlement_sessions, settlement_rule.settlement_lag_sessions)
        key = (intent.market, intent.symbol)
        position = positions.get(key)
        if intent.side is OrderSide.BUY:
            sellable_due = _nth_session(
                intent.session_date,
                settlement_rule.trading_sessions,
                settlement_rule.sellable_lag_sessions,
            )
            required = notional + fee_total
            bucket = cash.get(settlement_rule.settlement_currency, _zero_cash(settlement_rule.settlement_currency))
            from_cash = min(bucket.available, required)
            remainder = required - from_cash
            eligible = [lot for lot in credits if lot.currency is settlement_rule.settlement_currency and lot.due_session <= cash_due]
            if sum((lot.remaining_amount for lot in eligible), Decimal(0)) < remainder:
                _fail("LEDGER_CASH_INSUFFICIENT")
            _update_cash(cash, settlement_rule.settlement_currency, available=-from_cash, payable=required, error="LEDGER_CASH_INSUFFICIENT")
            for lot in sorted(eligible, key=lambda item: (item.due_session, item.credit_id)):
                used = min(lot.remaining_amount, remainder)
                if used:
                    credits[credits.index(lot)] = replace(lot, remaining_amount=lot.remaining_amount - used)
                    entries.append(_entry(source_type="EXECUTION", source_id=event.event_id, kind="CONSUME_TRADING_CREDIT", effective_date=intent.session_date, currency=lot.currency, credit_delta=-used))
                    remainder -= used
                if remainder == 0:
                    break
            previous_qty = 0 if position is None else position.quantity
            previous_cost = Decimal(0) if position is None else position.avg_cost.amount * previous_qty
            sellable_add = event.last_quantity if settlement_rule.sellable_lag_sessions == 0 else 0
            positions[key] = build_position_balance(
                symbol=intent.symbol, market=intent.market,
                quantity=previous_qty + event.last_quantity,
                sellable_quantity=sellable_add + (0 if position is None else position.sellable_quantity),
                avg_cost=build_money_amount(intent.quote_currency, (previous_cost + cast(Decimal, event.last_price) * event.last_quantity) / (previous_qty + event.last_quantity)),
            )
            entries.append(_entry(source_type="EXECUTION", source_id=event.event_id, kind="TRADE_BUY", effective_date=intent.session_date, currency=settlement_rule.settlement_currency, available_delta=-from_cash, payable_delta=required, market=intent.market, symbol=intent.symbol, quantity_delta=event.last_quantity, sellable_delta=sellable_add))
            additions = [
                _build_pending(source_event_id=event.event_id, kind="BUY_CASH_PAYABLE", due_session=cash_due, currency=settlement_rule.settlement_currency, amount=required, market=intent.market, symbol=intent.symbol, quantity=0),
                _build_pending(source_event_id=event.event_id, kind="BUY_POSITION_RECEIVABLE", due_session=cash_due, currency=settlement_rule.settlement_currency, amount=Decimal(0), market=intent.market, symbol=intent.symbol, quantity=event.last_quantity),
            ]
            if settlement_rule.sellable_lag_sessions:
                additions.append(_build_pending(source_event_id=event.event_id, kind="BUY_SELLABLE_UNLOCK", due_session=sellable_due, currency=settlement_rule.settlement_currency, amount=Decimal(0), market=intent.market, symbol=intent.symbol, quantity=event.last_quantity))
        else:
            if position is None or position.quantity < event.last_quantity or position.sellable_quantity < event.last_quantity:
                _fail("LEDGER_POSITION_INSUFFICIENT")
            proceeds = notional - fee_total
            if proceeds <= 0:
                _fail("LEDGER_CONSERVATION_FAILED")
            _update_cash(cash, settlement_rule.settlement_currency, receivable=proceeds)
            remaining_qty = position.quantity - event.last_quantity
            if remaining_qty:
                positions[key] = build_position_balance(symbol=position.symbol, market=position.market, quantity=remaining_qty, sellable_quantity=position.sellable_quantity - event.last_quantity, avg_cost=position.avg_cost)
            else:
                del positions[key]
            entries.append(_entry(source_type="EXECUTION", source_id=event.event_id, kind="TRADE_SELL", effective_date=intent.session_date, currency=settlement_rule.settlement_currency, receivable_delta=proceeds, market=intent.market, symbol=intent.symbol, quantity_delta=-event.last_quantity, sellable_delta=-event.last_quantity))
            additions = [
                _build_pending(source_event_id=event.event_id, kind="SELL_CASH_RECEIVABLE", due_session=cash_due, currency=settlement_rule.settlement_currency, amount=proceeds, market=intent.market, symbol=intent.symbol, quantity=0),
                _build_pending(source_event_id=event.event_id, kind="SELL_POSITION_PAYABLE", due_session=cash_due, currency=settlement_rule.settlement_currency, amount=Decimal(0), market=intent.market, symbol=intent.symbol, quantity=event.last_quantity),
            ]
            if settlement_rule.reuse_sell_receivables:
                lot = _build_credit(event.event_id, cash_due, settlement_rule.settlement_currency, proceeds)
                credits.append(lot)
                entries.append(_entry(source_type="EXECUTION", source_id=event.event_id, kind="ADD_TRADING_CREDIT", effective_date=intent.session_date, currency=lot.currency, credit_delta=proceeds))
        for item in additions:
            pending.append(item)
            entries.append(_entry(source_type="EXECUTION", source_id=event.event_id, kind="ADD_PENDING", effective_date=intent.session_date, currency=item.currency, market=item.market, symbol=item.symbol, pending_id=item.pending_id, pending_action="ADD"))

    projection_by_command[command.command_id] = CommandProjection(
        command_id=command.command_id,
        cumulative_quantity=event.cumulative_quantity,
        broker_order_id=resolved_broker_order_id,
        last_event_at=_normalize_utc_datetime(event.occurred_at),
        settlement_rule_id=settlement_rule.rule_id,
    )
    after = _replace_state(
        current,
        positions=tuple(sorted(positions.values(), key=lambda item: (item.market.value, item.symbol))),
        cash=tuple(sorted(cash.values(), key=lambda item: item.currency.value)),
        pending=tuple(sorted(pending, key=lambda item: (item.due_session, item.kind, item.pending_id))),
        trading_credits=tuple(sorted(credits, key=lambda item: (item.due_session, item.credit_id))),
        applied_event_ids=tuple(sorted((*current.applied_event_ids, event.event_id))),
        command_projections=tuple(
            projection_by_command[key] for key in sorted(projection_by_command)
        ),
    )
    if not fill:
        entries.append(_entry(source_type="EXECUTION", source_id=event.event_id, kind="NON_ECONOMIC_EVENT", effective_date=intent.session_date))
    same_day = advance_ledger_state(after, through_date=processing_date)
    return _transition(state, same_day.state, tuple((*entries, *same_day.entries)))


def build_capture_entitlement_transition(
    *, date: dt.date, before: tuple[EntitlementPosition, ...], after: tuple[EntitlementPosition, ...],
) -> EntitlementTransition:
    """Adapt G7C capture output without repeating entitlement arithmetic."""
    if (
        type(date) is not dt.date
        or type(before) is not tuple
        or type(after) is not tuple
        or any(type(item) is not EntitlementPosition for item in before)
        or any(type(item) is not EntitlementPosition for item in after)
    ):
        _fail("LEDGER_INPUT_INVALID")
    old = {item.event_id: item for item in before}
    new = {item.event_id: item for item in after}
    if len(old) != len(before) or len(new) != len(after) or any(new.get(key) != value for key, value in old.items()):
        _fail("LEDGER_ACTION_CONFLICT")
    postings: list[EntitlementPosting] = []
    for event_id in sorted(set(new) - set(old)):
        item = new[event_id]
        if item.record_date != date or item.cash_state not in {EntitlementLegState.CAPTURED, EntitlementLegState.NOT_APPLICABLE} or item.stock_state not in {EntitlementLegState.CAPTURED, EntitlementLegState.NOT_APPLICABLE}:
            _fail("LEDGER_ACTION_CONFLICT")
        postings.append(EntitlementPosting(date=date, event_id=event_id, symbol=item.symbol, posting_type=EntitlementPostingType.CAPTURE, cash_amount=Decimal(0), stock_quantity=item.record_quantity, cash_rounding_delta=Decimal(0), cash_state_before=EntitlementLegState.ABSENT, cash_state_after=item.cash_state, stock_state_before=EntitlementLegState.ABSENT, stock_state_after=item.stock_state))
    return EntitlementTransition(positions=tuple(sorted(after, key=lambda item: item.event_id)), postings=tuple(postings), cash_delta=Decimal(0), settled_stock=())


def _posting_payload(posting: EntitlementPosting, after: EntitlementPosition) -> dict[str, object]:
    return {"posting": posting, "after": after}


def _action_key(posting: EntitlementPosting) -> str:
    return f"{posting.event_id}:{posting.posting_type.value}:{posting.date.isoformat()}"


def _validate_action(state: LedgerState, action: EntitlementTransition) -> tuple[tuple[AppliedAction, ...], dt.date | None]:
    if (
        type(action) is not EntitlementTransition
        or type(action.positions) is not tuple
        or any(type(item) is not EntitlementPosition for item in action.positions)
        or type(action.postings) is not tuple
        or any(type(item) is not EntitlementPosting for item in action.postings)
    ):
        _fail("LEDGER_INPUT_INVALID")
    if not action.postings:
        if action.positions != state.entitlements:
            _fail("LEDGER_ACTION_CONFLICT")
        return (), None
    dates = {item.date for item in action.postings}
    if len(dates) != 1:
        _fail("LEDGER_ACTION_CONFLICT")
    current = {item.event_id: item for item in state.entitlements}
    final = {item.event_id: item for item in action.positions}
    working = dict(current)
    applied: list[AppliedAction] = []
    for posting in action.postings:
        target = final.get(posting.event_id)
        if target is None or target.symbol != posting.symbol:
            _fail("LEDGER_ACTION_CONFLICT")
        before = working.get(posting.event_id)
        if posting.posting_type is EntitlementPostingType.CAPTURE:
            if (
                before is not None
                or posting.date != target.record_date
                or posting.cash_state_before is not EntitlementLegState.ABSENT
                or posting.stock_state_before is not EntitlementLegState.ABSENT
                or posting.cash_state_after is not target.cash_state
                or posting.stock_state_after is not target.stock_state
                or posting.cash_amount != 0
                or posting.stock_quantity != target.record_quantity
                or posting.cash_rounding_delta != 0
            ):
                _fail("LEDGER_ACTION_CONFLICT")
            working[posting.event_id] = target
        else:
            if before is None or (before.cash_state, before.stock_state) != (posting.cash_state_before, posting.stock_state_before):
                _fail("LEDGER_ACTION_CONFLICT")
            if posting.posting_type is EntitlementPostingType.CASH_RECOGNIZE:
                valid = (
                    posting.date == before.ex_date
                    and before.cash_state is EntitlementLegState.CAPTURED
                    and posting.cash_state_after is EntitlementLegState.RECOGNIZED
                    and posting.stock_state_after is before.stock_state
                    and posting.cash_amount == 0
                    and posting.stock_quantity == 0
                    and posting.cash_rounding_delta == 0
                )
            elif posting.posting_type is EntitlementPostingType.STOCK_RECOGNIZE:
                valid = (
                    posting.date == before.ex_date
                    and before.stock_state is EntitlementLegState.CAPTURED
                    and posting.stock_state_after is EntitlementLegState.RECOGNIZED
                    and posting.cash_state_after is before.cash_state
                    and posting.cash_amount == 0
                    and posting.stock_quantity == 0
                    and posting.cash_rounding_delta == 0
                )
            elif posting.posting_type is EntitlementPostingType.CASH_SETTLE:
                expected_cash = before.cash_entitlement_gross.quantize(
                    _CENT, rounding=ROUND_HALF_UP
                )
                valid = (
                    posting.date == before.cash_settlement_session
                    and before.cash_state is EntitlementLegState.RECOGNIZED
                    and posting.cash_state_after is EntitlementLegState.SETTLED
                    and posting.stock_state_after is before.stock_state
                    and posting.cash_amount == expected_cash
                    and posting.stock_quantity == 0
                    and posting.cash_rounding_delta
                    == expected_cash - before.cash_entitlement_gross
                )
            elif posting.posting_type is EntitlementPostingType.STOCK_SETTLE:
                valid = (
                    posting.date == before.stock_settlement_session
                    and before.stock_state is EntitlementLegState.RECOGNIZED
                    and posting.stock_state_after is EntitlementLegState.SETTLED
                    and posting.cash_state_after is before.cash_state
                    and posting.cash_amount == 0
                    and posting.stock_quantity == before.stock_entitlement
                    and posting.cash_rounding_delta == 0
                )
            else:
                valid = False
            if not valid:
                _fail("LEDGER_ACTION_CONFLICT")
            working[posting.event_id] = replace(before, cash_state=posting.cash_state_after, stock_state=posting.stock_state_after)
        applied.append(AppliedAction(_action_key(posting), _identity("CorporateActionPosting", _posting_payload(posting, target))))
    if tuple(sorted(working.values(), key=lambda item: item.event_id)) != action.positions:
        _fail("LEDGER_ACTION_CONFLICT")
    expected_cash = sum((item.cash_amount for item in action.postings if item.posting_type is EntitlementPostingType.CASH_SETTLE), Decimal(0))
    expected_stock = tuple((item.symbol, item.stock_quantity) for item in action.postings if item.posting_type is EntitlementPostingType.STOCK_SETTLE)
    if action.cash_delta != expected_cash or action.settled_stock != expected_stock:
        _fail("LEDGER_ACTION_CONFLICT")
    return tuple(applied), next(iter(dates))


def apply_corporate_action(state: LedgerState, action: EntitlementTransition) -> LedgerTransition:
    """Apply one exact G7C entitlement transition to CNY cash and A-share positions."""
    _prove_state(state)
    if (
        type(action) is not EntitlementTransition
        or type(action.positions) is not tuple
        or any(type(item) is not EntitlementPosition for item in action.positions)
        or type(action.postings) is not tuple
        or any(type(item) is not EntitlementPosting for item in action.postings)
    ):
        _fail("LEDGER_INPUT_INVALID")
    final_by_event = {item.event_id: item for item in action.positions}
    if len(final_by_event) != len(action.positions) or any(
        posting.event_id not in final_by_event for posting in action.postings
    ):
        _fail("LEDGER_ACTION_CONFLICT")
    replay_identities = tuple(
        AppliedAction(
            _action_key(posting),
            _identity(
                "CorporateActionPosting",
                _posting_payload(posting, final_by_event[posting.event_id]),
            ),
        )
        for posting in action.postings
    )
    existing = {item.logical_key: item.payload_identity for item in state.applied_actions}
    replay_matches = tuple(
        existing.get(item.logical_key) == item.payload_identity
        for item in replay_identities
        if item.logical_key in existing
    )
    if replay_matches:
        if (
            len(replay_matches) == len(replay_identities)
            and all(replay_matches)
            and action.positions == state.entitlements
        ):
            return _transition(state, state, ())
        _fail("LEDGER_ACTION_CONFLICT")
    identities, action_date = _validate_action(state, action)
    if action_date is None:
        return _transition(state, state, ())
    advanced = advance_ledger_state(
        state, through_date=max(state.as_of_date, action_date)
    )
    current = advanced.state
    cash = _cash_map(current)
    positions = {(item.market, item.symbol): item for item in current.positions}
    entries = list(advanced.entries)
    for posting in action.postings:
        entitlement = next(item for item in action.positions if item.event_id == posting.event_id)
        common = dict(source_type="CORPORATE_ACTION", source_id=_identity("CorporateActionSource", {"key": _action_key(posting)}), effective_date=posting.date, currency=Currency.CNY, market=Market.SH if posting.symbol.endswith(".SH") else Market.SZ, symbol=posting.symbol)
        if posting.posting_type is EntitlementPostingType.CASH_RECOGNIZE:
            _update_cash(cash, Currency.CNY, receivable=entitlement.cash_entitlement_gross)
            entries.append(_entry(kind="CORPORATE_CASH_RECOGNIZE", receivable_delta=entitlement.cash_entitlement_gross, **common))
        elif posting.posting_type is EntitlementPostingType.CASH_SETTLE:
            expected = entitlement.cash_entitlement_gross.quantize(_CENT, rounding=ROUND_HALF_UP)
            if posting.cash_amount != expected or posting.cash_rounding_delta != expected - entitlement.cash_entitlement_gross:
                _fail("LEDGER_ACTION_CONFLICT")
            _update_cash(cash, Currency.CNY, settled=posting.cash_amount, available=posting.cash_amount, receivable=-entitlement.cash_entitlement_gross)
            entries.append(_entry(kind="CORPORATE_CASH_SETTLE", settled_delta=posting.cash_amount, available_delta=posting.cash_amount, receivable_delta=-entitlement.cash_entitlement_gross, rounding_delta=posting.cash_rounding_delta, **common))
        elif posting.posting_type is EntitlementPostingType.STOCK_SETTLE:
            key = (cast(Market, common["market"]), posting.symbol)
            position = positions.get(key)
            old_qty = 0 if position is None else position.quantity
            total_cost = Decimal(0) if position is None else position.avg_cost.amount * old_qty
            new_qty = old_qty + posting.stock_quantity
            positions[key] = build_position_balance(symbol=posting.symbol, market=key[0], quantity=new_qty, sellable_quantity=(0 if position is None else position.sellable_quantity) + posting.stock_quantity, avg_cost=build_money_amount(Currency.CNY, Decimal(0) if new_qty == 0 else total_cost / new_qty))
            entries.append(_entry(kind="CORPORATE_STOCK_SETTLE", quantity_delta=posting.stock_quantity, sellable_delta=posting.stock_quantity, **common))
        else:
            entries.append(_entry(kind=f"CORPORATE_{posting.posting_type.value}", **common))
    merged_actions = tuple(sorted((*current.applied_actions, *identities), key=lambda item: item.logical_key))
    after = _replace_state(current, positions=tuple(sorted(positions.values(), key=lambda item: (item.market.value, item.symbol))), cash=tuple(sorted(cash.values(), key=lambda item: item.currency.value)), entitlements=action.positions, applied_actions=merged_actions)
    return _transition(state, after, tuple(entries))


__all__ = [
    "AppliedAction", "CommandProjection", "LedgerEntry", "LedgerError",
    "LedgerState", "LedgerTransition", "PendingSettlement", "SettlementRule",
    "TradingCreditLot", "advance_ledger_state", "apply_corporate_action",
    "apply_execution_event", "build_capture_entitlement_transition",
    "build_ledger_state", "build_settlement_rule",
]
