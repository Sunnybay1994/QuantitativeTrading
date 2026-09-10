import datetime as dt

import polars as pl
import pytest

from quant.backtest import (
    AShareCostModel,
    DailyMarketState,
    EtfCostModel,
    simulate_daily_targets,
)


SESSION = dt.date(2026, 1, 5)
STOCK = "600000.SH"
ETF = "510300.SH"


def _calendar(*dates: dt.date) -> pl.DataFrame:
    return pl.DataFrame({
        "market": ["SH"] * len(dates),
        "date": list(dates),
        "is_open": [True] * len(dates),
        "is_connect_open": [False] * len(dates),
        "is_half_day": [False] * len(dates),
    })


def _instruments() -> pl.DataFrame:
    return pl.DataFrame({
        "symbol": [STOCK],
        "market": ["SH"],
        "name": ["浦发银行"],
        "instrument_type": ["STOCK"],
        "currency": ["CNY"],
        "list_date": [dt.date(1999, 11, 10)],
        "delist_date": [None],
        "board_lot": [100],
        "status": ["LISTED"],
    })


def _stock_and_etf_instruments() -> pl.DataFrame:
    return pl.DataFrame({
        "symbol": [STOCK, ETF],
        "market": ["SH", "SH"],
        "name": ["浦发银行", "沪深300ETF"],
        "instrument_type": ["STOCK", "ETF"],
        "currency": ["CNY", "CNY"],
        "list_date": [dt.date(1999, 11, 10), dt.date(2012, 5, 28)],
        "delist_date": [None, None],
        "board_lot": [100, 100],
        "status": ["LISTED", "LISTED"],
    })


def _bar(
    date: dt.date = SESSION,
    *,
    open_price: float = 10.0,
    close_price: float = 10.0,
) -> pl.DataFrame:
    high = max(open_price, close_price)
    low = min(open_price, close_price)
    return pl.DataFrame({
        "symbol": [STOCK],
        "trade_date": [date],
        "open": [open_price],
        "high": [high],
        "low": [low],
        "close": [close_price],
        "volume": [1_000.0],
        "amount": [10_000.0],
        "adj_factor": [1.0],
        "source": ["fixture"],
    })


def _stock_and_etf_bars(*dates: dt.date) -> pl.DataFrame:
    rows = [
        {
            "symbol": symbol,
            "trade_date": date,
            "open": price,
            "high": price,
            "low": price,
            "close": price,
            "volume": 1_000.0,
            "amount": price * 1_000.0,
            "adj_factor": 1.0,
            "source": "fixture",
        }
        for date in dates
        for symbol, price in ((STOCK, 10.0), (ETF, 4.0))
    ]
    return pl.DataFrame(rows)


def _target(weight: float) -> pl.DataFrame:
    return pl.DataFrame({
        "as_of": [SESSION - dt.timedelta(days=3)],
        "strategy": ["m2-u1"],
        "strategy_version": ["1"],
        "symbol": [STOCK],
        "weight": [weight],
        "execution_date": [SESSION],
    })


def _empty_targets() -> pl.DataFrame:
    return pl.DataFrame(
        schema={
            "as_of": pl.Date,
            "strategy": pl.String,
            "strategy_version": pl.String,
            "symbol": pl.String,
            "weight": pl.Float64,
            "execution_date": pl.Date,
        }
    )


def _initial_position(
    *,
    quantity: int,
    settled_quantity: int,
    mark_price: float = 10.0,
) -> pl.DataFrame:
    return pl.DataFrame({
        "symbol": [STOCK],
        "quantity": [quantity],
        "settled_quantity": [settled_quantity],
        "mark_price": [mark_price],
    })


def _stock_costs() -> AShareCostModel:
    return AShareCostModel(
        commission_rate=0.0,
        commission_min=0.0,
        stamp_tax_sell=0.0,
        transfer_fee=0.0,
        slippage=0.0,
        effective_from=dt.date(2026, 1, 1),
    )


def _stock_costs_scaled(scale: float) -> AShareCostModel:
    return AShareCostModel(
        commission_rate=0.00025 * scale,
        commission_min=5.0 * scale,
        stamp_tax_sell=0.0005,
        transfer_fee=0.00001,
        slippage=0.001 * scale,
        effective_from=dt.date(2026, 1, 1),
    )


def _etf_costs() -> EtfCostModel:
    return EtfCostModel(
        commission_rate=0.0,
        commission_min=0.0,
        slippage=0.0,
        effective_from=dt.date(2026, 1, 1),
    )


def _etf_costs_scaled(scale: float) -> EtfCostModel:
    return EtfCostModel(
        commission_rate=0.0001 * scale,
        commission_min=5.0 * scale,
        slippage=0.001 * scale,
        effective_from=dt.date(2026, 1, 1),
    )


def _simulate(
    *,
    bars: pl.DataFrame,
    target_weight: float,
    state: DailyMarketState,
    initial_cash: float = 1_000.0,
    initial_position: pl.DataFrame | None = None,
):
    return simulate_daily_targets(
        calendar=_calendar(SESSION),
        bars=bars,
        scheduled_targets=_target(target_weight),
        instruments=_instruments(),
        market_states={(SESSION, STOCK): state},
        initial_cash=initial_cash,
        etf_costs=_etf_costs(),
        stock_costs=_stock_costs(),
        strategy="m2-u1",
        initial_positions=initial_position,
    )


def test_full_day_suspension_without_bar_carries_mark_and_rejects_sale() -> None:
    result = _simulate(
        bars=_bar().head(0),
        target_weight=0.0,
        state=DailyMarketState(suspended=True),
        initial_position=_initial_position(quantity=100, settled_quantity=100),
    )

    assert result.nav.item(0, "market_value") == pytest.approx(1_000.0)
    assert result.positions.item(0, "quantity") == 100
    assert result.positions.item(0, "mark_price") == pytest.approx(10.0)
    assert result.trades.height == 0
    assert result.rejections.select(
        "symbol",
        "side",
        "reason",
        "requested_quantity",
        "rejected_quantity",
        "reference_price",
    ).row(0) == (STOCK, "SELL", "SUSPENDED", 100, 100, 10.0)


@pytest.mark.parametrize(("cash", "quantity", "final_cash"), [(2006.,200,1992.), (2005.9,100,1992.9)])
def test_early_share_based_fee_affects_affordability_and_realized_cash(cash, quantity, final_cash):
    from dataclasses import replace

    first, second = dt.date(2014,1,2), dt.date(2014,1,3)
    targets = pl.concat([_target(weight).with_columns(
        pl.lit(date-dt.timedelta(days=1)).alias("as_of"), pl.lit(date).alias("execution_date"))
        for date,weight in ((first,1.),(second,0.))])
    costs = AShareCostModel(.00025,5.,.0005,.00001,0.,dt.date(2010,1,1),historical_statutory_fees=True)
    result = simulate_daily_targets(calendar=_calendar(first,second),bars=pl.concat([_bar(first),_bar(second)]),
        scheduled_targets=targets,instruments=_instruments(),initial_cash=cash,strategy="m2-u1",
        market_states={(date,STOCK):DailyMarketState() for date in (first,second)},
        stock_costs=costs,etf_costs=replace(_etf_costs(),effective_from=dt.date(2010,1,1)))
    assert result.trades["quantity"].to_list() == [quantity,quantity]
    assert result.nav["cash"][-1] == pytest.approx(final_cash)


def test_missing_bar_is_not_inferred_as_suspension() -> None:
    with pytest.raises(ValueError, match="BACKTEST_TRADABLE_BAR_MISSING"):
        _simulate(
            bars=_bar().head(0),
            target_weight=0.0,
            state=DailyMarketState(),
            initial_position=_initial_position(quantity=100, settled_quantity=100),
        )


def test_initial_position_without_target_has_unknown_target_weight() -> None:
    result = simulate_daily_targets(
        calendar=_calendar(SESSION),
        bars=_bar(),
        scheduled_targets=_empty_targets(),
        instruments=_instruments(),
        market_states={(SESSION, STOCK): DailyMarketState()},
        initial_cash=1_000.0,
        etf_costs=_etf_costs(),
        stock_costs=_stock_costs(),
        strategy="m2-u1",
        initial_positions=_initial_position(
            quantity=100,
            settled_quantity=100,
        ),
    )

    assert result.trades.height == 0
    assert result.rejections.height == 0
    assert result.positions.item(0, "target_weight") is None


def test_initial_position_requires_positive_carried_mark() -> None:
    initial = _initial_position(
        quantity=100,
        settled_quantity=100,
    ).with_columns(pl.lit(None, dtype=pl.Float64).alias("mark_price"))

    with pytest.raises(ValueError, match="BACKTEST_INITIAL_MARK_MISSING"):
        simulate_daily_targets(
            calendar=_calendar(SESSION),
            bars=_bar(),
            scheduled_targets=_empty_targets(),
            instruments=_instruments(),
            market_states={(SESSION, STOCK): DailyMarketState()},
            initial_cash=1_000.0,
            etf_costs=_etf_costs(),
            stock_costs=_stock_costs(),
            strategy="m2-u1",
            initial_positions=initial,
        )


@pytest.mark.parametrize("initial_cash", [0.0, -1.0, float("nan")])
def test_initial_cash_must_be_positive_and_finite(initial_cash: float) -> None:
    with pytest.raises(ValueError, match="BACKTEST_ACCOUNT_INVARIANT_BROKEN"):
        simulate_daily_targets(
            calendar=_calendar(SESSION),
            bars=_bar(),
            scheduled_targets=_empty_targets(),
            instruments=_instruments(),
            market_states={(SESSION, STOCK): DailyMarketState()},
            initial_cash=initial_cash,
            etf_costs=_etf_costs(),
            stock_costs=_stock_costs(),
            strategy="m2-u1",
        )


def test_sell_fee_must_not_leave_even_slightly_negative_cash() -> None:
    instrument = _stock_and_etf_instruments().filter(
        pl.col("symbol") == ETF
    ).with_columns(pl.lit(1).alias("board_lot"))
    bars = _stock_and_etf_bars(SESSION).filter(
        pl.col("symbol") == ETF
    ).with_columns(
        pl.lit(1.0).alias("open"),
        pl.lit(1.0).alias("high"),
        pl.lit(1.0).alias("low"),
        pl.lit(1.0).alias("close"),
    )
    targets = _target(0.5).with_columns(pl.lit(ETF).alias("symbol"))
    initial = pl.DataFrame({
        "symbol": [ETF],
        "quantity": [2],
        "settled_quantity": [2],
        "mark_price": [1.0],
    })

    with pytest.raises(ValueError, match="BACKTEST_ACCOUNT_INVARIANT_BROKEN"):
        simulate_daily_targets(
            calendar=_calendar(SESSION),
            bars=bars,
            scheduled_targets=targets,
            instruments=instrument,
            market_states={(SESSION, ETF): DailyMarketState()},
            initial_cash=1e-12,
            etf_costs=EtfCostModel(
                commission_rate=0.0,
                commission_min=1.000000006,
                slippage=0.0,
                effective_from=dt.date(2026, 1, 1),
            ),
            stock_costs=_stock_costs(),
            strategy="m2-u1",
            initial_positions=initial,
        )


def test_missing_market_state_fails_before_silently_skipping_intent() -> None:
    with pytest.raises(ValueError, match="BACKTEST_MARKET_STATE_MISSING"):
        simulate_daily_targets(
            calendar=_calendar(SESSION),
            bars=_bar(),
            scheduled_targets=_target(1.0),
            instruments=_instruments(),
            market_states={},
            initial_cash=10_000.0,
            etf_costs=_etf_costs(),
            stock_costs=_stock_costs(),
            strategy="m2-u1",
        )


def test_target_execution_date_requires_calendar_coverage() -> None:
    targets = _target(1.0).with_columns(
        pl.lit(SESSION + dt.timedelta(days=1)).alias("execution_date")
    )
    with pytest.raises(ValueError, match="BACKTEST_CALENDAR_COVERAGE_MISSING"):
        simulate_daily_targets(
            calendar=_calendar(SESSION),
            bars=_bar(),
            scheduled_targets=targets,
            instruments=_instruments(),
            market_states={(SESSION, STOCK): DailyMarketState()},
            initial_cash=10_000.0,
            etf_costs=_etf_costs(),
            stock_costs=_stock_costs(),
            strategy="m2-u1",
        )


def test_calendar_coverage_is_checked_for_instrument_market() -> None:
    hk_only_calendar = _calendar(SESSION).with_columns(
        pl.lit("HK").alias("market")
    )
    with pytest.raises(ValueError, match="BACKTEST_CALENDAR_COVERAGE_MISSING"):
        simulate_daily_targets(
            calendar=hk_only_calendar,
            bars=_bar(),
            scheduled_targets=_target(1.0),
            instruments=_instruments(),
            market_states={(SESSION, STOCK): DailyMarketState()},
            initial_cash=10_000.0,
            etf_costs=_etf_costs(),
            stock_costs=_stock_costs(),
            strategy="m2-u1",
        )


def test_closed_market_rejects_unexpected_bar_on_other_market_session() -> None:
    sz_symbol = "000001.SZ"
    calendar = pl.DataFrame({
        "market": ["SH", "SZ"],
        "date": [SESSION, SESSION],
        "is_open": [False, True],
        "is_connect_open": [False, False],
        "is_half_day": [False, False],
    })
    instruments = pl.DataFrame({
        "symbol": [STOCK, sz_symbol],
        "market": ["SH", "SZ"],
        "name": ["浦发银行", "平安银行"],
        "instrument_type": ["STOCK", "STOCK"],
        "currency": ["CNY", "CNY"],
        "list_date": [dt.date(1999, 11, 10), dt.date(1991, 4, 3)],
        "delist_date": [None, None],
        "board_lot": [100, 100],
        "status": ["LISTED", "LISTED"],
    })
    bars = pl.concat([
        _bar(),
        _bar().with_columns(pl.lit(sz_symbol).alias("symbol")),
    ])
    initial = pl.DataFrame({
        "symbol": [STOCK, sz_symbol],
        "quantity": [100, 100],
        "settled_quantity": [100, 100],
        "mark_price": [10.0, 10.0],
    })

    with pytest.raises(ValueError, match="BACKTEST_CALENDAR_COVERAGE_MISSING"):
        simulate_daily_targets(
            calendar=calendar,
            bars=bars,
            scheduled_targets=_empty_targets(),
            instruments=instruments,
            market_states={(SESSION, sz_symbol): DailyMarketState()},
            initial_cash=1_000.0,
            etf_costs=_etf_costs(),
            stock_costs=_stock_costs(),
            strategy="m2-u1",
            initial_positions=initial,
        )


def test_missing_calendar_row_for_active_market_fails_closed() -> None:
    sz_symbol = "000001.SZ"
    instruments = pl.concat([
        _instruments(),
        _instruments().with_columns(
            pl.lit(sz_symbol).alias("symbol"),
            pl.lit("SZ").alias("market"),
        ),
    ])
    initial = pl.DataFrame({
        "symbol": [STOCK, sz_symbol],
        "quantity": [100, 100],
        "settled_quantity": [100, 100],
        "mark_price": [10.0, 10.0],
    })
    with pytest.raises(ValueError, match="BACKTEST_CALENDAR_COVERAGE_MISSING"):
        simulate_daily_targets(
            calendar=_calendar(SESSION),
            bars=_bar(),
            scheduled_targets=_empty_targets(),
            instruments=instruments,
            market_states={(SESSION, STOCK): DailyMarketState()},
            initial_cash=1_000.0,
            etf_costs=_etf_costs(),
            stock_costs=_stock_costs(),
            strategy="m2-u1",
            initial_positions=initial,
        )


def test_suspended_new_target_uses_prior_close_for_rejection() -> None:
    previous = SESSION - dt.timedelta(days=3)
    result = simulate_daily_targets(
        calendar=_calendar(SESSION),
        bars=_bar(previous, close_price=9.5),
        scheduled_targets=_target(1.0),
        instruments=_instruments(),
        market_states={(SESSION, STOCK): DailyMarketState(suspended=True)},
        initial_cash=10_000.0,
        etf_costs=_etf_costs(),
        stock_costs=_stock_costs(),
        strategy="m2-u1",
    )
    assert result.trades.is_empty()
    assert result.rejections.row(0, named=True) == {
        "strategy": "m2-u1",
        "date": SESSION,
        "symbol": STOCK,
        "side": "BUY",
        "reason": "SUSPENDED",
        "requested_quantity": 1_000,
        "rejected_quantity": 1_000,
        "reference_price": 9.5,
    }
    assert result.positions.row(0, named=True)["mark_price"] == 9.5


def test_execution_batch_rejects_duplicate_symbol_from_distinct_signals() -> None:
    targets = pl.concat([
        _target(0.5),
        _target(0.5).with_columns(
            pl.lit(SESSION - dt.timedelta(days=2)).alias("as_of")
        ),
    ])
    with pytest.raises(ValueError, match="BACKTEST_TARGET_BATCH_INVALID"):
        simulate_daily_targets(
            calendar=_calendar(SESSION),
            bars=_bar(),
            scheduled_targets=targets,
            instruments=_instruments(),
            market_states={(SESSION, STOCK): DailyMarketState()},
            initial_cash=10_000.0,
            etf_costs=_etf_costs(),
            stock_costs=_stock_costs(),
            strategy="m2-u1",
        )


def test_execution_batch_rejects_total_weight_above_one() -> None:
    targets = pl.concat([
        _target(0.6),
        _target(0.5).with_columns(pl.lit(ETF).alias("symbol")),
    ])

    with pytest.raises(ValueError, match="BACKTEST_TARGET_BATCH_INVALID"):
        simulate_daily_targets(
            calendar=_calendar(SESSION),
            bars=_stock_and_etf_bars(SESSION),
            scheduled_targets=targets,
            instruments=_stock_and_etf_instruments(),
            market_states={
                (SESSION, STOCK): DailyMarketState(),
                (SESSION, ETF): DailyMarketState(),
            },
            initial_cash=10_000.0,
            etf_costs=_etf_costs(),
            stock_costs=_stock_costs(),
            strategy="m2-u1",
        )


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("as_of", SESSION - dt.timedelta(days=2)),
        ("strategy_version", "2"),
    ],
)
def test_execution_batch_has_one_signal_identity(
    column: str, value: object
) -> None:
    targets = pl.concat([
        _target(0.5),
        _target(0.5).with_columns(
            pl.lit(ETF).alias("symbol"),
            pl.lit(value).alias(column),
        ),
    ])
    with pytest.raises(ValueError, match="BACKTEST_TARGET_BATCH_INVALID"):
        simulate_daily_targets(
            calendar=_calendar(SESSION),
            bars=_stock_and_etf_bars(SESSION),
            scheduled_targets=targets,
            instruments=_stock_and_etf_instruments(),
            market_states={
                (SESSION, STOCK): DailyMarketState(),
                (SESSION, ETF): DailyMarketState(),
            },
            initial_cash=10_000.0,
            etf_costs=_etf_costs(),
            stock_costs=_stock_costs(),
            strategy="m2-u1",
        )


def test_target_strategy_must_match_simulation_strategy() -> None:
    with pytest.raises(ValueError, match="BACKTEST_TARGET_BATCH_INVALID"):
        simulate_daily_targets(
            calendar=_calendar(SESSION),
            bars=_bar(),
            scheduled_targets=_target(1.0).with_columns(
                pl.lit("another-strategy").alias("strategy")
            ),
            instruments=_instruments(),
            market_states={(SESSION, STOCK): DailyMarketState()},
            initial_cash=10_000.0,
            etf_costs=_etf_costs(),
            stock_costs=_stock_costs(),
            strategy="m2-u1",
        )


def test_target_must_precede_execution_date() -> None:
    with pytest.raises(ValueError, match="BACKTEST_TARGET_BATCH_INVALID"):
        simulate_daily_targets(
            calendar=_calendar(SESSION),
            bars=_bar(),
            scheduled_targets=_target(1.0).with_columns(
                pl.lit(SESSION).alias("as_of")
            ),
            instruments=_instruments(),
            market_states={(SESSION, STOCK): DailyMarketState()},
            initial_cash=10_000.0,
            etf_costs=_etf_costs(),
            stock_costs=_stock_costs(),
            strategy="m2-u1",
        )


def test_target_symbol_requires_explicit_instrument_policy() -> None:
    with pytest.raises(ValueError, match="BACKTEST_INSTRUMENT_POLICY_MISSING"):
        simulate_daily_targets(
            calendar=_calendar(SESSION),
            bars=_bar(),
            scheduled_targets=_target(1.0),
            instruments=_instruments().head(0),
            market_states={(SESSION, STOCK): DailyMarketState()},
            initial_cash=10_000.0,
            etf_costs=_etf_costs(),
            stock_costs=_stock_costs(),
            strategy="m2-u1",
        )


def test_hk_security_is_not_assigned_a_share_execution_policy() -> None:
    hk_symbol = "00700.HK"
    hk_instrument = _instruments().with_columns(
        pl.lit(hk_symbol).alias("symbol"),
        pl.lit("HK").alias("market"),
        pl.lit("HKD").alias("currency"),
    )
    hk_bar = _bar().with_columns(pl.lit(hk_symbol).alias("symbol"))
    hk_target = _target(1.0).with_columns(
        pl.lit(hk_symbol).alias("symbol")
    )
    with pytest.raises(ValueError, match="BACKTEST_INSTRUMENT_POLICY_MISSING"):
        simulate_daily_targets(
            calendar=_calendar(SESSION).with_columns(
                pl.lit("HK").alias("market")
            ),
            bars=hk_bar,
            scheduled_targets=hk_target,
            instruments=hk_instrument,
            market_states={(SESSION, hk_symbol): DailyMarketState()},
            initial_cash=10_000.0,
            etf_costs=_etf_costs(),
            stock_costs=_stock_costs(),
            strategy="m2-u1",
        )


@pytest.mark.parametrize(
    "execution_date",
    ["2026-01-05", None, dt.datetime(2026, 1, 5)],
)
def test_execution_date_requires_non_null_date_dtype(
    execution_date: object,
) -> None:
    targets = _target(1.0).with_columns(
        pl.lit(execution_date).alias("execution_date")
    )
    with pytest.raises(ValueError, match="BACKTEST_TARGET_BATCH_INVALID"):
        simulate_daily_targets(
            calendar=_calendar(SESSION),
            bars=_bar(),
            scheduled_targets=targets,
            instruments=_instruments(),
            market_states={(SESSION, STOCK): DailyMarketState()},
            initial_cash=10_000.0,
            etf_costs=_etf_costs(),
            stock_costs=_stock_costs(),
            strategy="m2-u1",
        )


@pytest.mark.parametrize(
    ("list_date", "delist_date"),
    [
        (SESSION + dt.timedelta(days=1), None),
        (dt.date(1999, 11, 10), SESSION - dt.timedelta(days=1)),
    ],
)
def test_instrument_must_be_active_on_execution_date(
    list_date: dt.date,
    delist_date: dt.date | None,
) -> None:
    instrument = _instruments().with_columns(
        pl.lit(list_date).alias("list_date"),
        pl.lit(delist_date, dtype=pl.Date).alias("delist_date"),
    )
    with pytest.raises(ValueError, match="BACKTEST_INSTRUMENT_POLICY_MISSING"):
        simulate_daily_targets(
            calendar=_calendar(SESSION),
            bars=_bar(),
            scheduled_targets=_target(1.0),
            instruments=instrument,
            market_states={(SESSION, STOCK): DailyMarketState()},
            initial_cash=10_000.0,
            etf_costs=_etf_costs(),
            stock_costs=_stock_costs(),
            strategy="m2-u1",
        )


def test_trade_before_cost_effective_date_fails_closed() -> None:
    future_cost = AShareCostModel(
        commission_rate=0.00025,
        commission_min=5.0,
        stamp_tax_sell=0.0005,
        transfer_fee=0.00001,
        slippage=0.001,
        effective_from=SESSION + dt.timedelta(days=1),
    )

    with pytest.raises(ValueError, match="BACKTEST_COST_NOT_EFFECTIVE"):
        simulate_daily_targets(
            calendar=_calendar(SESSION),
            bars=_bar(),
            scheduled_targets=_target(1.0),
            instruments=_instruments(),
            market_states={(SESSION, STOCK): DailyMarketState()},
            initial_cash=10_000.0,
            etf_costs=_etf_costs(),
            stock_costs=future_cost,
            strategy="m2-u1",
        )


@pytest.mark.parametrize(
    ("target_weight", "initial_position", "state", "side", "reason"),
    [
        (
            1.0,
            None,
            DailyMarketState(at_upper_limit=True),
            "BUY",
            "BUY_AT_UPPER_LIMIT",
        ),
        (
            0.0,
            _initial_position(quantity=100, settled_quantity=100),
            DailyMarketState(at_lower_limit=True),
            "SELL",
            "SELL_AT_LOWER_LIMIT",
        ),
    ],
)
def test_open_price_limits_create_explicit_rejections(
    target_weight: float,
    initial_position: pl.DataFrame | None,
    state: DailyMarketState,
    side: str,
    reason: str,
) -> None:
    result = _simulate(
        bars=_bar(),
        target_weight=target_weight,
        state=state,
        initial_cash=1_000.0,
        initial_position=initial_position,
    )

    assert result.trades.height == 0
    assert result.rejections.select("symbol", "side", "reason").row(0) == (
        STOCK,
        side,
        reason,
    )


def test_bar_close_shape_does_not_create_lookahead_rejection() -> None:
    result = _simulate(
        bars=_bar(open_price=9.5, close_price=10.0),
        target_weight=1.0,
        state=DailyMarketState(),
        initial_cash=10_000.0,
    )

    assert result.rejections.height == 0
    assert result.trades.select("side", "quantity").row(0) == ("BUY", 1_000)


def test_t_plus_one_rejects_entire_sale_and_preserves_position() -> None:
    result = _simulate(
        bars=_bar(),
        target_weight=0.0,
        state=DailyMarketState(),
        initial_position=_initial_position(quantity=200, settled_quantity=100),
    )

    assert result.trades.height == 0
    assert result.rejections.select(
        "reason", "requested_quantity", "rejected_quantity"
    ).row(0) == ("T_PLUS_ONE", 200, 200)
    assert result.positions.item(0, "quantity") == 200
    assert result.positions.item(0, "settled_quantity") == 100


def test_rejected_stock_sale_does_not_fund_etf_purchase() -> None:
    targets = _target(1.0).with_columns(pl.lit(ETF).alias("symbol"))
    result = simulate_daily_targets(
        calendar=_calendar(SESSION),
        bars=_stock_and_etf_bars(SESSION),
        scheduled_targets=targets,
        instruments=_stock_and_etf_instruments(),
        market_states={
            (SESSION, STOCK): DailyMarketState(),
            (SESSION, ETF): DailyMarketState(),
        },
        initial_cash=100.0,
        etf_costs=_etf_costs(),
        stock_costs=_stock_costs(),
        strategy="m2-u1",
        initial_positions=_initial_position(
            quantity=200,
            settled_quantity=100,
        ),
    )

    assert result.trades.height == 0
    assert result.rejections.select("symbol", "reason").row(0) == (
        STOCK,
        "T_PLUS_ONE",
    )
    assert result.positions.filter(pl.col("symbol") == STOCK).item(
        0, "quantity"
    ) == 200
    assert result.positions.filter(pl.col("symbol") == ETF).item(
        0, "quantity"
    ) == 0
    assert result.nav.item(0, "cash") == pytest.approx(100.0)


def test_etf_sale_does_not_apply_stock_t_plus_one_rule() -> None:
    targets = _target(0.0).with_columns(pl.lit(ETF).alias("symbol"))
    initial = pl.DataFrame({
        "symbol": [ETF],
        "quantity": [200],
        "settled_quantity": [0],
        "mark_price": [4.0],
    })
    result = simulate_daily_targets(
        calendar=_calendar(SESSION),
        bars=_stock_and_etf_bars(SESSION).filter(pl.col("symbol") == ETF),
        scheduled_targets=targets,
        instruments=_stock_and_etf_instruments().filter(
            pl.col("symbol") == ETF
        ),
        market_states={(SESSION, ETF): DailyMarketState()},
        initial_cash=100.0,
        etf_costs=_etf_costs(),
        stock_costs=_stock_costs(),
        strategy="m2-u1",
        initial_positions=initial,
    )

    assert result.rejections.height == 0
    assert result.trades.select("symbol", "side", "quantity").row(0) == (
        ETF,
        "SELL",
        200,
    )


def test_initial_etf_unsettled_evidence_is_preserved_until_second_session() -> None:
    second_session = SESSION + dt.timedelta(days=1)
    initial = pl.DataFrame({
        "symbol": [ETF],
        "quantity": [200],
        "settled_quantity": [0],
        "mark_price": [4.0],
    })
    result = simulate_daily_targets(
        calendar=_calendar(SESSION, second_session),
        bars=_stock_and_etf_bars(SESSION, second_session).filter(
            pl.col("symbol") == ETF
        ),
        scheduled_targets=_empty_targets(),
        instruments=_stock_and_etf_instruments().filter(
            pl.col("symbol") == ETF
        ),
        market_states={
            (SESSION, ETF): DailyMarketState(),
            (second_session, ETF): DailyMarketState(),
        },
        initial_cash=100.0,
        etf_costs=_etf_costs(),
        stock_costs=_stock_costs(),
        strategy="m2-u1",
        initial_positions=initial,
    )

    assert result.positions.select(
        "date", "settled_quantity", "unsettled_quantity"
    ).rows() == [
        (SESSION, 0, 200),
        (second_session, 200, 0),
    ]


def test_all_positions_settle_on_second_global_session() -> None:
    second_session = SESSION + dt.timedelta(days=1)
    sz_symbol = "000001.SZ"
    calendar = pl.DataFrame({
        "market": ["SH", "SZ", "SH", "SZ"],
        "date": [SESSION, SESSION, second_session, second_session],
        "is_open": [True, True, False, True],
        "is_connect_open": [False] * 4,
        "is_half_day": [False] * 4,
    })
    instruments = _stock_and_etf_instruments().with_columns(
        pl.when(pl.col("symbol") == ETF)
        .then(pl.lit(sz_symbol))
        .otherwise(pl.col("symbol"))
        .alias("symbol"),
        pl.when(pl.col("symbol") == ETF)
        .then(pl.lit("SZ"))
        .otherwise(pl.col("market"))
        .alias("market"),
        pl.lit("STOCK").alias("instrument_type"),
    )
    bars = (
        _stock_and_etf_bars(SESSION, second_session)
        .with_columns(
            pl.when(pl.col("symbol") == ETF)
            .then(pl.lit(sz_symbol))
            .otherwise(pl.col("symbol"))
            .alias("symbol")
        )
        .filter(
            ~(
                (pl.col("trade_date") == second_session)
                & (pl.col("symbol") == STOCK)
            )
        )
    )
    initial = pl.DataFrame({
        "symbol": [STOCK, sz_symbol],
        "quantity": [100, 100],
        "settled_quantity": [0, 0],
        "mark_price": [10.0, 4.0],
    })
    result = simulate_daily_targets(
        calendar=calendar,
        bars=bars,
        scheduled_targets=_empty_targets(),
        instruments=instruments,
        market_states={
            (SESSION, STOCK): DailyMarketState(),
            (SESSION, sz_symbol): DailyMarketState(),
            (second_session, sz_symbol): DailyMarketState(),
        },
        initial_cash=100.0,
        etf_costs=_etf_costs(),
        stock_costs=_stock_costs(),
        strategy="m2-u1",
        initial_positions=initial,
    )
    assert result.positions.filter(
        pl.col("date") == second_session
    ).select("symbol", "settled_quantity").rows() == [
        (sz_symbol, 100),
        (STOCK, 100),
    ]


def test_previous_session_stock_purchase_is_settled_before_next_sale() -> None:
    second_session = SESSION + dt.timedelta(days=1)
    bars = pl.concat([
        _bar(SESSION),
        _bar(second_session),
    ])
    targets = pl.DataFrame({
        "as_of": [
            SESSION - dt.timedelta(days=3),
            SESSION,
        ],
        "strategy": ["m2-u1", "m2-u1"],
        "strategy_version": ["1", "1"],
        "symbol": [STOCK, STOCK],
        "weight": [1.0, 0.0],
        "execution_date": [SESSION, second_session],
    })
    result = simulate_daily_targets(
        calendar=_calendar(SESSION, second_session),
        bars=bars,
        scheduled_targets=targets,
        instruments=_instruments(),
        market_states={
            (SESSION, STOCK): DailyMarketState(),
            (second_session, STOCK): DailyMarketState(),
        },
        initial_cash=10_000.0,
        etf_costs=_etf_costs(),
        stock_costs=_stock_costs(),
        strategy="m2-u1",
    )

    assert result.trades.select("date", "side", "quantity").rows() == [
        (SESSION, "BUY", 1_000),
        (second_session, "SELL", 1_000),
    ]
    assert result.rejections.height == 0
    assert result.positions.filter(pl.col("date") == second_session).item(
        0, "quantity"
    ) == 0


def test_session_without_target_batch_holds_existing_position() -> None:
    second_session = SESSION + dt.timedelta(days=1)
    result = simulate_daily_targets(
        calendar=_calendar(SESSION, second_session),
        bars=pl.concat([_bar(SESSION), _bar(second_session)]),
        scheduled_targets=_target(1.0),
        instruments=_instruments(),
        market_states={
            (SESSION, STOCK): DailyMarketState(),
            (second_session, STOCK): DailyMarketState(),
        },
        initial_cash=10_000.0,
        etf_costs=_etf_costs(),
        stock_costs=_stock_costs(),
        strategy="m2-u1",
    )

    assert result.trades.select("date", "side", "quantity").rows() == [
        (SESSION, "BUY", 1_000)
    ]
    assert result.positions.filter(pl.col("date") == second_session).select(
        "quantity", "settled_quantity", "unsettled_quantity"
    ).row(0) == (1_000, 1_000, 0)


def test_new_target_batch_zeros_omitted_holding_before_buying_etf() -> None:
    second_session = SESSION + dt.timedelta(days=1)
    targets = pl.DataFrame({
        "as_of": [SESSION - dt.timedelta(days=3), SESSION],
        "strategy": ["m2-u1", "m2-u1"],
        "strategy_version": ["1", "1"],
        "symbol": [STOCK, ETF],
        "weight": [1.0, 1.0],
        "execution_date": [SESSION, second_session],
    })
    states = {
        (SESSION, STOCK): DailyMarketState(),
        (second_session, STOCK): DailyMarketState(),
        (second_session, ETF): DailyMarketState(),
    }

    result = simulate_daily_targets(
        calendar=_calendar(SESSION, second_session),
        bars=_stock_and_etf_bars(SESSION, second_session),
        scheduled_targets=targets,
        instruments=_stock_and_etf_instruments(),
        market_states=states,
        initial_cash=10_000.0,
        etf_costs=_etf_costs(),
        stock_costs=_stock_costs(),
        strategy="m2-u1",
    )

    assert result.trades.select("date", "symbol", "side", "quantity").rows() == [
        (SESSION, STOCK, "BUY", 1_000),
        (second_session, STOCK, "SELL", 1_000),
        (second_session, ETF, "BUY", 2_500),
    ]
    second_positions = result.positions.filter(pl.col("date") == second_session)
    assert second_positions.select("symbol", "quantity").rows() == [
        (ETF, 2_500),
        (STOCK, 0),
    ]


def test_input_order_does_not_change_unified_stock_etf_result() -> None:
    instruments = _stock_and_etf_instruments()
    bars = _stock_and_etf_bars(SESSION)
    targets = pl.DataFrame({
        "as_of": [SESSION - dt.timedelta(days=3)] * 2,
        "strategy": ["m2-u1"] * 2,
        "strategy_version": ["1"] * 2,
        "symbol": [STOCK, ETF],
        "weight": [0.5, 0.5],
        "execution_date": [SESSION, SESSION],
    })
    states = {
        (SESSION, STOCK): DailyMarketState(),
        (SESSION, ETF): DailyMarketState(),
    }

    first = simulate_daily_targets(
        calendar=_calendar(SESSION),
        bars=bars,
        scheduled_targets=targets,
        instruments=instruments,
        market_states=states,
        initial_cash=20_000.0,
        etf_costs=_etf_costs(),
        stock_costs=_stock_costs(),
        strategy="m2-u1",
    )
    reversed_result = simulate_daily_targets(
        calendar=_calendar(SESSION).reverse(),
        bars=bars.reverse(),
        scheduled_targets=targets.reverse(),
        instruments=instruments.reverse(),
        market_states=dict(reversed(list(states.items()))),
        initial_cash=20_000.0,
        etf_costs=_etf_costs(),
        stock_costs=_stock_costs(),
        strategy="m2-u1",
    )

    assert first.nav.equals(reversed_result.nav)
    assert first.trades.equals(reversed_result.trades)
    assert first.positions.equals(reversed_result.positions)
    assert first.rejections.equals(reversed_result.rejections)


def test_stock_cost_pressure_replays_from_same_initial_account() -> None:
    results = {
        scale: simulate_daily_targets(
            calendar=_calendar(SESSION),
            bars=_bar(),
            scheduled_targets=_target(0.5),
            instruments=_instruments(),
            market_states={(SESSION, STOCK): DailyMarketState()},
            initial_cash=20_000.0,
            etf_costs=_etf_costs(),
            stock_costs=_stock_costs_scaled(scale),
            strategy="m2-u1",
        )
        for scale in (0.5, 1.0, 2.0)
    }

    assert [results[scale].trades.item(0, "quantity") for scale in results] == [
        1_000,
        1_000,
        1_000,
    ]
    fees = [results[scale].trades.item(0, "fee") for scale in results]
    slippage = [
        results[scale].trades.item(0, "slippage_cost") for scale in results
    ]
    assert fees[0] < fees[1] < fees[2]
    assert slippage[0] < slippage[1] < slippage[2]
    assert [
        results[scale].nav.item(0, "cash") for scale in results
    ] == sorted(
        (results[scale].nav.item(0, "cash") for scale in results),
        reverse=True,
    )
    for result in results.values():
        nav = result.nav.row(0, named=True)
        assert nav["equity"] == pytest.approx(
            nav["cash"] + nav["market_value"]
        )
        assert nav["unit_nav"] == pytest.approx(nav["equity"] / 20_000.0)
        assert nav["cumulative_fees"] == pytest.approx(
            result.trades.get_column("fee").sum()
        )


def test_higher_stock_cost_pressure_can_reduce_purchase_by_one_lot() -> None:
    quantities = []
    for scale in (0.5, 1.0, 2.0):
        result = simulate_daily_targets(
            calendar=_calendar(SESSION),
            bars=_bar(),
            scheduled_targets=_target(1.0),
            instruments=_instruments(),
            market_states={(SESSION, STOCK): DailyMarketState()},
            initial_cash=10_025.0,
            etf_costs=_etf_costs(),
            stock_costs=_stock_costs_scaled(scale),
            strategy="m2-u1",
        )
        quantities.append(result.trades.item(0, "quantity"))
        assert result.nav.item(0, "cash") >= 0

    assert quantities == [1_000, 1_000, 900]


def test_stock_sell_pressure_scales_commission_not_taxes() -> None:
    observed_fees = []
    for scale in (0.5, 1.0, 2.0):
        result = simulate_daily_targets(
            calendar=_calendar(SESSION),
            bars=_bar(),
            scheduled_targets=_target(0.0),
            instruments=_instruments(),
            market_states={(SESSION, STOCK): DailyMarketState()},
            initial_cash=100.0,
            etf_costs=_etf_costs(),
            stock_costs=_stock_costs_scaled(scale),
            strategy="m2-u1",
            initial_positions=_initial_position(
                quantity=10_000,
                settled_quantity=10_000,
            ),
        )
        execution_price = 10.0 * (1.0 - 0.001 * scale)
        notional = execution_price * 10_000
        expected_fee = (
            max(notional * 0.00025 * scale, 5.0 * scale)
            + notional * 0.00001
            + notional * 0.0005
        )
        observed_fees.append(result.trades.item(0, "fee"))
        assert result.trades.item(0, "fee") == pytest.approx(expected_fee)

    assert observed_fees[0] < observed_fees[1] < observed_fees[2]


def test_higher_etf_cost_pressure_recomputes_affordable_lots() -> None:
    targets = _target(1.0).with_columns(pl.lit(ETF).alias("symbol"))
    quantities = []
    for scale in (0.5, 1.0, 2.0):
        result = simulate_daily_targets(
            calendar=_calendar(SESSION),
            bars=_stock_and_etf_bars(SESSION).filter(pl.col("symbol") == ETF),
            scheduled_targets=targets,
            instruments=_stock_and_etf_instruments().filter(
                pl.col("symbol") == ETF
            ),
            market_states={(SESSION, ETF): DailyMarketState()},
            initial_cash=4_009.5,
            etf_costs=_etf_costs_scaled(scale),
            stock_costs=_stock_costs(),
            strategy="m2-u1",
        )
        quantities.append(result.trades.item(0, "quantity"))
        assert result.nav.item(0, "cash") >= 0

    assert quantities == [1_000, 1_000, 900]


def test_affordability_uses_bounded_search_for_extreme_lot_count() -> None:
    tiny_price = 1e-9
    instrument = _stock_and_etf_instruments().filter(
        pl.col("symbol") == ETF
    ).with_columns(pl.lit(1).alias("board_lot"))
    bars = _stock_and_etf_bars(SESSION).filter(
        pl.col("symbol") == ETF
    ).with_columns(
        pl.lit(tiny_price).alias("open"),
        pl.lit(tiny_price).alias("high"),
        pl.lit(tiny_price).alias("low"),
        pl.lit(tiny_price).alias("close"),
    )
    targets = _target(1.0).with_columns(pl.lit(ETF).alias("symbol"))

    result = simulate_daily_targets(
        calendar=_calendar(SESSION),
        bars=bars,
        scheduled_targets=targets,
        instruments=instrument,
        market_states={(SESSION, ETF): DailyMarketState()},
        initial_cash=10_000.0,
        etf_costs=EtfCostModel(
            commission_rate=0.0,
            commission_min=5.0,
            slippage=0.0,
            effective_from=dt.date(2026, 1, 1),
        ),
        stock_costs=_stock_costs(),
        strategy="m2-u1",
    )

    assert result.trades.item(0, "quantity") == 9_995_000_000_000
    assert result.nav.item(0, "cash") == pytest.approx(0.0)


def test_cost_pressure_builders_scale_only_execution_cost_fields() -> None:
    etf = EtfCostModel(
        commission_rate=0.0001,
        commission_min=5.0,
        slippage=0.001,
        effective_from=dt.date(2026, 1, 1),
    )
    stock = AShareCostModel(
        commission_rate=0.00025,
        commission_min=5.0,
        stamp_tax_sell=0.0005,
        transfer_fee=0.00001,
        slippage=0.001,
        effective_from=dt.date(2026, 1, 1),
    )

    half_etf = etf.with_execution_cost_multiplier(0.5)
    double_stock = stock.with_execution_cost_multiplier(2.0)

    assert (
        half_etf.commission_rate,
        half_etf.commission_min,
        half_etf.slippage,
        half_etf.effective_from,
    ) == (0.00005, 2.5, 0.0005, etf.effective_from)
    assert (
        double_stock.commission_rate,
        double_stock.commission_min,
        double_stock.slippage,
        double_stock.stamp_tax_sell,
        double_stock.transfer_fee,
        double_stock.effective_from,
    ) == (
        0.0005,
        10.0,
        0.002,
        stock.stamp_tax_sell,
        stock.transfer_fee,
        stock.effective_from,
    )
    assert etf.commission_min == 5.0
    assert stock.commission_min == 5.0


@pytest.mark.parametrize(
    "multiplier",
    [0.0, -1.0, float("nan"), float("inf"), True],
)
def test_cost_pressure_multiplier_must_be_positive_and_finite(
    multiplier: float,
) -> None:
    with pytest.raises(ValueError):
        _etf_costs().with_execution_cost_multiplier(multiplier)
    with pytest.raises(ValueError):
        _stock_costs().with_execution_cost_multiplier(multiplier)


@pytest.mark.parametrize(
    ("model", "field"),
    [
        ("ETF", "commission_rate"),
        ("ETF", "commission_min"),
        ("ETF", "slippage"),
        ("STOCK", "commission_rate"),
        ("STOCK", "commission_min"),
        ("STOCK", "stamp_tax_sell"),
        ("STOCK", "transfer_fee"),
        ("STOCK", "slippage"),
    ],
)
def test_cost_model_rejects_non_finite_fields(
    model: str,
    field: str,
) -> None:
    if model == "ETF":
        values = {
            "commission_rate": 0.0001,
            "commission_min": 5.0,
            "slippage": 0.001,
        }
        values[field] = float("nan")
        with pytest.raises(ValueError):
            EtfCostModel(
                **values,
                effective_from=dt.date(2026, 1, 1),
            )
    else:
        stock_values = {
            "commission_rate": 0.00025,
            "commission_min": 5.0,
            "stamp_tax_sell": 0.0005,
            "transfer_fee": 0.00001,
            "slippage": 0.001,
        }
        stock_values[field] = float("inf")
        with pytest.raises(ValueError):
            AShareCostModel(
                **stock_values,
                effective_from=dt.date(2026, 1, 1),
            )


def test_five_session_unified_event_sequence_and_sorting() -> None:
    dates = [SESSION + dt.timedelta(days=offset) for offset in range(5)]
    bars = _stock_and_etf_bars(*dates).filter(
        ~(
            (pl.col("trade_date") == dates[1])
            & (pl.col("symbol") == STOCK)
        )
    )
    targets = pl.DataFrame({
        "as_of": [
            SESSION - dt.timedelta(days=3),
            SESSION - dt.timedelta(days=3),
            dates[1],
            dates[2],
            dates[3],
        ],
        "strategy": ["m2-u1"] * 5,
        "strategy_version": ["1"] * 5,
        "symbol": [STOCK, ETF, STOCK, ETF, ETF],
        "weight": [0.0, 0.2, 1.0, 1.0, 1.0],
        "execution_date": [
            dates[0],
            dates[0],
            dates[2],
            dates[3],
            dates[4],
        ],
    })
    states = {
        (date, symbol): DailyMarketState(
            suspended=date == dates[1] and symbol == STOCK,
            at_upper_limit=date == dates[2] and symbol == STOCK,
            at_lower_limit=date == dates[3] and symbol == STOCK,
        )
        for date in dates
        for symbol in (STOCK, ETF)
    }
    arguments = {
        "calendar": _calendar(*dates),
        "bars": bars,
        "scheduled_targets": targets,
        "instruments": _stock_and_etf_instruments(),
        "market_states": states,
        "initial_cash": 1_000.0,
        "etf_costs": _etf_costs(),
        "stock_costs": _stock_costs(),
        "strategy": "m2-u1",
        "initial_positions": _initial_position(
            quantity=200,
            settled_quantity=100,
        ),
    }

    result = simulate_daily_targets(**arguments)
    reversed_result = simulate_daily_targets(
        **{
            **arguments,
            "calendar": arguments["calendar"].reverse(),
            "bars": arguments["bars"].reverse(),
            "scheduled_targets": arguments["scheduled_targets"].reverse(),
            "instruments": arguments["instruments"].reverse(),
            "market_states": dict(reversed(list(states.items()))),
        }
    )

    assert result.nav.get_column("equity").to_list() == pytest.approx(
        [3_000.0] * 5
    )
    assert result.nav.get_column("date").to_list() == dates
    for nav in result.nav.iter_rows(named=True):
        assert nav["equity"] == pytest.approx(
            nav["cash"] + nav["market_value"]
        )
        assert nav["unit_nav"] == pytest.approx(nav["equity"] / 3_000.0)
        assert nav["cumulative_fees"] == pytest.approx(0.0)
    assert result.trades.select("date", "symbol", "side", "quantity").rows() == [
        (dates[0], ETF, "BUY", 100),
        (dates[2], ETF, "SELL", 100),
        (dates[3], ETF, "BUY", 200),
        (dates[4], STOCK, "SELL", 200),
        (dates[4], ETF, "BUY", 500),
    ]
    assert result.rejections.select("date", "symbol", "side", "reason").rows() == [
        (dates[0], STOCK, "SELL", "T_PLUS_ONE"),
        (dates[2], STOCK, "BUY", "BUY_AT_UPPER_LIMIT"),
        (dates[3], STOCK, "SELL", "SELL_AT_LOWER_LIMIT"),
    ]
    suspended_position = result.positions.filter(
        (pl.col("date") == dates[1]) & (pl.col("symbol") == STOCK)
    ).row(0, named=True)
    assert suspended_position["quantity"] == 200
    assert suspended_position["settled_quantity"] == 200
    assert suspended_position["unsettled_quantity"] == 0
    assert suspended_position["mark_price"] == pytest.approx(10.0)
    assert suspended_position["market_value"] == pytest.approx(2_000.0)
    assert suspended_position["target_weight"] == pytest.approx(0.0)
    day_two_etf = result.positions.filter(
        (pl.col("date") == dates[1]) & (pl.col("symbol") == ETF)
    ).row(0, named=True)
    assert day_two_etf["target_weight"] == pytest.approx(0.2)
    sold_etf = result.positions.filter(
        (pl.col("date") == dates[2]) & (pl.col("symbol") == ETF)
    ).row(0, named=True)
    assert sold_etf["quantity"] == 0
    assert sold_etf["target_weight"] == pytest.approx(0.0)
    position_keys = result.positions.select("date", "symbol").rows()
    assert position_keys == sorted(position_keys)
    assert result.nav.equals(reversed_result.nav)
    assert result.trades.equals(reversed_result.trades)
    assert result.positions.equals(reversed_result.positions)
    assert result.rejections.equals(reversed_result.rejections)
