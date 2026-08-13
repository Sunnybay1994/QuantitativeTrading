"""G7D sell execution and discrete buy-allocation adversarial tests."""

from __future__ import annotations

import datetime as dt
import inspect
from decimal import Decimal
from fractions import Fraction
from typing import cast

import polars as pl
import pytest

from quant.backtest.a_share_execution import (
    AccountPosition,
    TargetOrderIntent,
    allocate_buy_lots,
    execute_sell_intents,
    resolve_a_share_order_quantity_rule,
)
from quant.domain import ExecutionRejectReason, OrderSide
from quant.research.m3.contracts import AShareCostPeriod

_DAY = dt.date(2026, 7, 14)


def _period(**updates: Decimal) -> AShareCostPeriod:
    values = {
        "commission_rate": Decimal("0.00025"),
        "commission_min": Decimal("5"),
        "stamp_tax_sell": Decimal("0.0005"),
        "transfer_fee": Decimal("0.00001"),
        "slippage": Decimal("0.001"),
    }
    values.update(updates)
    return AShareCostPeriod(
        effective_from=dt.date(2023, 8, 28),
        effective_to=None,
        **values,
    )


def _open_states(*rows: dict[str, object]) -> pl.DataFrame:
    defaults: dict[str, object] = {
        "date": _DAY,
        "open": 10.0,
        "has_open": True,
        "full_day_suspended": False,
        "partial_open_status": "NOT_APPLICABLE",
        "has_price_limit": True,
        "up_limit": 11.0,
        "down_limit": 9.0,
        "buy_allowed": True,
        "sell_allowed": True,
        "reason": None,
    }
    return pl.DataFrame([{**defaults, **row} for row in rows]).with_columns(
        pl.col("date").cast(pl.Date),
        pl.col("open", "up_limit", "down_limit").cast(pl.Float64),
    )


def _intent(
    symbol: str,
    side: OrderSide,
    requested: int | None,
    *,
    raw: int | None = None,
    target_quantity: int | None = None,
    target_notional: Decimal = Decimal("1000"),
) -> TargetOrderIntent:
    return TargetOrderIntent(
        symbol=symbol,
        side=side,
        target_weight=Decimal("0.1"),
        target_notional=target_notional,
        raw_target_quantity=requested if raw is None else raw,
        target_position_quantity=requested if target_quantity is None else target_quantity,
        requested_quantity=requested,
        quantity_rule=resolve_a_share_order_quantity_rule(symbol=symbol, date=_DAY),
    )


def _position(
    symbol: str,
    quantity: int,
    *,
    sellable: int | None = None,
    mark: Decimal = Decimal("10"),
) -> AccountPosition:
    available = quantity if sellable is None else sellable
    return AccountPosition(
        symbol=symbol,
        quantity=quantity,
        sellable_quantity=available,
        unsettled_quantity=quantity - available,
        mark_price=mark,
    )


def _sell(
    *,
    intents: tuple[TargetOrderIntent, ...],
    states: pl.DataFrame,
    positions: tuple[AccountPosition, ...],
    cash: Decimal = Decimal("0"),
    period: AShareCostPeriod | None = None,
    tick: Decimal = Decimal("0.01"),
):
    return execute_sell_intents(
        intents=intents,
        open_states=states,
        positions=positions,
        cash=cash,
        cost_period=period or _period(),
        price_tick=tick,
    )


def _buy(
    *,
    intents: tuple[TargetOrderIntent, ...],
    states: pl.DataFrame,
    positions: tuple[AccountPosition, ...] = (),
    cash: Decimal,
    period: AShareCostPeriod | None = None,
    tick: Decimal = Decimal("0.01"),
):
    return allocate_buy_lots(
        intents=intents,
        open_states=states,
        positions=positions,
        cash=cash,
        cost_period=period or _period(),
        price_tick=tick,
    )


def test_execution_entrypoints_are_keyword_only_and_side_specific() -> None:
    for function in (execute_sell_intents, allocate_buy_lots):
        assert all(
            parameter.kind is inspect.Parameter.KEYWORD_ONLY
            for parameter in inspect.signature(function).parameters.values()
        )
    with pytest.raises(ValueError):
        _sell(
            intents=(_intent("600000.SH", OrderSide.BUY, 100),),
            states=_open_states({"symbol": "600000.SH"}),
            positions=(),
        )
    with pytest.raises(ValueError):
        _buy(
            intents=(_intent("600000.SH", OrderSide.SELL, 100),),
            states=_open_states({"symbol": "600000.SH"}),
            cash=Decimal("10000"),
        )


@pytest.mark.parametrize(
    ("side", "state", "expected"),
    [
        (
            OrderSide.BUY,
            {
                "open": None,
                "has_open": False,
                "buy_allowed": False,
                "sell_allowed": False,
                "reason": "MISSING_OPEN",
            },
            ExecutionRejectReason.MISSING_OPEN,
        ),
        (
            OrderSide.BUY,
            {
                "buy_allowed": False,
                "sell_allowed": False,
                "partial_open_status": "OPEN_UNKNOWN",
                "reason": "OPEN_UNKNOWN",
            },
            ExecutionRejectReason.OPEN_UNKNOWN,
        ),
        (
            OrderSide.SELL,
            {
                "full_day_suspended": True,
                "buy_allowed": False,
                "sell_allowed": False,
                "reason": "SUSPENDED",
            },
            ExecutionRejectReason.SUSPENDED,
        ),
        (
            OrderSide.BUY,
            {"open": 10.995, "up_limit": 11.0, "buy_allowed": False, "reason": "BUY_AT_UPPER_LIMIT"},
            ExecutionRejectReason.BUY_AT_UPPER_LIMIT,
        ),
        (
            OrderSide.SELL,
            {"open": 9.005, "down_limit": 9.0, "sell_allowed": False, "reason": "SELL_AT_LOWER_LIMIT"},
            ExecutionRejectReason.SELL_AT_LOWER_LIMIT,
        ),
    ],
)
def test_untrusted_open_then_price_limit_have_fixed_rejection_priority(
    side: OrderSide,
    state: dict[str, object],
    expected: ExecutionRejectReason,
) -> None:
    symbol = "600000.SH"
    intent = _intent(
        symbol,
        side,
        None if expected is ExecutionRejectReason.MISSING_OPEN else 100,
        raw=None if expected is ExecutionRejectReason.MISSING_OPEN else 100,
        target_quantity=None if expected is ExecutionRejectReason.MISSING_OPEN else 100,
        target_notional=Decimal("1234"),
    )
    states = _open_states({"symbol": symbol, **state})
    if side is OrderSide.SELL:
        batch = _sell(intents=(intent,), states=states, positions=(_position(symbol, 100),))
    else:
        batch = _buy(intents=(intent,), states=states, cash=Decimal("10000")).batch
    assert batch.fills == ()
    assert len(batch.rejections) == 1
    rejection = batch.rejections[0]
    assert rejection.reason is expected
    if expected is ExecutionRejectReason.MISSING_OPEN:
        assert rejection.requested_quantity is None
        assert rejection.rejected_quantity is None
        assert rejection.rejected_notional == Decimal("1234")


def test_sell_layers_t_plus_one_then_lot_and_conserves_quantity_and_cash() -> None:
    symbol = "600000.SH"
    batch = _sell(
        intents=(_intent(symbol, OrderSide.SELL, 157, target_notional=Decimal("0")),),
        states=_open_states({"symbol": symbol}),
        positions=(_position(symbol, 257, sellable=120, mark=Decimal("9.8")),),
    )
    assert len(batch.fills) == 1
    fill = batch.fills[0]
    assert fill.quantity == 100
    assert fill.reference_open == Decimal("10.0")
    assert fill.execution_price == Decimal("9.99")
    assert fill.notional == Decimal("999.00")
    assert fill.fees.commission == Decimal("5.00")
    assert fill.fees.stamp_tax == Decimal("0.50")
    assert fill.fees.transfer_fee == Decimal("0.01")
    assert fill.slippage_cost == Decimal("1.00")
    residuals = {item.reason: item.rejected_quantity for item in batch.rejections}
    assert residuals == {
        ExecutionRejectReason.T_PLUS_ONE: 37,
        ExecutionRejectReason.LOT_CONSTRAINT: 20,
    }
    assert fill.quantity + sum(cast(int, value) for value in residuals.values()) == 157
    assert batch.cash == Decimal("993.49")
    position = batch.positions[0]
    assert (position.quantity, position.sellable_quantity, position.unsettled_quantity) == (
        157,
        20,
        137,
    )


def test_decimal_slippage_tick_rounding_and_limit_clamp_both_sides() -> None:
    buy_symbol, sell_symbol = "600000.SH", "600001.SH"
    expensive_slippage = _period(slippage=Decimal("0.1"))
    sold = _sell(
        intents=(_intent(sell_symbol, OrderSide.SELL, 100),),
        states=_open_states(
            {"symbol": sell_symbol, "open": 10.001, "down_limit": 9.50, "up_limit": 11.0}
        ),
        positions=(_position(sell_symbol, 100),),
        period=expensive_slippage,
    )
    assert sold.fills[0].execution_price == Decimal("9.50")

    bought = _buy(
        intents=(_intent(buy_symbol, OrderSide.BUY, 100),),
        states=_open_states(
            {"symbol": buy_symbol, "open": 10.001, "up_limit": 10.50, "down_limit": 9.0}
        ),
        cash=Decimal("2000"),
        period=expensive_slippage,
    )
    assert bought.batch.fills[0].execution_price == Decimal("10.50")


def test_sell_cash_is_available_to_same_day_buy_and_blocked_sell_is_not() -> None:
    sell_symbol, buy_symbol = "600000.SH", "600001.SH"
    sell_intent = _intent(sell_symbol, OrderSide.SELL, 200)
    sell_states = _open_states({"symbol": sell_symbol})
    sold = _sell(
        intents=(sell_intent,),
        states=sell_states,
        positions=(_position(sell_symbol, 200),),
    )
    buy_intent = _intent(buy_symbol, OrderSide.BUY, 100)
    bought = _buy(
        intents=(buy_intent,),
        states=_open_states({"symbol": buy_symbol}),
        positions=sold.positions,
        cash=sold.cash,
    )
    assert bought.batch.fills[0].quantity == 100
    assert bought.batch.cash >= 0

    blocked = _sell(
        intents=(sell_intent,),
        states=_open_states(
            {
                "symbol": sell_symbol,
                "full_day_suspended": True,
                "buy_allowed": False,
                "sell_allowed": False,
                "reason": "SUSPENDED",
            }
        ),
        positions=(_position(sell_symbol, 200),),
    )
    assert blocked.cash == Decimal("0")


def test_fraction_breakpoint_and_cash_residual_use_real_component_fees() -> None:
    symbol = "600000.SH"
    zero_rate_min_fee = _period(
        commission_rate=Decimal("0"),
        commission_min=Decimal("5"),
        stamp_tax_sell=Decimal("0"),
        transfer_fee=Decimal("0.00001"),
        slippage=Decimal("0"),
    )
    allocation = _buy(
        intents=(_intent(symbol, OrderSide.BUY, 300),),
        states=_open_states({"symbol": symbol}),
        cash=Decimal("2005.02"),
        period=zero_rate_min_fee,
    )
    assert allocation.lambda_fraction == Fraction(2, 3)
    assert allocation.batch.fills[0].quantity == 200
    assert allocation.batch.fills[0].fees.commission == Decimal("5.00")
    assert allocation.batch.fills[0].fees.transfer_fee == Decimal("0.02")
    assert allocation.batch.cash == Decimal("0.00")
    assert [(item.reason, item.rejected_quantity) for item in allocation.batch.rejections] == [
        (ExecutionRejectReason.CASH_CONSTRAINT, 100)
    ]


def test_equal_fairness_remainder_uses_symbol_asc_and_input_order_is_irrelevant() -> None:
    low, high = "600000.SH", "600001.SH"
    intents = (
        _intent(high, OrderSide.BUY, 100),
        _intent(low, OrderSide.BUY, 100),
    )
    states = _open_states({"symbol": high}, {"symbol": low})
    first = _buy(intents=intents, states=states, cash=Decimal("1006.01"))
    second = _buy(
        intents=tuple(reversed(intents)),
        states=states.reverse(),
        cash=Decimal("1006.01"),
    )
    assert first == second
    assert first.lambda_fraction == Fraction(0)
    assert [(item.symbol, item.quantity) for item in first.batch.fills] == [(low, 100)]
    assert first.batch.cash == Decimal("0.00")
    assert first.batch.cash >= 0
    assert [(item.symbol, item.reason, item.rejected_quantity) for item in first.batch.rejections] == [
        (high, ExecutionRejectReason.CASH_CONSTRAINT, 100)
    ]


def test_star_activation_breakpoint_is_exact_fraction_not_float() -> None:
    symbol = "688001.SH"
    allocation = _buy(
        intents=(_intent(symbol, OrderSide.BUY, 201),),
        states=_open_states({"symbol": symbol}),
        cash=Decimal("2007"),
        period=_period(slippage=Decimal("0")),
    )
    assert allocation.lambda_fraction == Fraction(200, 201)
    assert allocation.batch.fills[0].quantity == 200
    assert allocation.batch.cash >= 0


def test_lot_residual_precedes_cash_and_each_requested_share_is_counted_once() -> None:
    symbol = "600000.SH"
    allocation = _buy(
        intents=(
            _intent(
                symbol,
                OrderSide.BUY,
                0,
                raw=57,
                target_quantity=0,
                target_notional=Decimal("570"),
            ),
        ),
        states=_open_states({"symbol": symbol}),
        cash=Decimal("0"),
    )
    assert allocation.batch.fills == ()
    assert [(item.reason, item.rejected_quantity) for item in allocation.batch.rejections] == [
        (ExecutionRejectReason.LOT_CONSTRAINT, 57)
    ]
    assert allocation.lambda_fraction is None

    layered = _buy(
        intents=(
            _intent(
                symbol,
                OrderSide.BUY,
                150,
                raw=150,
                target_quantity=150,
                target_notional=Decimal("1500"),
            ),
        ),
        states=_open_states({"symbol": symbol}),
        cash=Decimal("0"),
    )
    assert layered.batch.fills == ()
    assert [(item.reason, item.rejected_quantity) for item in layered.batch.rejections] == [
        (ExecutionRejectReason.LOT_CONSTRAINT, 50),
        (ExecutionRejectReason.CASH_CONSTRAINT, 100),
    ]
    assert sum(cast(int, item.rejected_quantity) for item in layered.batch.rejections) == 150


@pytest.mark.parametrize(
    ("cash", "tick"),
    [(Decimal("-1"), Decimal("0.01")), (Decimal("1"), Decimal("0")), (Decimal("1"), Decimal("NaN"))],
)
def test_allocation_rejects_invalid_cash_and_tick(cash: Decimal, tick: Decimal) -> None:
    with pytest.raises(ValueError):
        _buy(
            intents=(_intent("600000.SH", OrderSide.BUY, 100),),
            states=_open_states({"symbol": "600000.SH"}),
            cash=cash,
            tick=tick,
        )
