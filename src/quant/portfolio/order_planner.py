"""Pure route-aware target-to-order planning for M4-B4."""

from __future__ import annotations

import hashlib
import json
import datetime as dt
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, ROUND_FLOOR

from quant.backtest.a_share_execution import (
    AShareRuleConfig,
    build_a_share_rule_config,
    evaluate_a_share_intent,
)
from quant.backtest.connect_execution import (
    ConnectRuleConfig,
    build_connect_rule_config,
    evaluate_connect_intent,
)
from quant.backtest.costs import (
    ExecutionCostPeriod,
    ExecutionCostSchedule,
    build_execution_cost_schedule,
    calculate_execution_cost,
)
from quant.backtest.fx import FxSnapshot, convert_money, require_fx_snapshot_current
from quant.domain.enums import ConnectRoute, Currency, Market, OrderSide
from quant.execution.config import TradingConfig, trading_config_identity
from quant.execution.contracts import (
    AccountSnapshot,
    MoneyAmount,
    OrderIntent,
    OrderIntentSpec,
    OrderPlan,
    OrderPlanDecision,
    OrderPlanReasonClass,
    PositionBalance,
    RuleDecision,
    SymbolMarketState,
    VerifiedConnectMarketContext,
    VerifiedMarketSnapshot,
    build_account_snapshot_identity,
    build_money_amount,
    build_order_intent,
    build_order_plan as build_contract_order_plan,
    build_order_plan_decision,
    build_rule_decision,
    build_verified_market_snapshot_identity,
)

_HEX64 = frozenset("0123456789abcdef")
_PLANNER_RULE_VERSION = "m4-order-planner-v1"
_INPUT_INVALID = "ORDER_PLANNER_INPUT_INVALID"
_STATE_MISSING = "ORDER_PLANNER_MARKET_STATE_MISSING"
_POSITION_TARGET_MISSING = "ORDER_PLANNER_POSITION_TARGET_MISSING"


class OrderPlannerError(ValueError):
    """Stable and path-free M4-B4 planning failure."""


@dataclass(frozen=True, slots=True)
class OrderPlanTarget:
    symbol: str
    market: Market
    connect_route: ConnectRoute | None
    target_weight: Decimal

    def __post_init__(self) -> None:
        if type(self.symbol) is not str or not self.symbol or self.symbol != self.symbol.strip():
            raise OrderPlannerError(_INPUT_INVALID)
        if type(self.market) is not Market:
            raise OrderPlannerError(_INPUT_INVALID)
        if self.market is Market.HK:
            if type(self.connect_route) is not ConnectRoute:
                raise OrderPlannerError(_INPUT_INVALID)
        elif self.connect_route is not None:
            raise OrderPlannerError(_INPUT_INVALID)
        if (
            type(self.target_weight) is not Decimal
            or not self.target_weight.is_finite()
            or not Decimal(0) <= self.target_weight <= Decimal(1)
        ):
            raise OrderPlannerError(_INPUT_INVALID)


@dataclass(frozen=True, slots=True)
class OrderPlannerConfig:
    config_identity: str
    trading_config: TradingConfig
    a_share_rule_config: AShareRuleConfig
    connect_rule_configs: tuple[ConnectRuleConfig, ...]
    execution_cost_schedule: ExecutionCostSchedule
    fx_snapshot: FxSnapshot | None
    minimum_order_notionals: tuple[MoneyAmount, ...]

    def __post_init__(self) -> None:
        try:
            proven = _planner_config_payload(
                trading_config=self.trading_config,
                a_share_rule_config=self.a_share_rule_config,
                connect_rule_configs=self.connect_rule_configs,
                execution_cost_schedule=self.execution_cost_schedule,
                fx_snapshot=self.fx_snapshot,
                minimum_order_notionals=self.minimum_order_notionals,
            )
            expected = _sha256(proven)
            if self.config_identity != expected:
                raise ValueError
        except Exception:
            raise OrderPlannerError(_INPUT_INVALID) from None


def build_order_planner_config(
    *,
    trading_config: TradingConfig,
    a_share_rule_config: AShareRuleConfig,
    connect_rule_configs: tuple[ConnectRuleConfig, ...],
    execution_cost_schedule: ExecutionCostSchedule,
    fx_snapshot: FxSnapshot | None,
    minimum_order_notionals: tuple[MoneyAmount, ...],
) -> OrderPlannerConfig:
    """Build a strict composition of already-public rule, fee and FX contracts."""
    try:
        payload = _planner_config_payload(
            trading_config=trading_config,
            a_share_rule_config=a_share_rule_config,
            connect_rule_configs=connect_rule_configs,
            execution_cost_schedule=execution_cost_schedule,
            fx_snapshot=fx_snapshot,
            minimum_order_notionals=minimum_order_notionals,
        )
        return OrderPlannerConfig(
            config_identity=_sha256(payload),
            trading_config=trading_config,
            a_share_rule_config=a_share_rule_config,
            connect_rule_configs=connect_rule_configs,
            execution_cost_schedule=execution_cost_schedule,
            fx_snapshot=fx_snapshot,
            minimum_order_notionals=minimum_order_notionals,
        )
    except Exception:
        raise OrderPlannerError(_INPUT_INVALID) from None


def build_order_plan(
    *,
    targets: Sequence[OrderPlanTarget],
    target_identity: str,
    market: VerifiedMarketSnapshot,
    account: AccountSnapshot,
    config: OrderPlannerConfig,
) -> OrderPlan:
    """Build a deterministic in-memory plan; accepted sells fund later buys."""
    targets_t, states, positions, contexts = _prove_inputs(
        targets=targets,
        target_identity=target_identity,
        market=market,
        account=account,
        config=config,
    )
    equity, settlement_by_target = _equity_pools(
        targets=targets_t,
        states=states,
        positions=positions,
        account=account,
        config=config,
        at=market.as_of,
    )
    minimums = {item.currency: item.amount for item in config.minimum_order_notionals}
    available_cash = {item.currency: item.available for item in account.cash}
    for settlement in equity:
        available_cash.setdefault(settlement, Decimal(0))
    specs: list[OrderIntentSpec] = []
    decisions: list[OrderPlanDecision] = []
    buy_candidates: list[tuple[OrderPlanTarget, int, int]] = []

    for target in targets_t:
        state = states[(target.market, target.symbol)]
        position = positions.get((target.market, target.symbol))
        current = 0 if position is None else position.quantity
        settlement = settlement_by_target[(target.market, target.symbol)]
        unit_value = _settlement_amount(
            amount=state.reference_price,
            source=state.quote_currency,
            settlement=settlement,
            config=config,
            session_date=market.session_date,
            at=market.as_of,
        )
        desired = int(
            (equity[settlement] * target.target_weight / unit_value).to_integral_value(
                rounding=ROUND_FLOOR
            )
        )
        delta = desired - current
        if delta == 0:
            zero_side = OrderSide.SELL if current > 0 else OrderSide.BUY
            decisions.append(_zero_decision(target, zero_side, 0))
            continue
        side = OrderSide.BUY if delta > 0 else OrderSide.SELL
        requested = abs(delta)
        candidate = _rounded_candidate(
            requested=requested,
            side=side,
            target_quantity=desired,
            state=state,
            position=position,
        )
        if candidate == 0:
            decisions.append(_zero_decision(target, side, requested))
            continue
        if side is OrderSide.BUY:
            buy_candidates.append((target, requested, candidate))
            continue

        intent = _provisional_intent(
            target=target,
            side=side,
            quantity=candidate,
            state=state,
            market=market,
            account=account,
            config=config,
            target_identity=target_identity,
        )
        outcome = _evaluate(
            intent=intent,
            state=state,
            position=position,
            context=_context_for(target, contexts),
            config=config,
        )
        if not outcome.accepted:
            decisions.append(
                _decision(
                    target,
                    side,
                    requested,
                    0,
                    candidate,
                    requested - candidate,
                    outcome,
                    "RULE_REJECTED",
                )
            )
            continue
        notional, _, _ = _cash_components(intent, candidate, config)
        if notional < minimums[settlement]:
            decisions.append(
                _decision(
                    target,
                    side,
                    requested,
                    0,
                    candidate,
                    requested - candidate,
                    _reject("BELOW_MINIMUM_NOTIONAL"),
                    "ECONOMIC_REJECTED",
                )
            )
            continue
        specs.append(_spec_from_intent(intent))
        decisions.append(
            _decision(
                target,
                side,
                requested,
                candidate,
                0,
                requested - candidate,
                outcome,
                "ACCEPTED",
            )
        )
        available_cash[settlement] += _sell_release(intent, candidate, config)

    for target, requested, candidate in buy_candidates:
        state = states[(target.market, target.symbol)]
        position = positions.get((target.market, target.symbol))
        settlement = settlement_by_target[(target.market, target.symbol)]
        intent = _provisional_intent(
            target=target,
            side=OrderSide.BUY,
            quantity=candidate,
            state=state,
            market=market,
            account=account,
            config=config,
            target_identity=target_identity,
        )
        outcome = _evaluate(
            intent=intent,
            state=state,
            position=position,
            context=_context_for(target, contexts),
            config=config,
        )
        if not outcome.accepted:
            decisions.append(
                _decision(
                    target,
                    OrderSide.BUY,
                    requested,
                    0,
                    candidate,
                    requested - candidate,
                    outcome,
                    "RULE_REJECTED",
                )
            )
            continue
        notional, _, _ = _cash_components(intent, candidate, config)
        if notional < minimums[settlement]:
            decisions.append(
                _decision(
                    target,
                    OrderSide.BUY,
                    requested,
                    0,
                    candidate,
                    requested - candidate,
                    _reject("BELOW_MINIMUM_NOTIONAL"),
                    "ECONOMIC_REJECTED",
                )
            )
            continue
        accepted = _affordable_quantity(
            intent=intent,
            requested=candidate,
            available=available_cash[settlement],
            minimum=minimums[settlement],
            lot=state.board_lot,
            config=config,
        )
        if accepted == 0:
            decisions.append(
                _decision(
                    target,
                    OrderSide.BUY,
                    requested,
                    0,
                    candidate,
                    requested - candidate,
                    _reject("INSUFFICIENT_CASH"),
                    "CASH_REJECTED",
                )
            )
            continue
        accepted_intent = _provisional_intent(
            target=target,
            side=OrderSide.BUY,
            quantity=accepted,
            state=state,
            market=market,
            account=account,
            config=config,
            target_identity=target_identity,
        )
        accepted_outcome = _evaluate(
            intent=accepted_intent,
            state=state,
            position=position,
            context=_context_for(target, contexts),
            config=config,
        )
        if not accepted_outcome.accepted:
            raise OrderPlannerError(_INPUT_INVALID)
        cash_cost, _ = _cash_total(accepted_intent, accepted, config)
        available_cash[settlement] -= cash_cost
        specs.append(_spec_from_intent(accepted_intent))
        cash_rejected = candidate - accepted
        decisions.append(
            _decision(
                target,
                OrderSide.BUY,
                requested,
                accepted,
                cash_rejected,
                requested - candidate,
                accepted_outcome,
                "PARTIAL_CASH" if cash_rejected else "ACCEPTED",
            )
        )

    ordered_decisions = tuple(sorted(decisions, key=_decision_sort_key))
    rejections = tuple(
        item.outcome
        for item in ordered_decisions
        if item.reason_class
        in {"RULE_REJECTED", "ECONOMIC_REJECTED", "CASH_REJECTED"}
    )
    residual = tuple(
        build_money_amount(currency, amount)
        for currency, amount in sorted(
            available_cash.items(), key=lambda item: item[0].value
        )
    )
    return build_contract_order_plan(
        target_identity=target_identity,
        market_snapshot_id=market.snapshot_id,
        account_snapshot_id=account.snapshot_id,
        config_identity=config.config_identity,
        intent_specs=specs,
        rejections=rejections,
        residual_cash=residual,
        decisions=ordered_decisions,
    )


def _planner_config_payload(
    *,
    trading_config: TradingConfig,
    a_share_rule_config: AShareRuleConfig,
    connect_rule_configs: tuple[ConnectRuleConfig, ...],
    execution_cost_schedule: ExecutionCostSchedule,
    fx_snapshot: FxSnapshot | None,
    minimum_order_notionals: tuple[MoneyAmount, ...],
) -> dict[str, object]:
    if (
        type(trading_config) is not TradingConfig
        or type(a_share_rule_config) is not AShareRuleConfig
        or type(connect_rule_configs) is not tuple
        or len(connect_rule_configs) != 2
        or any(type(item) is not ConnectRuleConfig for item in connect_rule_configs)
        or type(execution_cost_schedule) is not ExecutionCostSchedule
        or fx_snapshot is not None
        and type(fx_snapshot) is not FxSnapshot
        or type(minimum_order_notionals) is not tuple
        or not minimum_order_notionals
        or any(type(item) is not MoneyAmount for item in minimum_order_notionals)
    ):
        raise ValueError
    trading_id = trading_config_identity(trading_config)
    proven_a = build_a_share_rule_config(
        selector=a_share_rule_config.selector,
        effective_from=a_share_rule_config.effective_from,
        effective_to=a_share_rule_config.effective_to,
    )
    if proven_a != a_share_rule_config:
        raise ValueError
    connect = tuple(
        sorted(connect_rule_configs, key=lambda item: item.route.value)
    )
    if tuple(item.route for item in connect) != (
        ConnectRoute.SH_CONNECT,
        ConnectRoute.SZ_CONNECT,
    ):
        raise ValueError
    proven_connect = tuple(
        build_connect_rule_config(
            selector=item.selector,
            route=item.route,
            effective_from=item.effective_from,
            effective_to=item.effective_to,
        )
        for item in connect
    )
    if proven_connect != connect or connect != connect_rule_configs:
        raise ValueError
    schedule = build_execution_cost_schedule(
        selector=execution_cost_schedule.selector,
        periods=execution_cost_schedule.periods,
    )
    if schedule != execution_cost_schedule:
        raise ValueError
    rules = trading_config.section("rules")
    if (
        rules["a_share_rule_selector"] != proven_a.selector
        or rules["hk_connect_rule_selector"] != connect[0].selector
        or any(item.selector != connect[0].selector for item in connect)
        or rules["fee_schedule_selector"] != schedule.selector
        or fx_snapshot is not None
        and rules["fx_schedule_selector"] != fx_snapshot.selector
    ):
        raise ValueError
    minimums = tuple(
        sorted(minimum_order_notionals, key=lambda item: item.currency.value)
    )
    if minimums != minimum_order_notionals or len(
        {item.currency for item in minimums}
    ) != len(minimums) or any(item.amount <= 0 for item in minimums):
        raise ValueError
    return {
        "schema_version": "m4-order-planner-config-v1",
        "trading_config_identity": trading_id,
        "a_share_rule_identity": proven_a.rule_identity,
        "connect_rule_identities": [item.rule_identity for item in connect],
        "execution_cost_schedule": _schedule_payload(schedule),
        "fx_snapshot_id": None if fx_snapshot is None else fx_snapshot.snapshot_id,
        "minimum_order_notionals": [
            {"currency": item.currency.value, "amount": format(item.amount, "f")}
            for item in minimums
        ],
    }


def _schedule_payload(schedule: ExecutionCostSchedule) -> dict[str, object]:
    return {
        "selector": schedule.selector,
        "periods": [
            {
                "market": item.market.value,
                "effective_from": item.effective_from.isoformat(),
                "effective_to": None
                if item.effective_to is None
                else item.effective_to.isoformat(),
                "commission_rate": format(item.commission_rate, "f"),
                "commission_min": format(item.commission_min, "f"),
                "stamp_tax_sell": format(item.stamp_tax_sell, "f"),
                "transfer_fee": format(item.transfer_fee, "f"),
                "settlement_currency": item.settlement_currency.value,
            }
            for item in schedule.periods
        ],
    }


def _sha256(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _prove_inputs(
    *,
    targets: Sequence[OrderPlanTarget],
    target_identity: str,
    market: VerifiedMarketSnapshot,
    account: AccountSnapshot,
    config: OrderPlannerConfig,
) -> tuple[
    tuple[OrderPlanTarget, ...],
    dict[tuple[Market, str], SymbolMarketState],
    dict[tuple[Market, str], PositionBalance],
    dict[ConnectRoute, VerifiedConnectMarketContext],
]:
    try:
        if (
            isinstance(targets, (str, bytes))
            or not isinstance(targets, Sequence)
            or type(target_identity) is not str
            or len(target_identity) != 64
            or any(char not in _HEX64 for char in target_identity)
            or type(market) is not VerifiedMarketSnapshot
            or type(account) is not AccountSnapshot
            or type(config) is not OrderPlannerConfig
        ):
            raise ValueError
        targets_t = tuple(targets)
        if not targets_t or any(type(item) is not OrderPlanTarget for item in targets_t):
            raise ValueError
        ordered = tuple(sorted(targets_t, key=_target_sort_key))
        if len({(item.market, item.symbol) for item in ordered}) != len(ordered):
            raise ValueError
        if build_verified_market_snapshot_identity(market) != market.snapshot_id:
            raise ValueError
        if build_account_snapshot_identity(account) != account.snapshot_id:
            raise ValueError
        if account.as_of > market.as_of:
            raise ValueError
        OrderPlannerConfig(
            config_identity=config.config_identity,
            trading_config=config.trading_config,
            a_share_rule_config=config.a_share_rule_config,
            connect_rule_configs=config.connect_rule_configs,
            execution_cost_schedule=config.execution_cost_schedule,
            fx_snapshot=config.fx_snapshot,
            minimum_order_notionals=config.minimum_order_notionals,
        )
        states = {(item.market, item.symbol): item for item in market.states}
        positions = {(item.market, item.symbol): item for item in account.positions}
        contexts = {item.route: item for item in market.connect_contexts}
        if any((item.market, item.symbol) not in states for item in ordered):
            raise OrderPlannerError(_STATE_MISSING)
        if any(key not in {(item.market, item.symbol) for item in ordered} for key in positions):
            raise OrderPlannerError(_POSITION_TARGET_MISSING)
        if any(
            target.market is Market.HK and target.connect_route not in contexts
            for target in ordered
        ):
            raise ValueError
        return ordered, states, positions, contexts
    except OrderPlannerError:
        raise
    except Exception:
        raise OrderPlannerError(_INPUT_INVALID) from None


def _equity_pools(
    *,
    targets: tuple[OrderPlanTarget, ...],
    states: Mapping[tuple[Market, str], SymbolMarketState],
    positions: Mapping[tuple[Market, str], PositionBalance],
    account: AccountSnapshot,
    config: OrderPlannerConfig,
    at: dt.datetime,
) -> tuple[dict[Currency, Decimal], dict[tuple[Market, str], Currency]]:
    pools = {item.currency: item.available for item in account.cash}
    settlements: dict[tuple[Market, str], Currency] = {}
    weights: dict[Currency, Decimal] = {}
    for target in targets:
        state = states[(target.market, target.symbol)]
        settlement = _cost_period(
            config.execution_cost_schedule, target.market, state.session_date
        ).settlement_currency
        if settlement not in {
            item.currency for item in config.minimum_order_notionals
        }:
            raise OrderPlannerError(_INPUT_INVALID)
        settlements[(target.market, target.symbol)] = settlement
        if settlement not in pools:
            pools[settlement] = Decimal(0)
        weights[settlement] = weights.get(settlement, Decimal(0)) + target.target_weight
        position = positions.get((target.market, target.symbol))
        if position is not None:
            pools[settlement] += _settlement_amount(
                amount=state.reference_price * position.quantity,
                source=state.quote_currency,
                settlement=settlement,
                config=config,
                session_date=state.session_date,
                at=at,
            )
    if any(value > 1 for value in weights.values()):
        raise OrderPlannerError(_INPUT_INVALID)
    return pools, settlements


def _cost_period(
    schedule: ExecutionCostSchedule, market: Market, session_date: dt.date
) -> ExecutionCostPeriod:
    matches = tuple(
        item
        for item in schedule.periods
        if item.market is market
        and item.effective_from <= session_date
        and (item.effective_to is None or session_date <= item.effective_to)
    )
    if len(matches) != 1:
        raise OrderPlannerError(_INPUT_INVALID)
    return matches[0]


def _settlement_amount(
    *,
    amount: Decimal,
    source: Currency,
    settlement: Currency,
    config: OrderPlannerConfig,
    session_date: dt.date,
    at: dt.datetime,
) -> Decimal:
    money = build_money_amount(source, amount)
    if source is settlement:
        return money.amount
    if config.fx_snapshot is None:
        raise OrderPlannerError(_INPUT_INVALID)
    try:
        current = require_fx_snapshot_current(
            config.fx_snapshot,
            session_date=session_date,
            at=at,
        )
        return convert_money(money, current, settlement).amount
    except Exception:
        raise OrderPlannerError(_INPUT_INVALID) from None


def _rounded_candidate(
    *,
    requested: int,
    side: OrderSide,
    target_quantity: int,
    state: SymbolMarketState,
    position: PositionBalance | None,
) -> int:
    if side is OrderSide.BUY:
        return requested // state.board_lot * state.board_lot
    sellable = 0 if position is None else min(requested, position.sellable_quantity)
    if target_quantity == 0 and position is not None and sellable == position.quantity:
        return sellable
    return sellable // state.board_lot * state.board_lot


def _provisional_intent(
    *,
    target: OrderPlanTarget,
    side: OrderSide,
    quantity: int,
    state: SymbolMarketState,
    market: VerifiedMarketSnapshot,
    account: AccountSnapshot,
    config: OrderPlannerConfig,
    target_identity: str,
) -> OrderIntent:
    return build_order_intent(
        plan_id="0" * 64,
        symbol=target.symbol,
        market=target.market,
        side=side,
        quantity=quantity,
        limit_price=state.reference_price,
        quote_currency=state.quote_currency,
        session_date=market.session_date,
        generated_at=market.as_of,
        target_identity=target_identity,
        market_snapshot_id=market.snapshot_id,
        account_snapshot_id=account.snapshot_id,
        config_identity=config.config_identity,
        connect_route=target.connect_route,
    )


def _evaluate(
    *,
    intent: OrderIntent,
    state: SymbolMarketState,
    position: PositionBalance | None,
    context: VerifiedConnectMarketContext | None,
    config: OrderPlannerConfig,
) -> RuleDecision:
    if intent.market in {Market.SH, Market.SZ}:
        return evaluate_a_share_intent(
            intent, state, position, config.a_share_rule_config
        )
    if context is None or intent.connect_route is None:
        raise OrderPlannerError(_INPUT_INVALID)
    rules = {
        item.route: item for item in config.connect_rule_configs
    }
    return evaluate_connect_intent(
        intent, state, position, context, rules[intent.connect_route]
    )


def _context_for(
    target: OrderPlanTarget,
    contexts: Mapping[ConnectRoute, VerifiedConnectMarketContext],
) -> VerifiedConnectMarketContext | None:
    return None if target.connect_route is None else contexts.get(target.connect_route)


def _cash_total(
    intent: OrderIntent, quantity: int, config: OrderPlannerConfig
) -> tuple[Decimal, Currency]:
    notional, fees, settlement = _cash_components(intent, quantity, config)
    return notional + fees, settlement


def _cash_components(
    intent: OrderIntent, quantity: int, config: OrderPlannerConfig
) -> tuple[Decimal, Decimal, Currency]:
    period = _cost_period(
        config.execution_cost_schedule, intent.market, intent.session_date
    )
    notional = _settlement_amount(
        amount=intent.limit_price * quantity,
        source=intent.quote_currency,
        settlement=period.settlement_currency,
        config=config,
        session_date=intent.session_date,
        at=intent.generated_at,
    )
    fees = calculate_execution_cost(
        intent,
        intent.limit_price,
        quantity,
        config.execution_cost_schedule,
        config.fx_snapshot,
    )
    fee_total = sum((item.amount.amount for item in fees), Decimal(0))
    return notional, fee_total, period.settlement_currency


def _sell_release(
    intent: OrderIntent, quantity: int, config: OrderPlannerConfig
) -> Decimal:
    notional, fees, _ = _cash_components(intent, quantity, config)
    return max(Decimal(0), notional - fees)


def _affordable_quantity(
    *,
    intent: OrderIntent,
    requested: int,
    available: Decimal,
    minimum: Decimal,
    lot: int,
    config: OrderPlannerConfig,
) -> int:
    low, high = 0, requested // lot
    while low < high:
        middle = (low + high + 1) // 2
        quantity = middle * lot
        probe = build_order_intent(
            plan_id=intent.plan_id,
            symbol=intent.symbol,
            market=intent.market,
            side=intent.side,
            quantity=quantity,
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
        total, _ = _cash_total(probe, quantity, config)
        if total <= available:
            low = middle
        else:
            high = middle - 1
    quantity = low * lot
    if quantity == 0:
        return 0
    probe = build_order_intent(
        plan_id=intent.plan_id,
        symbol=intent.symbol,
        market=intent.market,
        side=intent.side,
        quantity=quantity,
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
    notional, _, _ = _cash_components(probe, quantity, config)
    return quantity if notional >= minimum else 0


def _spec_from_intent(intent: OrderIntent) -> OrderIntentSpec:
    return OrderIntentSpec(
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


def _reject(code: str) -> RuleDecision:
    return build_rule_decision(
        accepted=False,
        code=code,
        normalized_quantity=0,
        normalized_limit_price=Decimal(0),
        rule_version=_PLANNER_RULE_VERSION,
    )


def _zero_decision(
    target: OrderPlanTarget, side: OrderSide, requested: int
) -> OrderPlanDecision:
    outcome = build_rule_decision(
        accepted=True,
        code="ZERO_DELTA",
        normalized_quantity=0,
        normalized_limit_price=Decimal(0),
        rule_version=_PLANNER_RULE_VERSION,
    )
    return _decision(
        target,
        side,
        requested,
        0,
        0,
        requested,
        outcome,
        "ZERO_DELTA",
    )


def _decision(
    target: OrderPlanTarget,
    side: OrderSide,
    requested: int,
    accepted: int,
    rejected: int,
    zero: int,
    outcome: RuleDecision,
    reason: OrderPlanReasonClass,
) -> OrderPlanDecision:
    return build_order_plan_decision(
        symbol=target.symbol,
        market=target.market,
        connect_route=target.connect_route,
        side=side,
        requested_quantity=requested,
        accepted_quantity=accepted,
        rejected_quantity=rejected,
        zero_delta_quantity=zero,
        outcome=outcome,
        reason_class=reason,
    )


def _target_sort_key(target: OrderPlanTarget) -> tuple[str, str, str]:
    route = "" if target.connect_route is None else target.connect_route.value
    return target.market.value, target.symbol, route


def _decision_sort_key(
    decision: OrderPlanDecision,
) -> tuple[str, str, str, str]:
    route = "" if decision.connect_route is None else decision.connect_route.value
    return decision.market.value, decision.symbol, route, decision.side.value


__all__ = [
    "OrderPlanTarget",
    "OrderPlannerConfig",
    "OrderPlannerError",
    "build_order_plan",
    "build_order_planner_config",
]
