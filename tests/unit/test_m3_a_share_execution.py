"""G7D A-share execution pure-contract adversarial tests."""

from __future__ import annotations

import datetime as dt
import importlib
import inspect
import sys
from dataclasses import replace
from decimal import Decimal
from fractions import Fraction

import polars as pl
import pytest

from quant.backtest.a_share_execution import (
    AccountPosition,
    AShareFeeComponents,
    AShareOrderQuantityRule,
    BuyAllocation,
    ExecutionBatch,
    ExecutionFill,
    ExecutionRejection,
    TargetOrderIntent,
    build_target_order_intents,
    compute_a_share_fee_components,
    largest_valid_buy_quantity,
    largest_valid_sell_quantity,
    resolve_a_share_order_quantity_rule,
)
from quant.domain import AShareBoard, ExecutionRejectReason, OrderSide
from quant.research.m3.contracts import AShareCostPeriod

_DAY = dt.date(2026, 7, 14)


def _open_states(rows: list[dict[str, object]]) -> pl.DataFrame:
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


def _targets(rows: list[dict[str, object]]) -> pl.DataFrame:
    defaults: dict[str, object] = {
        "as_of": _DAY - dt.timedelta(days=1),
        "strategy": "topk",
        "strategy_version": "m3_topk_v1",
    }
    return pl.DataFrame([{**defaults, **row} for row in rows]).with_columns(
        pl.col("as_of").cast(pl.Date),
        pl.col("weight").cast(pl.Float64),
    )


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


def test_domain_enums_are_single_source_and_include_g7d_values() -> None:
    assert {item.value for item in AShareBoard} == {
        "SSE_MAIN", "SSE_STAR", "SZSE_MAIN", "SZSE_CHINEXT"
    }
    assert {
        "SUSPENDED", "OPEN_UNKNOWN", "MISSING_OPEN", "BUY_AT_UPPER_LIMIT",
        "SELL_AT_LOWER_LIMIT", "T_PLUS_ONE", "LOT_CONSTRAINT", "CASH_CONSTRAINT",
    } <= {item.value for item in ExecutionRejectReason}
    module = importlib.import_module("quant.backtest.a_share_execution")
    assert module.AShareBoard is AShareBoard
    assert module.ExecutionRejectReason is ExecutionRejectReason


@pytest.mark.parametrize(
    ("symbol", "board", "buy_min", "buy_increment", "sell_min", "sell_increment"),
    [
        ("600000.SH", AShareBoard.SSE_MAIN, 100, 100, 100, 100),
        ("601318.SH", AShareBoard.SSE_MAIN, 100, 100, 100, 100),
        ("603000.SH", AShareBoard.SSE_MAIN, 100, 100, 100, 100),
        ("605000.SH", AShareBoard.SSE_MAIN, 100, 100, 100, 100),
        ("688001.SH", AShareBoard.SSE_STAR, 200, 1, 200, 1),
        ("689001.SH", AShareBoard.SSE_STAR, 200, 1, 200, 1),
        ("000001.SZ", AShareBoard.SZSE_MAIN, 100, 100, 100, 100),
        ("001000.SZ", AShareBoard.SZSE_MAIN, 100, 100, 100, 100),
        ("002001.SZ", AShareBoard.SZSE_MAIN, 100, 100, 100, 100),
        ("003001.SZ", AShareBoard.SZSE_MAIN, 100, 100, 100, 100),
        ("300001.SZ", AShareBoard.SZSE_CHINEXT, 100, 100, 100, 100),
        ("301001.SZ", AShareBoard.SZSE_CHINEXT, 100, 100, 100, 100),
    ],
)
def test_resolve_rule_uses_only_frozen_prefix_and_effective_date(
    symbol: str,
    board: AShareBoard,
    buy_min: int,
    buy_increment: int,
    sell_min: int,
    sell_increment: int,
) -> None:
    rule = resolve_a_share_order_quantity_rule(symbol=symbol, date=_DAY)
    assert rule.rule_version == "sse_szse_limit_order_quantity_v1"
    assert rule.board is board
    assert (
        rule.buy_min_quantity,
        rule.buy_increment,
        rule.sell_min_quantity,
        rule.sell_increment,
    ) == (buy_min, buy_increment, sell_min, sell_increment)
    assert rule.odd_lot_sell_policy == (
        "FULL_BALANCE_BELOW_MIN"
        if board is AShareBoard.SSE_STAR
        else "MATCH_POSITION_REMAINDER"
    )


@pytest.mark.parametrize(
    "symbol",
    [
        "604001.SH", "606001.SH", "687001.SH", "600000.SZ", "300001.SH",
        "004001.SZ", "00700.HK", "510300.SH", "not-a-symbol",
    ],
)
def test_resolve_rule_rejects_unknown_or_suffix_mismatch(symbol: str) -> None:
    with pytest.raises(ValueError):
        resolve_a_share_order_quantity_rule(symbol=symbol, date=_DAY)


def test_resolve_rule_rejects_dates_before_board_exists_and_bool_dates() -> None:
    with pytest.raises(ValueError):
        resolve_a_share_order_quantity_rule(
            symbol="688001.SH", date=dt.date(2019, 7, 21)
        )
    with pytest.raises((TypeError, ValueError)):
        resolve_a_share_order_quantity_rule(symbol="600000.SH", date=True)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("symbol", "requested", "expected"),
    [
        ("600000.SH", 0, 0),
        ("600000.SH", 99, 0),
        ("600000.SH", 100, 100),
        ("600000.SH", 257, 200),
        ("300001.SZ", 399, 300),
        ("688001.SH", 199, 0),
        ("688001.SH", 200, 200),
        ("688001.SH", 257, 257),
    ],
)
def test_largest_valid_buy_quantity(
    symbol: str,
    requested: int,
    expected: int,
) -> None:
    rule = resolve_a_share_order_quantity_rule(symbol=symbol, date=_DAY)
    assert largest_valid_buy_quantity(requested_quantity=requested, rule=rule) == expected


@pytest.mark.parametrize(
    ("symbol", "requested", "position", "expected"),
    [
        ("600000.SH", 157, 257, 157),
        ("600000.SH", 156, 257, 100),
        ("600000.SH", 120, 257, 100),
        ("600000.SH", 256, 257, 200),
        ("600000.SH", 257, 257, 257),
        ("300001.SZ", 57, 257, 57),
        ("688001.SH", 199, 257, 0),
        ("688001.SH", 200, 257, 200),
        ("688001.SH", 256, 257, 256),
        ("688001.SH", 100, 157, 0),
        ("688001.SH", 157, 157, 157),
    ],
)
def test_largest_valid_sell_quantity_respects_remainder_and_star_minimum(
    symbol: str,
    requested: int,
    position: int,
    expected: int,
) -> None:
    rule = resolve_a_share_order_quantity_rule(symbol=symbol, date=_DAY)
    actual = largest_valid_sell_quantity(
        requested_quantity=requested,
        position_quantity=position,
        rule=rule,
    )
    assert actual == expected
    assert 0 <= actual <= min(requested, position)


def test_t_plus_one_and_lot_residual_are_layered_not_whole_order_rejection() -> None:
    rule = resolve_a_share_order_quantity_rule(symbol="600000.SH", date=_DAY)
    requested = 157
    sellable_cap = min(requested, 120)
    filled = largest_valid_sell_quantity(
        requested_quantity=sellable_cap,
        position_quantity=257,
        rule=rule,
    )
    assert filled == 100
    assert requested - sellable_cap == 37
    assert sellable_cap - filled == 20
    assert filled + 37 + 20 == requested


def test_fee_components_use_decimal_and_round_each_component_half_up() -> None:
    buy = compute_a_share_fee_components(
        notional=Decimal("1000"), side=OrderSide.BUY, cost_period=_period()
    )
    sell = compute_a_share_fee_components(
        notional=Decimal("1000"), side=OrderSide.SELL, cost_period=_period()
    )
    assert buy == AShareFeeComponents(
        commission=Decimal("5.00"),
        stamp_tax=Decimal("0.00"),
        transfer_fee=Decimal("0.01"),
    )
    assert sell == AShareFeeComponents(
        commission=Decimal("5.00"),
        stamp_tax=Decimal("0.50"),
        transfer_fee=Decimal("0.01"),
    )
    edge = compute_a_share_fee_components(
        notional=Decimal("101"),
        side=OrderSide.SELL,
        cost_period=_period(
            commission_rate=Decimal("0.04995"),
            commission_min=Decimal("0"),
            stamp_tax_sell=Decimal("0.00005"),
            transfer_fee=Decimal("0.00005"),
        ),
    )
    assert edge.commission == Decimal("5.04")
    assert edge.stamp_tax == Decimal("0.01")
    assert edge.transfer_fee == Decimal("0.01")


def test_fee_rejects_float_bool_negative_and_unknown_side() -> None:
    with pytest.raises((TypeError, ValueError)):
        compute_a_share_fee_components(
            notional=1000.0,  # type: ignore[arg-type]
            side=OrderSide.BUY,
            cost_period=_period(),
        )
    with pytest.raises((TypeError, ValueError)):
        compute_a_share_fee_components(
            notional=Decimal("-1"), side=OrderSide.BUY, cost_period=_period()
        )
    with pytest.raises((TypeError, ValueError)):
        compute_a_share_fee_components(
            notional=Decimal("1"), side="BUY", cost_period=_period()  # type: ignore[arg-type]
        )


def test_target_order_intents_use_pre_trade_equity_decimal_and_zero_clears_all() -> None:
    positions = (
        AccountPosition(
            symbol="600001.SH",
            quantity=257,
            sellable_quantity=120,
            unsettled_quantity=137,
            mark_price=Decimal("9.8"),
        ),
    )
    intents = build_target_order_intents(
        date=_DAY,
        targets=_targets([
            {"symbol": "600000.SH", "weight": 0.1234},
            {"symbol": "600001.SH", "weight": 0.0},
        ]),
        positions=positions,
        open_states=_open_states([
            {"symbol": "600000.SH", "open": 10.0},
            {"symbol": "600001.SH", "open": 10.0},
        ]),
        pre_trade_equity=Decimal("10000"),
    )
    assert tuple(intent.symbol for intent in intents) == ("600000.SH", "600001.SH")
    buy, sell = intents
    assert buy.side is OrderSide.BUY
    assert buy.target_weight == Decimal("0.1234")
    assert buy.target_notional == Decimal("1234.0000")
    assert buy.raw_target_quantity == 123
    assert buy.target_position_quantity == 100
    assert buy.requested_quantity == 100
    assert sell.side is OrderSide.SELL
    assert sell.target_weight == Decimal("0.0")
    assert sell.target_notional == Decimal("0.0")
    assert sell.raw_target_quantity == 0
    assert sell.target_position_quantity == 0
    assert sell.requested_quantity == 257


def test_target_intent_missing_open_and_lot_constraint_remain_auditable() -> None:
    intents = build_target_order_intents(
        date=_DAY,
        targets=_targets([
            {"symbol": "600000.SH", "weight": 0.2},
            {"symbol": "600001.SH", "weight": 0.005},
        ]),
        positions=(),
        open_states=_open_states([
            {
                "symbol": "600000.SH", "open": None, "has_open": False,
                "buy_allowed": False, "sell_allowed": False,
                "reason": "MISSING_OPEN",
            },
            {"symbol": "600001.SH", "open": 10.0},
        ]),
        pre_trade_equity=Decimal("10000"),
    )
    missing, lot = intents
    assert missing.side is OrderSide.BUY
    assert missing.target_notional == Decimal("2000.0")
    assert missing.raw_target_quantity is None
    assert missing.target_position_quantity is None
    assert missing.requested_quantity is None
    assert lot.side is OrderSide.BUY
    assert lot.target_notional == Decimal("50.000")
    assert lot.raw_target_quantity == 5
    assert lot.target_position_quantity == 0
    assert lot.requested_quantity == 0


def test_execution_value_objects_enforce_decimal_and_conservation() -> None:
    rule = resolve_a_share_order_quantity_rule(symbol="600000.SH", date=_DAY)
    intent = TargetOrderIntent(
        symbol="600000.SH",
        side=OrderSide.BUY,
        target_weight=Decimal("0.1"),
        target_notional=Decimal("1000"),
        raw_target_quantity=100,
        target_position_quantity=100,
        requested_quantity=100,
        quantity_rule=rule,
    )
    fees = AShareFeeComponents(
        commission=Decimal("5.00"),
        stamp_tax=Decimal("0.00"),
        transfer_fee=Decimal("0.01"),
    )
    fill = ExecutionFill(
        symbol=intent.symbol,
        side=intent.side,
        quantity=100,
        reference_open=Decimal("10"),
        execution_price=Decimal("10.01"),
        notional=Decimal("1001"),
        fees=fees,
        slippage_cost=Decimal("1"),
    )
    rejection = ExecutionRejection(
        symbol="600001.SH",
        side=OrderSide.SELL,
        reason=ExecutionRejectReason.T_PLUS_ONE,
        requested_quantity=37,
        filled_quantity=0,
        rejected_quantity=37,
        rejected_notional=Decimal("370"),
    )
    position = AccountPosition(
        symbol="600000.SH", quantity=100, sellable_quantity=0,
        unsettled_quantity=100, mark_price=Decimal("10"),
    )
    batch = ExecutionBatch(
        cash=Decimal("8993.99"),
        positions=(position,),
        fills=(fill,),
        rejections=(rejection,),
    )
    allocation = BuyAllocation(lambda_fraction=Fraction(1, 2), batch=batch)
    assert allocation.batch.cash >= Decimal(0)
    assert allocation.lambda_fraction == Fraction(1, 2)
    with pytest.raises(ValueError):
        replace(position, sellable_quantity=101)


def test_quantity_helpers_reject_bool_negative_and_foreign_rule() -> None:
    rule = resolve_a_share_order_quantity_rule(symbol="600000.SH", date=_DAY)
    for value in (-1, True):
        with pytest.raises((TypeError, ValueError)):
            largest_valid_buy_quantity(requested_quantity=value, rule=rule)
    assert largest_valid_sell_quantity(
        requested_quantity=101, position_quantity=100, rule=rule
    ) == 100
    with pytest.raises(ValueError):
        AShareOrderQuantityRule(
            rule_version="future",  # type: ignore[arg-type]
            board=AShareBoard.SSE_MAIN,
            buy_min_quantity=100,
            buy_increment=100,
            sell_min_quantity=100,
            sell_increment=100,
            odd_lot_sell_policy="MATCH_POSITION_REMAINDER",
        )


def test_execution_module_import_is_qlib_free(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in tuple(sys.modules):
        if name == "qlib" or name.startswith("qlib."):
            monkeypatch.delitem(sys.modules, name, raising=False)
    module = importlib.reload(importlib.import_module("quant.backtest.a_share_execution"))
    assert module.AccountPosition.__name__ == AccountPosition.__name__
    assert not any(name == "qlib" or name.startswith("qlib.") for name in sys.modules)
    for function in (
        resolve_a_share_order_quantity_rule,
        largest_valid_buy_quantity,
        largest_valid_sell_quantity,
        compute_a_share_fee_components,
        build_target_order_intents,
    ):
        assert all(
            parameter.kind is inspect.Parameter.KEYWORD_ONLY
            for parameter in inspect.signature(function).parameters.values()
        )
