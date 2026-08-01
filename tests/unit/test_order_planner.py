"""M4-B4 deterministic Target -> OrderPlan tests."""

from __future__ import annotations

import datetime as dt
import hashlib
from decimal import Decimal
from pathlib import Path

import pytest

from quant.backtest.a_share_execution import build_a_share_rule_config
from quant.backtest.connect_execution import build_connect_rule_config
from quant.backtest.costs import ExecutionCostPeriod, build_execution_cost_schedule
from quant.backtest.fx import FxRate, build_fx_snapshot
from quant.domain.enums import ConnectRoute, Currency, Market, OrderSide
from quant.execution.config import load_trading_config
from quant.execution.contracts import (
    build_account_snapshot,
    build_cash_balance,
    build_money_amount,
    build_position_balance,
    build_symbol_market_state,
    build_verified_connect_market_context,
    build_verified_market_snapshot,
)
from quant.portfolio.order_planner import (
    OrderPlannerError,
    OrderPlanTarget,
    build_order_plan,
    build_order_planner_config,
)

DAY = dt.date(2026, 7, 20)
NOW = dt.datetime(2026, 7, 19, 8, tzinfo=dt.UTC)
A_RULE = "a_share_execution_rules_v1"
HK_RULE = "hk_connect_execution_rules_v1"
FEE_RULE = "a_share_research_cost_schedule_v1"


def test_order_planner_public_api_is_importable() -> None:
    from quant.portfolio import (
        OrderPlannerConfig,
        OrderPlannerError,
        OrderPlanTarget,
        build_order_plan,
        build_order_planner_config,
    )

    assert OrderPlannerConfig is not None
    assert OrderPlannerError is not None
    assert OrderPlanTarget is not None
    assert build_order_plan is not None
    assert build_order_planner_config is not None


def _hex(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _config(*, minimum: str = "1"):
    trading = load_trading_config(Path("configs/trading/example.toml"))
    schedule = build_execution_cost_schedule(
        selector=FEE_RULE,
        periods=tuple(
            ExecutionCostPeriod(
                market=market,
                effective_from=dt.date(2026, 1, 1),
                effective_to=dt.date(2026, 12, 31),
                commission_rate=Decimal("0.0003"),
                commission_min=Decimal("5"),
                stamp_tax_sell=Decimal("0.0005"),
                transfer_fee=Decimal("0.00001"),
                settlement_currency=Currency.CNY,
            )
            for market in (Market.HK, Market.SH, Market.SZ)
        ),
    )
    return build_order_planner_config(
        trading_config=trading,
        a_share_rule_config=build_a_share_rule_config(
            selector=A_RULE,
            effective_from=dt.date(2020, 8, 24),
            effective_to=None,
        ),
        connect_rule_configs=tuple(
            build_connect_rule_config(
                selector=HK_RULE,
                route=route,
                effective_from=dt.date(2026, 1, 1),
                effective_to=dt.date(2026, 12, 31),
            )
            for route in (ConnectRoute.SH_CONNECT, ConnectRoute.SZ_CONNECT)
        ),
        execution_cost_schedule=schedule,
        fx_snapshot=build_fx_snapshot(
            selector="cny_hkd_fx_schedule_v1",
            session_date=DAY,
            observed_at=NOW - dt.timedelta(hours=1),
            expires_at=NOW + dt.timedelta(hours=1),
            rates=(FxRate(Currency.HKD, Currency.CNY, Decimal("0.9")),),
        ),
        minimum_order_notionals=(build_money_amount(Currency.CNY, Decimal(minimum)),),
    )


def _state(symbol: str, *, suspended: bool = False):
    market = Market.SH if symbol.endswith(".SH") else Market.SZ
    return build_symbol_market_state(
        symbol=symbol,
        market=market,
        session_date=DAY,
        quote_currency=Currency.CNY,
        reference_price=Decimal("10"),
        limit_up=Decimal("11"),
        limit_down=Decimal("9"),
        suspended=suspended,
        board_lot=100,
        tick_size=Decimal("0.01"),
        rule_version=A_RULE,
    )


def _market(*states, contexts=()):
    return build_verified_market_snapshot(
        as_of=NOW,
        session_date=DAY,
        states=states,
        connect_contexts=contexts,
        calendar_identity=_hex("calendar"),
        source_identity=_hex("source"),
    )


def _account(*, cash: str, positions=()):
    return build_account_snapshot(
        as_of=NOW,
        positions=positions,
        cash=(
            build_cash_balance(
                currency=Currency.CNY,
                settled=Decimal(cash),
                available=Decimal(cash),
                receivable=Decimal(0),
                payable=Decimal(0),
            ),
        ),
    )


def _target(symbol: str, weight: str) -> OrderPlanTarget:
    market = Market.SH if symbol.endswith(".SH") else Market.SZ
    return OrderPlanTarget(symbol, market, None, Decimal(weight))


def test_sell_proceeds_fund_later_buy_without_changing_target_budget() -> None:
    sell = _state("600000.SH")
    buy = _state("000001.SZ")
    position = build_position_balance(
        symbol=sell.symbol,
        market=sell.market,
        quantity=1000,
        sellable_quantity=1000,
        avg_cost=build_money_amount(Currency.CNY, Decimal("8")),
    )
    plan = build_order_plan(
        targets=(_target(buy.symbol, "0.9"), _target(sell.symbol, "0")),
        target_identity=_hex("targets"),
        market=_market(buy, sell),
        account=_account(cash="0", positions=(position,)),
        config=_config(),
    )
    intents = {(item.symbol, item.side): item.quantity for item in plan.intents}
    assert intents[(sell.symbol, OrderSide.SELL)] == 1000
    assert intents[(buy.symbol, OrderSide.BUY)] == 900
    assert plan.residual_cash[0].amount >= 0
    assert sum(item.accepted_quantity for item in plan.decisions) == 1900


def test_rounding_and_economic_rejection_preserve_quantity_conservation() -> None:
    state = _state("600000.SH")
    rounded = build_order_plan(
        targets=(_target(state.symbol, "1"),),
        target_identity=_hex("rounding"),
        market=_market(state),
        account=_account(cash="1500"),
        config=_config(),
    )
    decision = rounded.decisions[0]
    assert decision.requested_quantity == 150
    assert decision.accepted_quantity == 100
    assert decision.zero_delta_quantity == 50

    economic = build_order_plan(
        targets=(_target(state.symbol, "1"),),
        target_identity=_hex("economic"),
        market=_market(state),
        account=_account(cash="1500"),
        config=_config(minimum="2000"),
    )
    assert not economic.intents
    assert economic.decisions[0].reason_class == "ECONOMIC_REJECTED"
    assert economic.rejections == (economic.decisions[0].outcome,)


def test_suspended_rule_rejection_and_missing_state_fail_closed() -> None:
    state = _state("600000.SH", suspended=True)
    plan = build_order_plan(
        targets=(_target(state.symbol, "1"),),
        target_identity=_hex("suspended"),
        market=_market(state),
        account=_account(cash="2000"),
        config=_config(),
    )
    assert plan.decisions[0].reason_class == "RULE_REJECTED"
    assert plan.decisions[0].outcome.code == "SUSPENDED"

    with pytest.raises(OrderPlannerError, match="^ORDER_PLANNER_MARKET_STATE_MISSING$"):
        build_order_plan(
            targets=(_target("000001.SZ", "1"),),
            target_identity=_hex("missing"),
            market=_market(state),
            account=_account(cash="2000"),
            config=_config(),
        )


def test_target_input_order_does_not_change_plan_identity() -> None:
    first = _state("600000.SH")
    second = _state("000001.SZ")
    kwargs = {
        "target_identity": _hex("stable"),
        "market": _market(first, second),
        "account": _account(cash="4000"),
        "config": _config(),
    }
    left = build_order_plan(
        targets=(_target(first.symbol, "0.5"), _target(second.symbol, "0.5")),
        **kwargs,
    )
    right = build_order_plan(
        targets=(_target(second.symbol, "0.5"), _target(first.symbol, "0.5")),
        **kwargs,
    )
    assert left == right
    assert left.plan_id == right.plan_id


def test_direct_config_constructor_rejects_forged_identity() -> None:
    config = _config()
    with pytest.raises(OrderPlannerError, match="^ORDER_PLANNER_INPUT_INVALID$"):
        type(config)(
            config_identity="0" * 64,
            trading_config=config.trading_config,
            a_share_rule_config=config.a_share_rule_config,
            connect_rule_configs=config.connect_rule_configs,
            execution_cost_schedule=config.execution_cost_schedule,
            fx_snapshot=config.fx_snapshot,
            minimum_order_notionals=config.minimum_order_notionals,
        )


def test_hk_target_requires_explicit_route_and_uses_public_fx_contract() -> None:
    state = build_symbol_market_state(
        symbol="00700.HK",
        market=Market.HK,
        session_date=DAY,
        quote_currency=Currency.HKD,
        reference_price=Decimal("100"),
        limit_up=Decimal("110"),
        limit_down=Decimal("90"),
        suspended=False,
        board_lot=100,
        tick_size=Decimal("0.1"),
        rule_version=HK_RULE,
    )
    context = build_verified_connect_market_context(
        route=ConnectRoute.SH_CONNECT,
        session_date=DAY,
        as_of=NOW,
        mainland_open=True,
        hong_kong_open=True,
        buy_quota_available=True,
        calendar_identity=_hex("hk-calendar"),
        quota_identity=_hex("hk-quota"),
        source_identity=_hex("hk-source"),
    )
    account = _account(cash="10000")
    plan = build_order_plan(
        targets=(
            OrderPlanTarget(
                state.symbol,
                Market.HK,
                ConnectRoute.SH_CONNECT,
                Decimal("1"),
            ),
        ),
        target_identity=_hex("hk-target"),
        market=_market(state, contexts=(context,)),
        account=account,
        config=_config(),
    )
    assert plan.intents[0].connect_route is ConnectRoute.SH_CONNECT
    assert plan.intents[0].quantity == 100
    assert plan.residual_cash[0].currency is Currency.CNY

    with pytest.raises(OrderPlannerError, match="^ORDER_PLANNER_INPUT_INVALID$"):
        OrderPlanTarget(state.symbol, Market.HK, None, Decimal("1"))
