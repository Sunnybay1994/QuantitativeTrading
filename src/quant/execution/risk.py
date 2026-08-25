"""M4-P3 pre-trade risk evaluation with per-rule audit trail.

Based on pending-main-acceptance M4-C0/D0/D1 contracts.
Does not implement LIVE, OMS, store, or gateway submit.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from quant.domain.enums import ConnectRoute, Currency, ExecutionMode, Market, OrderSide
from quant.execution.approval import (
    ApprovalReceiptError,
    unpack_verified_approval_receipt,
)
from quant.execution.config import TradingConfig, trading_config_identity
from quant.execution.contracts import (
    AccountSnapshot,
    CancelCommand,
    OrderCommand,
    OrderIntent,
    OrderPlan,
    VerifiedConnectMarketContext,
    VerifiedMarketSnapshot,
    build_account_snapshot_identity,
    build_cancel_command_identity,
    build_order_command,
    build_order_plan_identity,
    build_verified_connect_market_context_identity,
    build_verified_market_snapshot_identity,
)


class RiskInputError(ValueError):
    """Stable fail-closed rejection of untrusted pre-trade input payloads."""


@dataclass(frozen=True, slots=True)
class RiskRuleResult:
    """One rule evaluation outcome for the audit trail."""

    rule: str
    accepted: bool
    code: str
    subject: str
    detail: str


@dataclass(frozen=True, slots=True)
class DailyRiskCounters:
    """Durable daily counters; callers must persist across process restarts."""

    session_date: dt.date
    order_count: int
    cancel_count: int
    buy_notional: Decimal

    def __post_init__(self) -> None:
        if type(self.session_date) is not dt.date or isinstance(self.session_date, dt.datetime):
            raise TypeError("session_date must be date")
        if type(self.order_count) is not int or isinstance(self.order_count, bool):
            raise TypeError("order_count must be int")
        if type(self.cancel_count) is not int or isinstance(self.cancel_count, bool):
            raise TypeError("cancel_count must be int")
        if self.order_count < 0 or self.cancel_count < 0:
            raise ValueError("counters must be non-negative")
        if type(self.buy_notional) is not Decimal or not self.buy_notional.is_finite():
            raise TypeError("buy_notional must be finite Decimal")
        if self.buy_notional < 0:
            raise ValueError("buy_notional must be non-negative")

    def to_persistable_dict(self) -> dict[str, object]:
        """Serialize for durable store round-trip (cancel/order counts survive restart)."""
        self.__post_init__()
        return {
            "session_date": self.session_date.isoformat(),
            "order_count": self.order_count,
            "cancel_count": self.cancel_count,
            "buy_notional": format(self.buy_notional, "f"),
        }

    @classmethod
    def from_persistable_dict(cls, payload: Mapping[str, object]) -> DailyRiskCounters:
        """Restore counters after process restart; malformed payloads fail closed."""
        expected_keys = {
            "session_date",
            "order_count",
            "cancel_count",
            "buy_notional",
        }
        if type(payload) is not dict or set(payload) != expected_keys:
            raise ValueError("daily risk counters payload keys invalid")
        session_raw = payload["session_date"]
        order_raw = payload["order_count"]
        cancel_raw = payload["cancel_count"]
        notional_raw = payload["buy_notional"]
        if type(session_raw) is not str:
            raise TypeError("session_date must be str")
        if type(order_raw) is not int or isinstance(order_raw, bool):
            raise TypeError("order_count must be int")
        if type(cancel_raw) is not int or isinstance(cancel_raw, bool):
            raise TypeError("cancel_count must be int")
        if type(notional_raw) is not str:
            raise TypeError("buy_notional must be str")
        return cls(
            session_date=dt.date.fromisoformat(session_raw),
            order_count=order_raw,
            cancel_count=cancel_raw,
            buy_notional=Decimal(notional_raw),
        )


_DAILY_RISK_COUNTERS_HASH_VERSION = "daily-risk-counters-hash-v1"


def _validated_daily_risk_counters_payload(
    counters: DailyRiskCounters,
) -> dict[str, object]:
    if type(counters) is not DailyRiskCounters:
        raise TypeError("counters must be DailyRiskCounters")
    payload = counters.to_persistable_dict()
    restored = DailyRiskCounters.from_persistable_dict(payload)
    if restored != counters:
        raise ValueError("daily risk counters object is not canonical")
    return payload


def serialize_daily_risk_counters(counters: DailyRiskCounters) -> bytes:
    """Return the sole canonical durable payload for daily counters."""
    encoded = json.dumps(
        _validated_daily_risk_counters_payload(counters),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return encoded.encode("utf-8")


def deserialize_daily_risk_counters(payload: bytes) -> DailyRiskCounters:
    """Restore and authenticate the canonical wire shape before identity checks."""
    if type(payload) is not bytes:
        raise TypeError("payload must be bytes")
    decoded: object = None
    invalid_json = False
    try:
        decoded = json.loads(payload.decode("utf-8"))
    except (RecursionError, UnicodeDecodeError, json.JSONDecodeError):
        invalid_json = True
    if invalid_json:
        raise ValueError("daily risk counters payload invalid") from None
    if type(decoded) is not dict:
        raise ValueError("daily risk counters payload must be an object")
    counters = DailyRiskCounters.from_persistable_dict(decoded)
    if serialize_daily_risk_counters(counters) != payload:
        raise ValueError("daily risk counters payload must be canonical")
    return counters


def build_daily_risk_counters_identity(counters: DailyRiskCounters) -> str:
    """Build the versioned canonical identity used by durable CAS writes."""
    payload = {
        "hash_version": _DAILY_RISK_COUNTERS_HASH_VERSION,
        "type": "DailyRiskCounters",
        "payload": _validated_daily_risk_counters_payload(counters),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class RiskDecision:
    """Overall pre-trade decision with complete rule audit trail."""

    accepted: bool
    plan_id: str
    rule_results: tuple[RiskRuleResult, ...]
    approved_intent_ids: tuple[str, ...]
    commands: tuple[OrderCommand, ...]
    projected_counters: DailyRiskCounters
    requires_manual_approval: bool


@dataclass(frozen=True, slots=True)
class CancelRiskDecision:
    """One deterministic daily cancel-limit decision."""

    accepted: bool
    cancel_id: str
    code: str
    policy_identity: str
    projected_counters: DailyRiskCounters

    def __post_init__(self) -> None:
        if (
            type(self.accepted) is not bool
            or type(self.cancel_id) is not str
            or len(self.cancel_id) != 64
            or type(self.code) is not str
            or self.code not in {"CANCEL_LIMIT_OK", "CANCEL_LIMIT_EXCEEDED"}
            or type(self.policy_identity) is not str
            or len(self.policy_identity) != 64
            or type(self.projected_counters) is not DailyRiskCounters
        ):
            raise RiskInputError("CANCEL_RISK_INPUT_INVALID")


def _result(
    rule: str,
    *,
    accepted: bool,
    code: str,
    subject: str,
    detail: str,
) -> RiskRuleResult:
    return RiskRuleResult(
        rule=rule,
        accepted=accepted,
        code=code,
        subject=subject,
        detail=detail,
    )


def _section(config: TradingConfig, name: str) -> Mapping[str, object]:
    return config.section(name)


def _as_bool(value: object) -> bool:
    if type(value) is not bool:
        raise TypeError("expected bool")
    return value


def _as_str_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise TypeError("expected str sequence")
    return tuple(str(item) for item in value)


def _as_int(value: object) -> int:
    if type(value) is not int or isinstance(value, bool):
        raise TypeError("expected int")
    return value


def _select_limits(config: TradingConfig, session_date: dt.date) -> Mapping[str, object]:
    periods = _section(config, "risk")["limits"]
    if not isinstance(periods, Sequence) or not periods:
        raise ValueError("risk.limits missing")
    for period in periods:
        if not isinstance(period, Mapping):
            continue
        start = period["effective_from"]
        end = period.get("effective_to")
        if type(start) is not dt.date:
            continue
        if session_date < start:
            continue
        if end is None or (type(end) is dt.date and session_date <= end):
            return period
    raise ValueError("no risk limit period covers session_date")


def _intent_notional(intent: OrderIntent) -> Decimal:
    return intent.limit_price * Decimal(intent.quantity)


def _snapshot_age_seconds(clock: dt.datetime, as_of: dt.datetime) -> float:
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("snapshot as_of must be timezone-aware UTC")
    if as_of.utcoffset() != dt.timedelta(0):
        raise ValueError("snapshot as_of must be timezone-aware UTC")
    return (clock - as_of).total_seconds()


def _equity_cny(
    account: AccountSnapshot,
    market: VerifiedMarketSnapshot,
) -> Decimal | None:
    """Account equity in CNY using verified reference prices only.

    Returns None when a CNY position cannot be valued from the market snapshot
    (fail closed — never silently substitute avg_cost into risk inputs).
    """
    state_by_key = {(s.market, s.symbol): s for s in market.states}
    equity = Decimal("0")
    for cash in account.cash:
        if cash.currency is Currency.CNY:
            equity += cash.available
    for pos in account.positions:
        if pos.avg_cost.currency is not Currency.CNY:
            continue
        state = state_by_key.get((pos.market, pos.symbol))
        if state is None:
            return None
        equity += state.reference_price * Decimal(pos.quantity)
    return equity


def _position_qty(account: AccountSnapshot, market: Market, symbol: str) -> int:
    for pos in account.positions:
        if pos.market is market and pos.symbol == symbol:
            return pos.quantity
    return 0


def _sellable_qty(account: AccountSnapshot, market: Market, symbol: str) -> int | None:
    for pos in account.positions:
        if pos.market is market and pos.symbol == symbol:
            return pos.sellable_quantity
    return None


def _resolve_hk_connect_context(
    intent: OrderIntent,
    market: VerifiedMarketSnapshot,
) -> VerifiedConnectMarketContext | str:
    """Exact route lookup for one HK intent; return context or stable reject code.

    SH/SZ must not call this. Missing / duplicate / session / future as_of fail closed
    before any quota read. Forged context identity raises RiskInputError.
    """
    route = intent.connect_route
    if route is None or type(route) is not ConnectRoute:
        return "CONNECT_CONTEXT_ROUTE_MISSING"
    matches = [item for item in market.connect_contexts if item.route is route]
    if not matches:
        return "CONNECT_CONTEXT_MISSING"
    if len(matches) != 1:
        return "CONNECT_CONTEXT_DUPLICATE"
    context = matches[0]
    if context.session_date != market.session_date:
        return "CONNECT_CONTEXT_SESSION_MISMATCH"
    if context.session_date != intent.session_date:
        return "CONNECT_CONTEXT_SESSION_MISMATCH"
    if context.as_of > market.as_of:
        return "CONNECT_CONTEXT_FUTURE"
    failure: RiskInputError | None = None
    try:
        build_verified_connect_market_context_identity(context)
    except Exception:
        failure = RiskInputError("MARKET_CONTRACT_INVALID")
    if failure is not None:
        raise failure from None
    return context


def _prove_pretrade_inputs(
    plan: OrderPlan,
    account: AccountSnapshot,
    market: VerifiedMarketSnapshot,
    config: TradingConfig,
    daily_counters: DailyRiskCounters,
) -> tuple[str, DailyRiskCounters]:
    """Recompute D0/C0 identities and counters before any economic field use.

    Ordinary verification failures map to RiskInputError with fixed codes only.
    Build the error inside ``except``, then raise outside the handler so both
    ``__cause__`` and ``__context__`` stay None (fail closed, no payload echo).
    """
    failure: RiskInputError | None = None
    try:
        build_order_plan_identity(plan)
    except Exception:
        failure = RiskInputError("PLAN_CONTRACT_INVALID")
    if failure is not None:
        raise failure from None

    try:
        build_verified_market_snapshot_identity(market)
    except Exception:
        failure = RiskInputError("MARKET_CONTRACT_INVALID")
    if failure is not None:
        raise failure from None

    try:
        build_account_snapshot_identity(account)
    except Exception:
        failure = RiskInputError("ACCOUNT_CONTRACT_INVALID")
    if failure is not None:
        raise failure from None

    cfg_id = ""
    try:
        cfg_id = trading_config_identity(config)
    except Exception:
        failure = RiskInputError("CONFIG_CONTRACT_INVALID")
    if failure is not None:
        raise failure from None

    try:
        proven_counters = DailyRiskCounters(
            session_date=daily_counters.session_date,
            order_count=daily_counters.order_count,
            cancel_count=daily_counters.cancel_count,
            buy_notional=daily_counters.buy_notional,
        )
    except Exception:
        failure = RiskInputError("COUNTERS_INVALID")
        proven_counters = daily_counters
    if failure is not None:
        raise failure from None

    return cfg_id, proven_counters


def _projected_gross_exposure(
    account: AccountSnapshot,
    market: VerifiedMarketSnapshot,
    intents: Sequence[OrderIntent],
) -> Decimal | None:
    """Sum of absolute security market values after applying batch intents.

    Cash is excluded. Returns None when any non-zero projected holding lacks a
    verified reference price (fail closed).
    """
    state_by_key = {(s.market, s.symbol): s for s in market.states}
    qty_by_key: dict[tuple[Market, str], int] = {}
    for pos in account.positions:
        qty_by_key[(pos.market, pos.symbol)] = pos.quantity
    for intent in intents:
        key = (intent.market, intent.symbol)
        current = qty_by_key.get(key, 0)
        if intent.side is OrderSide.BUY:
            qty_by_key[key] = current + intent.quantity
        else:
            qty_by_key[key] = current - intent.quantity

    gross = Decimal("0")
    for key, qty in qty_by_key.items():
        if qty == 0:
            continue
        state = state_by_key.get(key)
        if state is None:
            return None
        gross += abs(state.reference_price * Decimal(qty))
    return gross


def evaluate_pretrade(
    plan: OrderPlan,
    account: AccountSnapshot,
    market: VerifiedMarketSnapshot,
    config: TradingConfig,
    daily_counters: DailyRiskCounters,
    *,
    now: dt.datetime | None = None,
    approval: object | None = None,
) -> RiskDecision:
    """Evaluate an order plan against config switches, data gate, and risk limits.

    Priority: input identity proof → master switch → data/snapshot gate →
    sellable → frozen symbols → sell-only → per-order / symbol / gross / daily /
    order-count limits (batch).

    SHADOW never emits OrderCommand. manual_approval blocks command emission.
    Ordinary stale market forbids new buys but may allow sells; future market or
    unusable account snapshot reject all intents.
    """
    if not isinstance(plan, OrderPlan):
        raise TypeError("plan must be OrderPlan")
    if not isinstance(account, AccountSnapshot):
        raise TypeError("account must be AccountSnapshot")
    if not isinstance(market, VerifiedMarketSnapshot):
        raise TypeError("market must be VerifiedMarketSnapshot")
    if not isinstance(config, TradingConfig):
        raise TypeError("config must be TradingConfig")
    if not isinstance(daily_counters, DailyRiskCounters):
        raise TypeError("daily_counters must be DailyRiskCounters")

    clock = now if now is not None else dt.datetime.now(dt.timezone.utc)
    if clock.tzinfo is None or clock.utcoffset() is None:
        raise ValueError("now must be timezone-aware UTC")
    if clock.utcoffset() != dt.timedelta(0):
        raise ValueError("now must be timezone-aware UTC")

    # Prove content identities before reading mode/quota/cash/position/side.
    cfg_id, daily_counters = _prove_pretrade_inputs(
        plan, account, market, config, daily_counters
    )

    audit: list[RiskRuleResult] = []
    execution = _section(config, "execution")
    data_cfg = _section(config, "data")
    mode_raw = execution["mode"]
    auto_trade = _as_bool(execution["auto_trade"])
    manual_approval = _as_bool(execution["manual_approval"])
    sell_only = _as_bool(execution["sell_only"])
    frozen = set(_as_str_tuple(execution["frozen_symbols"]))
    max_age = _as_int(data_cfg["snapshot_max_age_seconds"])

    # --- 1. Master switch ---
    if mode_raw not in (ExecutionMode.PAPER.value, ExecutionMode.SHADOW.value):
        audit.append(
            _result(
                "MASTER_SWITCH",
                accepted=False,
                code="MODE_FORBIDDEN",
                subject=plan.plan_id,
                detail="mode must be PAPER or SHADOW",
            )
        )
        return _reject_all(plan, audit, daily_counters, manual_approval=False)

    mode = ExecutionMode(str(mode_raw))
    if auto_trade is True:
        audit.append(
            _result(
                "MASTER_SWITCH",
                accepted=False,
                code="AUTO_TRADE_FORBIDDEN",
                subject=plan.plan_id,
                detail="auto_trade must remain false",
            )
        )
        return _reject_all(plan, audit, daily_counters, manual_approval=False)

    audit.append(
        _result(
            "MASTER_SWITCH",
            accepted=True,
            code="MASTER_SWITCH_OK",
            subject=plan.plan_id,
            detail=f"mode={mode.value};auto_trade=false",
        )
    )

    if plan.trading_config_identity != cfg_id:
        audit.append(
            _result(
                "MASTER_SWITCH",
                accepted=False,
                code="CONFIG_IDENTITY_MISMATCH",
                subject=plan.plan_id,
                detail="plan.trading_config_identity does not match loaded config",
            )
        )
        return _reject_all(plan, audit, daily_counters, manual_approval=False)

    if plan.market_snapshot_id != market.snapshot_id:
        audit.append(
            _result(
                "MASTER_SWITCH",
                accepted=False,
                code="MARKET_SNAPSHOT_MISMATCH",
                subject=plan.plan_id,
                detail="plan.market_snapshot_id does not match market",
            )
        )
        return _reject_all(plan, audit, daily_counters, manual_approval=False)

    if plan.account_snapshot_id != account.snapshot_id:
        audit.append(
            _result(
                "MASTER_SWITCH",
                accepted=False,
                code="ACCOUNT_SNAPSHOT_MISMATCH",
                subject=plan.plan_id,
                detail="plan.account_snapshot_id does not match account",
            )
        )
        return _reject_all(plan, audit, daily_counters, manual_approval=False)

    if daily_counters.session_date != market.session_date:
        audit.append(
            _result(
                "MASTER_SWITCH",
                accepted=False,
                code="COUNTER_SESSION_MISMATCH",
                subject=plan.plan_id,
                detail="daily_counters.session_date must match market.session_date",
            )
        )
        return _reject_all(plan, audit, daily_counters, manual_approval=False)

    limits = _select_limits(config, market.session_date)
    max_order_notional = Decimal(str(limits["max_order_notional"]))
    max_symbol_weight = Decimal(str(limits["max_symbol_weight"]))
    max_gross_exposure = Decimal(str(limits["max_gross_exposure"]))
    max_daily_notional = Decimal(str(limits["max_daily_notional"]))
    max_orders_per_day = _as_int(limits["max_orders_per_day"])

    # --- 2. Data / snapshot gate (market + account ages) ---
    # Closed interval: 0 <= age <= snapshot_max_age_seconds.
    market_age = _snapshot_age_seconds(clock, market.as_of)
    account_age = _snapshot_age_seconds(clock, account.as_of)
    max_age_f = float(max_age)

    if market_age < 0:
        audit.append(
            _result(
                "DATA_GATE",
                accepted=False,
                code="DATA_GATE_FUTURE",
                subject=market.snapshot_id,
                detail="market snapshot as_of is in the future; fail closed",
            )
        )
        return _reject_all(plan, audit, daily_counters, manual_approval=False)

    if account_age < 0:
        audit.append(
            _result(
                "DATA_GATE",
                accepted=False,
                code="ACCOUNT_GATE_FUTURE",
                subject=account.snapshot_id,
                detail="account snapshot as_of is in the future; cash/positions untrusted",
            )
        )
        return _reject_all(plan, audit, daily_counters, manual_approval=False)

    if account_age > max_age_f:
        audit.append(
            _result(
                "DATA_GATE",
                accepted=False,
                code="ACCOUNT_GATE_STALE",
                subject=account.snapshot_id,
                detail="account snapshot exceeds snapshot_max_age_seconds; fail closed",
            )
        )
        return _reject_all(plan, audit, daily_counters, manual_approval=False)

    data_gate_ok = market_age <= max_age_f
    if not data_gate_ok:
        audit.append(
            _result(
                "DATA_GATE",
                accepted=False,
                code="DATA_GATE_STALE",
                subject=market.snapshot_id,
                detail="verified market snapshot exceeds snapshot_max_age_seconds",
            )
        )
    else:
        audit.append(
            _result(
                "DATA_GATE",
                accepted=True,
                code="DATA_GATE_OK",
                subject=market.snapshot_id,
                detail="market and account snapshot ages within max",
            )
        )

    state_by_key = {(s.market, s.symbol): s for s in market.states}
    rejected: set[str] = set()
    candidates: list[OrderIntent] = []

    for intent in plan.intents:
        if intent.plan_id != plan.plan_id:
            rejected.add(intent.intent_id)
            audit.append(
                _result(
                    "DATA_GATE",
                    accepted=False,
                    code="INTENT_PLAN_MISMATCH",
                    subject=intent.intent_id,
                    detail="intent.plan_id mismatch",
                )
            )
            continue

        state = state_by_key.get((intent.market, intent.symbol))
        if state is None:
            rejected.add(intent.intent_id)
            audit.append(
                _result(
                    "DATA_GATE",
                    accepted=False,
                    code="SYMBOL_MISSING",
                    subject=intent.intent_id,
                    detail="symbol absent from verified market snapshot",
                )
            )
            continue

        if state.session_date != market.session_date:
            rejected.add(intent.intent_id)
            audit.append(
                _result(
                    "DATA_GATE",
                    accepted=False,
                    code="SESSION_DATE_MISMATCH",
                    subject=intent.intent_id,
                    detail="symbol session_date mismatch",
                )
            )
            continue

        # Ordinary stale market: forbid new buys; allow sells to continue.
        if not data_gate_ok and intent.side is OrderSide.BUY:
            rejected.add(intent.intent_id)
            audit.append(
                _result(
                    "DATA_GATE",
                    accepted=False,
                    code="DATA_GATE_BUY_BLOCKED",
                    subject=intent.intent_id,
                    detail="new buys forbidden when data gate fails",
                )
            )
            continue

        if state.suspended:
            rejected.add(intent.intent_id)
            audit.append(
                _result(
                    "DATA_GATE",
                    accepted=False,
                    code="SYMBOL_SUSPENDED",
                    subject=intent.intent_id,
                    detail="symbol is suspended",
                )
            )
            continue

        # HK: exact route context lookup before quota; SH/SZ never consume connect context.
        if intent.market is Market.HK:
            resolved = _resolve_hk_connect_context(intent, market)
            if isinstance(resolved, str):
                rejected.add(intent.intent_id)
                audit.append(
                    _result(
                        "DATA_GATE",
                        accepted=False,
                        code=resolved,
                        subject=intent.intent_id,
                        detail="HK connect context lookup failed closed",
                    )
                )
                continue
            if intent.side is OrderSide.BUY and not resolved.buy_quota_available:
                rejected.add(intent.intent_id)
                audit.append(
                    _result(
                        "DATA_GATE",
                        accepted=False,
                        code="BUY_QUOTA_UNAVAILABLE",
                        subject=intent.intent_id,
                        detail="route buy quota unavailable",
                    )
                )
                continue

        candidates.append(intent)

    # --- 2b. Sellable quantity (SELL must not exceed account sellable) ---
    remaining: list[OrderIntent] = []
    for intent in candidates:
        if intent.side is OrderSide.SELL:
            sellable = _sellable_qty(account, intent.market, intent.symbol)
            if sellable is None:
                rejected.add(intent.intent_id)
                audit.append(
                    _result(
                        "SELLABLE",
                        accepted=False,
                        code="SELLABLE_POSITION_MISSING",
                        subject=intent.intent_id,
                        detail="no matching position for sell intent",
                    )
                )
                continue
            if intent.quantity > sellable:
                rejected.add(intent.intent_id)
                audit.append(
                    _result(
                        "SELLABLE",
                        accepted=False,
                        code="SELLABLE_EXCEEDED",
                        subject=intent.intent_id,
                        detail="sell quantity exceeds sellable_quantity",
                    )
                )
                continue
            audit.append(
                _result(
                    "SELLABLE",
                    accepted=True,
                    code="SELLABLE_OK",
                    subject=intent.intent_id,
                    detail="sell quantity within sellable_quantity",
                )
            )
        remaining.append(intent)
    candidates = remaining

    # --- 3. Frozen symbols (before sell-only) ---
    remaining = []
    for intent in candidates:
        if intent.symbol in frozen:
            rejected.add(intent.intent_id)
            audit.append(
                _result(
                    "FROZEN_SYMBOL",
                    accepted=False,
                    code="FROZEN_SYMBOL",
                    subject=intent.intent_id,
                    detail="symbol is frozen",
                )
            )
        else:
            remaining.append(intent)
            audit.append(
                _result(
                    "FROZEN_SYMBOL",
                    accepted=True,
                    code="FROZEN_SYMBOL_OK",
                    subject=intent.intent_id,
                    detail="symbol not frozen",
                )
            )
    candidates = remaining

    # --- 4. Sell-only ---
    remaining = []
    for intent in candidates:
        if sell_only and intent.side is OrderSide.BUY:
            rejected.add(intent.intent_id)
            audit.append(
                _result(
                    "SELL_ONLY",
                    accepted=False,
                    code="SELL_ONLY",
                    subject=intent.intent_id,
                    detail="buys forbidden under sell_only",
                )
            )
        else:
            remaining.append(intent)
            if sell_only:
                audit.append(
                    _result(
                        "SELL_ONLY",
                        accepted=True,
                        code="SELL_ONLY_OK",
                        subject=intent.intent_id,
                        detail="sell allowed under sell_only",
                    )
                )
    candidates = remaining

    # --- 5. Limits (per-order then batch aggregates) ---
    equity = _equity_cny(account, market)

    per_order_ok: list[OrderIntent] = []
    for intent in candidates:
        notional = _intent_notional(intent)
        if notional > max_order_notional:
            rejected.add(intent.intent_id)
            audit.append(
                _result(
                    "LIMIT",
                    accepted=False,
                    code="MAX_ORDER_NOTIONAL",
                    subject=intent.intent_id,
                    detail="order notional exceeds max_order_notional",
                )
            )
            continue

        if intent.side is OrderSide.BUY:
            if equity is None:
                rejected.add(intent.intent_id)
                audit.append(
                    _result(
                        "LIMIT",
                        accepted=False,
                        code="EQUITY_PRICE_MISSING",
                        subject=intent.intent_id,
                        detail="cannot value equity without verified reference prices",
                    )
                )
                continue
            if equity <= 0:
                rejected.add(intent.intent_id)
                audit.append(
                    _result(
                        "LIMIT",
                        accepted=False,
                        code="NON_POSITIVE_EQUITY",
                        subject=intent.intent_id,
                        detail="buys fail closed when equity is non-positive",
                    )
                )
                continue
            projected_qty = _position_qty(account, intent.market, intent.symbol) + intent.quantity
            state = state_by_key[(intent.market, intent.symbol)]
            symbol_value = state.reference_price * Decimal(projected_qty)
            weight = symbol_value / equity
            if weight > max_symbol_weight:
                rejected.add(intent.intent_id)
                audit.append(
                    _result(
                        "LIMIT",
                        accepted=False,
                        code="MAX_SYMBOL_WEIGHT",
                        subject=intent.intent_id,
                        detail="projected symbol weight exceeds max_symbol_weight",
                    )
                )
                continue
        per_order_ok.append(intent)
        audit.append(
            _result(
                "LIMIT",
                accepted=True,
                code="PER_ORDER_LIMIT_OK",
                subject=intent.intent_id,
                detail="per-order notional/weight checks passed",
            )
        )

    buy_batch = [i for i in per_order_ok if i.side is OrderSide.BUY]
    sell_batch = [i for i in per_order_ok if i.side is OrderSide.SELL]
    batch_buy_notional = sum((_intent_notional(i) for i in buy_batch), Decimal("0"))
    projected_daily = daily_counters.buy_notional + batch_buy_notional
    projected_orders = daily_counters.order_count + len(per_order_ok)

    daily_fail = bool(buy_batch) and projected_daily > max_daily_notional
    orders_fail = bool(per_order_ok) and projected_orders > max_orders_per_day

    gross_fail = False
    gross_code = "MAX_GROSS_EXPOSURE"
    gross_detail = "projected gross exposure exceeds max_gross_exposure"
    if buy_batch:
        if equity is None:
            gross_fail = True
            gross_code = "GROSS_PRICE_MISSING"
            gross_detail = "cannot compute projected gross without verified reference prices"
        elif equity <= 0:
            # Defense in depth: buys already rejected per-order; keep batch fail closed.
            gross_fail = True
            gross_code = "NON_POSITIVE_EQUITY"
            gross_detail = "buys fail closed when equity is non-positive"
        else:
            projected_gross = _projected_gross_exposure(account, market, per_order_ok)
            if projected_gross is None:
                gross_fail = True
                gross_code = "GROSS_PRICE_MISSING"
                gross_detail = "cannot compute projected gross without verified reference prices"
            else:
                gross_fail = (projected_gross / equity) > max_gross_exposure

    if daily_fail:
        audit.append(
            _result(
                "LIMIT",
                accepted=False,
                code="MAX_DAILY_NOTIONAL",
                subject=plan.plan_id,
                detail="batch buy notional with counters exceeds max_daily_notional",
            )
        )
        for intent in buy_batch:
            rejected.add(intent.intent_id)

    if orders_fail:
        audit.append(
            _result(
                "LIMIT",
                accepted=False,
                code="MAX_ORDERS_PER_DAY",
                subject=plan.plan_id,
                detail="batch order count with counters exceeds max_orders_per_day",
            )
        )
        for intent in per_order_ok:
            rejected.add(intent.intent_id)

    if gross_fail and not daily_fail and not orders_fail:
        audit.append(
            _result(
                "LIMIT",
                accepted=False,
                code=gross_code,
                subject=plan.plan_id,
                detail=gross_detail,
            )
        )
        for intent in buy_batch:
            rejected.add(intent.intent_id)

    if not daily_fail and not orders_fail and not gross_fail and per_order_ok:
        audit.append(
            _result(
                "LIMIT",
                accepted=True,
                code="BATCH_LIMIT_OK",
                subject=plan.plan_id,
                detail="batch daily/order/gross checks passed",
            )
        )

    approved_intents = tuple(i for i in per_order_ok if i.intent_id not in rejected)
    # Daily notional / gross failures keep sells; order-count failure rejects all.
    if daily_fail and not orders_fail:
        approved_intents = tuple(sell_batch)
        for intent in sell_batch:
            rejected.discard(intent.intent_id)

    approved = tuple(i.intent_id for i in approved_intents)

    added_buy = sum(
        (_intent_notional(i) for i in approved_intents if i.side is OrderSide.BUY),
        Decimal("0"),
    )
    projected = DailyRiskCounters(
        session_date=daily_counters.session_date,
        order_count=daily_counters.order_count + len(approved_intents),
        cancel_count=daily_counters.cancel_count,
        buy_notional=daily_counters.buy_notional + added_buy,
    )

    requires_manual = False
    commands: tuple[OrderCommand, ...] = ()
    verified_approval = _optional_verified_approval(
        approval,
        plan_id=plan.plan_id,
        session_date=market.session_date,
    )

    # F4: only record command-policy success codes when approved intents exist.
    if approved_intents:
        if mode is ExecutionMode.SHADOW:
            audit.append(
                _result(
                    "COMMAND_POLICY",
                    accepted=True,
                    code="SHADOW_READ_ONLY",
                    subject=plan.plan_id,
                    detail="SHADOW does not generate sendable commands",
                )
            )
        elif manual_approval and verified_approval is None:
            requires_manual = True
            audit.append(
                _result(
                    "COMMAND_POLICY",
                    accepted=True,
                    code="MANUAL_APPROVAL_REQUIRED",
                    subject=plan.plan_id,
                    detail="manual_approval blocks command emission",
                )
            )
        else:
            commands = tuple(
                build_order_command(intent=intent, mode=ExecutionMode.PAPER)
                for intent in approved_intents
            )
            audit.append(
                _result(
                    "COMMAND_POLICY",
                    accepted=True,
                    code=(
                        "COMMANDS_EMITTED_AFTER_APPROVAL"
                        if manual_approval and verified_approval is not None
                        else "COMMANDS_EMITTED"
                    ),
                    subject=plan.plan_id,
                    detail=f"emitted {len(commands)} PAPER command(s)",
                )
            )

    if plan.intents and not approved_intents:
        accepted = False
    elif not plan.intents:
        accepted = data_gate_ok
    else:
        accepted = True

    return RiskDecision(
        accepted=accepted,
        plan_id=plan.plan_id,
        rule_results=tuple(audit),
        approved_intent_ids=approved,
        commands=commands,
        projected_counters=projected,
        requires_manual_approval=requires_manual,
    )


def _optional_verified_approval(
    approval: object | None, *, plan_id: str, session_date: dt.date
) -> object | None:
    if approval is None:
        return None
    try:
        receipt, _payload = unpack_verified_approval_receipt(approval)
    except ApprovalReceiptError as error:
        raise RiskInputError(error.code) from None
    if receipt.plan_identity != plan_id:
        raise RiskInputError("APPROVAL_PLAN_DRIFT") from None
    if receipt.session_date != session_date.isoformat():
        raise RiskInputError("APPROVAL_SESSION_DRIFT") from None
    return approval


def _reject_all(
    plan: OrderPlan,
    audit: list[RiskRuleResult],
    counters: DailyRiskCounters,
    *,
    manual_approval: bool,
) -> RiskDecision:
    return RiskDecision(
        accepted=False,
        plan_id=plan.plan_id,
        rule_results=tuple(audit),
        approved_intent_ids=(),
        commands=(),
        projected_counters=counters,
        requires_manual_approval=manual_approval,
    )


def evaluate_cancel_risk(
    cancel: CancelCommand,
    config: TradingConfig,
    counters: DailyRiskCounters,
) -> CancelRiskDecision:
    """Apply the versioned daily cancel limit without performing I/O."""
    result: CancelRiskDecision | None = None
    try:
        if type(cancel) is not CancelCommand:
            raise ValueError
        cancel_id = build_cancel_command_identity(cancel)
        if type(config) is not TradingConfig:
            raise ValueError
        policy_id = trading_config_identity(config)
        checked = DailyRiskCounters(
            session_date=counters.session_date,
            order_count=counters.order_count,
            cancel_count=counters.cancel_count,
            buy_notional=counters.buy_notional,
        )
        limit = _as_int(_select_limits(config, checked.session_date)["max_cancels_per_day"])
        accepted = checked.cancel_count + 1 <= limit
        projected = checked
        if accepted:
            projected = DailyRiskCounters(
                session_date=checked.session_date,
                order_count=checked.order_count,
                cancel_count=checked.cancel_count + 1,
                buy_notional=checked.buy_notional,
            )
        result = CancelRiskDecision(
            accepted=accepted,
            cancel_id=cancel_id,
            code="CANCEL_LIMIT_OK" if accepted else "CANCEL_LIMIT_EXCEEDED",
            policy_identity=policy_id,
            projected_counters=projected,
        )
    except Exception:
        pass
    if result is None:
        raise RiskInputError("CANCEL_RISK_INPUT_INVALID") from None
    return result


__all__ = [
    "CancelRiskDecision",
    "DailyRiskCounters",
    "RiskDecision",
    "RiskInputError",
    "RiskRuleResult",
    "build_daily_risk_counters_identity",
    "deserialize_daily_risk_counters",
    "evaluate_pretrade",
    "serialize_daily_risk_counters",
    "evaluate_cancel_risk",
]
