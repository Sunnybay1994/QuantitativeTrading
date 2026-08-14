"""Typed pure bridge from execution callbacks to the existing B5 ledger."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol, cast, runtime_checkable

from quant.backtest.fx import (
    FxRate,
    FxSnapshot,
    build_fx_snapshot,
    require_fx_snapshot_current,
)
from quant.backtest.ledger import (
    LedgerEntry,
    LedgerState,
    SettlementRule,
    apply_execution_event,
    build_ledger_state,
    build_settlement_rule,
)
from quant.domain.enums import Currency, Market
from quant.execution.contracts import (
    AccountSnapshot,
    ExecutionEvent,
    OrderCommand,
    build_order_command_identity,
)

_SCHEMA = "m4-ledger-context-v1"
_HEX = frozenset("0123456789abcdef")


class LedgerAdapterError(ValueError):
    """Stable context/adapter failure."""


@dataclass(frozen=True, slots=True)
class ExecutionLedgerContext:
    """Immutable rule/FX snapshot selected before a command becomes sendable."""

    context_id: str
    command_id: str
    settlement_rule: SettlementRule
    fx_snapshot: FxSnapshot | None

    def __post_init__(self) -> None:
        rebuilt = _build_context(
            command_id=self.command_id,
            settlement_rule=self.settlement_rule,
            fx_snapshot=self.fx_snapshot,
        )
        if self.context_id != rebuilt.context_id:
            raise LedgerAdapterError("LEDGER_CONTEXT_INVALID")


@dataclass(frozen=True, slots=True)
class LedgerMutation:
    """Verified next checkpoint and append-only entries."""

    state: LedgerState
    entries: tuple[LedgerEntry, ...]


@runtime_checkable
class LedgerContextProvider(Protocol):
    """Narrow dependency used by P4 while staging each command."""

    def context_for(self, command: OrderCommand) -> ExecutionLedgerContext:
        """Return the preselected immutable rule/FX context."""
        ...


def build_execution_ledger_context(
    *,
    command: OrderCommand,
    settlement_rule: SettlementRule,
    fx_snapshot: FxSnapshot | None,
) -> ExecutionLedgerContext:
    """Bind one proven command to its already-selected B5 inputs."""
    result: ExecutionLedgerContext | None = None
    try:
        value = _build_context(
            command_id=command.command_id,
            settlement_rule=settlement_rule,
            fx_snapshot=fx_snapshot,
        )
        result = verify_execution_ledger_context(value, command=command)
    except Exception:
        pass
    if result is None:
        raise LedgerAdapterError("LEDGER_CONTEXT_INVALID") from None
    return result


def verify_execution_ledger_context(
    value: ExecutionLedgerContext, *, command: OrderCommand
) -> ExecutionLedgerContext:
    """Prove command/rule/currency/freshness closure before durable staging."""
    result: ExecutionLedgerContext | None = None
    try:
        rebuilt = decode_ledger_context(encode_ledger_context(value))
        build_order_command_identity(command)
        rule = rebuilt.settlement_rule
        if (
            rebuilt.command_id != command.command_id
            or rule.market is not command.intent.market
            or rule.quote_currency is not command.intent.quote_currency
        ):
            raise ValueError
        if rule.quote_currency is rule.settlement_currency:
            if rebuilt.fx_snapshot is not None:
                raise ValueError
        else:
            if rebuilt.fx_snapshot is None:
                raise ValueError
            require_fx_snapshot_current(
                rebuilt.fx_snapshot,
                session_date=command.intent.session_date,
                at=command.intent.generated_at,
            )
        result = rebuilt
    except Exception:
        pass
    if result is None:
        raise LedgerAdapterError("LEDGER_CONTEXT_INVALID") from None
    return result


def encode_ledger_context(value: ExecutionLedgerContext) -> bytes:
    """Encode one strict canonical context row."""
    result: bytes | None = None
    try:
        rebuilt = _build_context(
            command_id=value.command_id,
            settlement_rule=value.settlement_rule,
            fx_snapshot=value.fx_snapshot,
        )
        if rebuilt != value:
            raise ValueError
        result = _canonical(_context_root(value))
    except Exception:
        pass
    if result is None:
        raise LedgerAdapterError("LEDGER_CONTEXT_INVALID") from None
    return result


def decode_ledger_context(payload: bytes) -> ExecutionLedgerContext:
    """Decode and re-prove a canonical context without guessing legacy bytes."""
    result: ExecutionLedgerContext | None = None
    failure_code: str | None = None
    try:
        if type(payload) is not bytes or not payload:
            raise ValueError
        root = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_float=_reject_number,
            parse_constant=_reject_number,
        )
        if type(root) is not dict or set(root) != {
            "command_id", "context_id", "fx_snapshot", "schema_version",
            "settlement_rule",
        }:
            raise ValueError
        if root["schema_version"] != _SCHEMA:
            raise LedgerAdapterError("LEGACY_LEDGER_CONTEXT_UNVERIFIED")
        command_id = _text(root["command_id"])
        rule = _decode_rule(root["settlement_rule"])
        fx = _decode_fx(root["fx_snapshot"])
        value = _build_context(
            command_id=command_id, settlement_rule=rule, fx_snapshot=fx
        )
        if value.context_id != _text(root["context_id"]):
            raise ValueError
        if encode_ledger_context(value) != payload:
            raise ValueError
        result = value
    except LedgerAdapterError as error:
        failure_code = str(error)
    except Exception:
        failure_code = "LEDGER_CONTEXT_INVALID"
    if result is None:
        payload = b""
        raise LedgerAdapterError(
            failure_code or "LEDGER_CONTEXT_INVALID"
        ) from None
    return result


def build_genesis_checkpoint(
    account: AccountSnapshot, *, as_of_date: dt.date
) -> LedgerState:
    """Delegate genesis construction to B5."""
    result: LedgerState | None = None
    try:
        result = build_ledger_state(account, as_of_date=as_of_date)
    except Exception:
        pass
    if result is None:
        raise LedgerAdapterError("LEDGER_GENESIS_INVALID") from None
    return result


def apply_ledger_callbacks(
    *,
    state: LedgerState,
    command: OrderCommand,
    callbacks: tuple[ExecutionEvent, ...],
    context: ExecutionLedgerContext,
) -> LedgerMutation:
    """Apply ordered callbacks by invoking B5 once per event."""
    result: LedgerMutation | None = None
    try:
        if (
            type(state) is not LedgerState
            or type(command) is not OrderCommand
            or type(callbacks) is not tuple
            or any(type(item) is not ExecutionEvent for item in callbacks)
            or context.command_id != command.command_id
        ):
            raise ValueError
        current = state
        entries: list[LedgerEntry] = []
        for event in callbacks:
            transition = apply_execution_event(
                current,
                command,
                event,
                context.settlement_rule,
                context.fx_snapshot,
            )
            current = transition.state
            entries.extend(transition.entries)
        result = LedgerMutation(state=current, entries=tuple(entries))
    except Exception:
        pass
    if result is None:
        raise LedgerAdapterError("LEDGER_CALLBACK_INVALID") from None
    return result


def _build_context(
    *, command_id: str, settlement_rule: SettlementRule,
    fx_snapshot: FxSnapshot | None,
) -> ExecutionLedgerContext:
    if (
        not _hex64(command_id)
        or type(settlement_rule) is not SettlementRule
        or (fx_snapshot is not None and type(fx_snapshot) is not FxSnapshot)
    ):
        raise ValueError
    provisional = ExecutionLedgerContext.__new__(ExecutionLedgerContext)
    object.__setattr__(provisional, "context_id", "0" * 64)
    object.__setattr__(provisional, "command_id", command_id)
    object.__setattr__(provisional, "settlement_rule", settlement_rule)
    object.__setattr__(provisional, "fx_snapshot", fx_snapshot)
    context_id = hashlib.sha256(_canonical(_identity_root(provisional))).hexdigest()
    value = ExecutionLedgerContext.__new__(ExecutionLedgerContext)
    object.__setattr__(value, "context_id", context_id)
    object.__setattr__(value, "command_id", command_id)
    object.__setattr__(value, "settlement_rule", settlement_rule)
    object.__setattr__(value, "fx_snapshot", fx_snapshot)
    return value


def _context_root(value: ExecutionLedgerContext) -> dict[str, object]:
    return {"schema_version": _SCHEMA, "context_id": value.context_id,
            **_identity_root(value)}


def _identity_root(value: ExecutionLedgerContext) -> dict[str, object]:
    return {
        "command_id": value.command_id,
        "settlement_rule": _rule_root(value.settlement_rule),
        "fx_snapshot": None if value.fx_snapshot is None else _fx_root(value.fx_snapshot),
    }


def _rule_root(rule: SettlementRule) -> dict[str, object]:
    return {
        "rule_id": rule.rule_id, "selector": rule.selector,
        "market": rule.market.value, "quote_currency": rule.quote_currency.value,
        "settlement_currency": rule.settlement_currency.value,
        "effective_from": rule.effective_from.isoformat(),
        "effective_to": None if rule.effective_to is None else rule.effective_to.isoformat(),
        "trading_sessions": [item.isoformat() for item in rule.trading_sessions],
        "settlement_sessions": [item.isoformat() for item in rule.settlement_sessions],
        "trading_calendar_source_identity": rule.trading_calendar_source_identity,
        "settlement_calendar_source_identity": rule.settlement_calendar_source_identity,
        "settlement_lag_sessions": rule.settlement_lag_sessions,
        "sellable_lag_sessions": rule.sellable_lag_sessions,
        "reuse_sell_receivables": rule.reuse_sell_receivables,
    }


def _fx_root(value: FxSnapshot) -> dict[str, object]:
    return {
        "snapshot_id": value.snapshot_id, "selector": value.selector,
        "session_date": value.session_date.isoformat(),
        "observed_at": _datetime(value.observed_at),
        "expires_at": _datetime(value.expires_at),
        "rates": [{"source_currency": item.source_currency.value,
                   "settlement_currency": item.settlement_currency.value,
                   "rate": format(item.rate, "f")} for item in value.rates],
    }


def _decode_rule(raw: object) -> SettlementRule:
    root = _dict(raw, {"effective_from", "effective_to", "market", "quote_currency",
        "reuse_sell_receivables", "rule_id", "selector", "sellable_lag_sessions",
        "settlement_calendar_source_identity", "settlement_currency",
        "settlement_lag_sessions", "settlement_sessions",
        "trading_calendar_source_identity", "trading_sessions"})
    rule = build_settlement_rule(
        selector=_text(root["selector"]), market=Market(_text(root["market"])),
        quote_currency=Currency(_text(root["quote_currency"])),
        settlement_currency=Currency(_text(root["settlement_currency"])),
        effective_from=dt.date.fromisoformat(_text(root["effective_from"])),
        effective_to=None if root["effective_to"] is None else dt.date.fromisoformat(_text(root["effective_to"])),
        trading_sessions=tuple(dt.date.fromisoformat(_text(item)) for item in _list(root["trading_sessions"])),
        settlement_sessions=tuple(dt.date.fromisoformat(_text(item)) for item in _list(root["settlement_sessions"])),
        trading_calendar_source_identity=_text(root["trading_calendar_source_identity"]),
        settlement_calendar_source_identity=_text(root["settlement_calendar_source_identity"]),
        settlement_lag_sessions=_int(root["settlement_lag_sessions"]),
        sellable_lag_sessions=_int(root["sellable_lag_sessions"]),
        reuse_sell_receivables=_bool(root["reuse_sell_receivables"]),
    )
    if rule.rule_id != _text(root["rule_id"]):
        raise ValueError
    return rule


def _decode_fx(raw: object) -> FxSnapshot | None:
    if raw is None:
        return None
    root = _dict(raw, {"expires_at", "observed_at", "rates", "selector",
                       "session_date", "snapshot_id"})
    rates = tuple(FxRate(Currency(_text(item["source_currency"])),
                         Currency(_text(item["settlement_currency"])),
                         Decimal(_text(item["rate"])))
                  for item in (_dict(value, {"rate", "settlement_currency", "source_currency"})
                               for value in _list(root["rates"])))
    value = build_fx_snapshot(
        selector=_text(root["selector"]),
        session_date=dt.date.fromisoformat(_text(root["session_date"])),
        observed_at=_parse_datetime(root["observed_at"]),
        expires_at=_parse_datetime(root["expires_at"]), rates=rates,
    )
    if value.snapshot_id != _text(root["snapshot_id"]):
        raise ValueError
    return value


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def _reject_duplicate_keys(items: list[tuple[str, object]]) -> dict[str, object]:
    if len({key for key, _ in items}) != len(items):
        raise ValueError
    return dict(items)


def _reject_number(_value: str) -> object:
    raise ValueError


def _dict(value: object, keys: set[str]) -> dict[str, object]:
    if type(value) is not dict or set(cast(dict[object, object], value)) != keys:
        raise ValueError
    return cast(dict[str, object], value)


def _list(value: object) -> list[object]:
    if type(value) is not list:
        raise ValueError
    return cast(list[object], value)


def _text(value: object) -> str:
    if type(value) is not str or not value:
        raise ValueError
    return value


def _int(value: object) -> int:
    if type(value) is not int:
        raise ValueError
    return value


def _bool(value: object) -> bool:
    if type(value) is not bool:
        raise ValueError
    return value


def _datetime(value: dt.datetime) -> str:
    if value.tzinfo is not dt.UTC:
        raise ValueError
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _parse_datetime(value: object) -> dt.datetime:
    text = _text(value)
    if not text.endswith("Z"):
        raise ValueError
    parsed = dt.datetime.fromisoformat(text[:-1] + "+00:00")
    if _datetime(parsed) != text:
        raise ValueError
    return parsed


def _hex64(value: object) -> bool:
    return type(value) is str and len(value) == 64 and all(char in _HEX for char in value)


__all__ = [
    "ExecutionLedgerContext", "LedgerAdapterError", "LedgerContextProvider",
    "LedgerMutation", "apply_ledger_callbacks", "build_execution_ledger_context",
    "build_genesis_checkpoint", "decode_ledger_context", "encode_ledger_context",
    "verify_execution_ledger_context",
]
