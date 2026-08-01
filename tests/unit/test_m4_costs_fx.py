from __future__ import annotations

import datetime as dt
from dataclasses import replace
from decimal import Decimal

import pytest

from quant.backtest import (
    ExecutionCostError,
    ExecutionCostPeriod,
    FxContractError,
    FxRate,
    build_execution_cost_schedule,
    build_fx_snapshot,
    calculate_execution_cost,
    convert_money,
)
from quant.domain.enums import ConnectRoute, Currency, Market, OrderSide
from quant.execution.contracts import MoneyAmount, build_order_intent

_DAY = dt.date(2026, 7, 20)
_NOW = dt.datetime(2026, 7, 20, 2, tzinfo=dt.UTC)
_HEX = "a" * 64


def _intent(
    *, market: Market = Market.SH, side: OrderSide = OrderSide.BUY,
    quantity: int = 100,
):
    hk = market is Market.HK
    return build_order_intent(
        plan_id=_HEX,
        symbol="00700.HK" if hk else "600000.SH",
        market=market,
        side=side,
        quantity=quantity,
        limit_price=Decimal("10"),
        quote_currency=Currency.HKD if hk else Currency.CNY,
        session_date=_DAY,
        generated_at=_NOW,
        target_identity="b" * 64,
        market_snapshot_id="c" * 64,
        account_snapshot_id="d" * 64,
        config_identity="e" * 64,
        connect_route=ConnectRoute.SH_CONNECT if hk else None,
    )


def _period(
    *, market: Market = Market.SH, commission: str = "0.0003",
    minimum: str = "5", stamp: str = "0.0005", transfer: str = "0.00001",
    settlement: Currency = Currency.CNY,
) -> ExecutionCostPeriod:
    return ExecutionCostPeriod(
        market=market,
        effective_from=dt.date(2020, 1, 1),
        effective_to=None,
        commission_rate=Decimal(commission),
        commission_min=Decimal(minimum),
        stamp_tax_sell=Decimal(stamp),
        transfer_fee=Decimal(transfer),
        settlement_currency=settlement,
    )


def _schedule(*periods: ExecutionCostPeriod):
    return build_execution_cost_schedule(
        selector="execution_fee_schedule_v1", periods=periods
    )


def _fx(*, expires: dt.datetime = dt.datetime(2026, 7, 20, 8, tzinfo=dt.UTC)):
    return build_fx_snapshot(
        selector="cny_hkd_fx_schedule_v1",
        session_date=_DAY,
        observed_at=dt.datetime(2026, 7, 20, 1, tzinfo=dt.UTC),
        expires_at=expires,
        rates=(FxRate(Currency.HKD, Currency.CNY, Decimal("0.92345")),),
    )


def test_a_share_minimum_commission_and_sell_statutory_fees() -> None:
    schedule = _schedule(_period())
    buy = calculate_execution_cost(
        _intent(), Decimal("10"), 100, schedule, None
    )
    sell = calculate_execution_cost(
        _intent(side=OrderSide.SELL), Decimal("10"), 100, schedule, None
    )
    assert tuple(item.code for item in buy) == (
        "COMMISSION", "STAMP_TAX", "TRANSFER_FEE"
    )
    assert tuple(item.amount.amount for item in buy) == (
        Decimal("5.00"), Decimal("0.00"), Decimal("0.01")
    )
    assert tuple(item.amount.amount for item in sell) == (
        Decimal("5.00"), Decimal("0.50"), Decimal("0.01")
    )
    assert tuple(item.statutory for item in sell) == (False, True, True)


def test_only_commercial_rate_changes_between_cost_scenarios() -> None:
    low = calculate_execution_cost(
        _intent(), Decimal("100"), 100,
        _schedule(_period(commission="0.00015", minimum="0")), None,
    )
    high = calculate_execution_cost(
        _intent(), Decimal("100"), 100,
        _schedule(_period(commission="0.00060", minimum="0")), None,
    )
    assert low[0].amount.amount == Decimal("1.50")
    assert high[0].amount.amount == Decimal("6.00")
    assert low[1:] == high[1:]


def test_hk_fees_convert_to_cny_with_half_up_rounding() -> None:
    schedule = _schedule(
        _period(
            market=Market.HK,
            commission="0.001",
            minimum="0",
            stamp="0",
            transfer="0",
            settlement=Currency.CNY,
        )
    )
    fees = calculate_execution_cost(
        _intent(market=Market.HK), Decimal("10.005"), 100, schedule, _fx()
    )
    assert all(item.amount.currency is Currency.CNY for item in fees)
    assert fees[0].amount.amount == Decimal("0.92")


def test_fx_missing_expired_and_reverse_direction_fail_closed() -> None:
    hk_schedule = _schedule(
        _period(market=Market.HK, settlement=Currency.CNY)
    )
    with pytest.raises(ExecutionCostError, match="^EXECUTION_COST_INPUT_INVALID$"):
        calculate_execution_cost(
            _intent(market=Market.HK), Decimal("10"), 100, hk_schedule, None
        )
    expired = _fx(expires=dt.datetime(2026, 7, 20, 1, 30, tzinfo=dt.UTC))
    with pytest.raises(ExecutionCostError, match="^FX_SNAPSHOT_EXPIRED$"):
        calculate_execution_cost(
            _intent(market=Market.HK), Decimal("10"), 100, hk_schedule, expired
        )
    reverse = build_fx_snapshot(
        selector="cny_hkd_fx_schedule_v1",
        session_date=_DAY,
        observed_at=dt.datetime(2026, 7, 20, 1, tzinfo=dt.UTC),
        expires_at=dt.datetime(2026, 7, 20, 8, tzinfo=dt.UTC),
        rates=(FxRate(Currency.CNY, Currency.HKD, Decimal("1.08")),),
    )
    with pytest.raises(FxContractError, match="^FX_RATE_MISSING$"):
        convert_money(MoneyAmount(Currency.HKD, Decimal("1")), reverse, Currency.CNY)


def test_overlapping_periods_hostile_selector_and_forged_fx_are_rejected() -> None:
    first = replace(_period(), effective_to=dt.date(2026, 12, 31))
    second = replace(_period(), effective_from=dt.date(2026, 12, 31))
    with pytest.raises(ExecutionCostError, match="^EXECUTION_COST_INPUT_INVALID$"):
        _schedule(first, second)
    with pytest.raises(ExecutionCostError, match="^EXECUTION_COST_INPUT_INVALID$"):
        build_execution_cost_schedule(selector="C:\\fees", periods=(_period(),))
    snapshot = _fx()
    with pytest.raises(FxContractError, match="^FX_INPUT_INVALID$"):
        type(snapshot)(
            "f" * 64,
            snapshot.selector,
            snapshot.session_date,
            snapshot.observed_at,
            snapshot.expires_at,
            snapshot.rates,
        )


def test_missing_cost_period_and_invalid_partial_fill_are_stable() -> None:
    with pytest.raises(ExecutionCostError, match="^EXECUTION_COST_PERIOD_MISSING$"):
        calculate_execution_cost(
            _intent(market=Market.HK), Decimal("10"), 100,
            _schedule(_period()), _fx(),
        )
    with pytest.raises(ExecutionCostError, match="^EXECUTION_COST_INPUT_INVALID$"):
        calculate_execution_cost(
            _intent(), Decimal("10"), 101, _schedule(_period()), None
        )
