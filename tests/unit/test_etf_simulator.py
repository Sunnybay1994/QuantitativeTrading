import datetime as dt
import inspect

import polars as pl
import pytest

from quant.backtest import (
    EtfCostModel,
    SimulationResult,
    simulate_etf_targets,
)


def test_simulator_credits_dividend_and_uses_raw_prices() -> None:
    dates = [dt.date(2026, 1, 5), dt.date(2026, 1, 6)]
    bars = pl.DataFrame({
        "symbol": ["510300.SH", "510300.SH"],
        "trade_date": dates,
        "open": [10.0, 9.0],
        "high": [10.0, 9.0],
        "low": [10.0, 9.0],
        "close": [10.0, 9.0],
        "volume": [1000.0, 1000.0],
        "amount": [10000.0, 9000.0],
        "adj_factor": [1.0, 1.0],
        "source": ["fixture", "fixture"],
    })
    research = pl.DataFrame({
        "symbol": ["510300.SH", "510300.SH"],
        "trade_date": dates,
        "adjusted_close": [10.0, 10.0],
        "adjustment_method": ["TOTAL_RETURN_DIVIDEND"] * 2,
        "source": ["fixture", "fixture"],
    })
    targets = pl.DataFrame({
        "as_of": [dt.date(2026, 1, 2)],
        "strategy": ["s0"],
        "strategy_version": ["1"],
        "symbol": ["510300.SH"],
        "weight": [1.0],
        "execution_date": [dates[0]],
    })
    instruments = pl.DataFrame({
        "symbol": ["510300.SH"],
        "market": ["SH"],
        "name": ["ETF"],
        "instrument_type": ["ETF"],
        "currency": ["CNY"],
        "list_date": [dt.date(2012, 1, 1)],
        "delist_date": [None],
        "board_lot": [100],
        "status": ["LISTED"],
    })
    result = simulate_etf_targets(
        bars=bars,
        research_prices=research,
        scheduled_targets=targets,
        instruments=instruments,
        initial_cash=10000.0,
        costs=EtfCostModel(0.0, 0.0, 0.0, dt.date(2026, 1, 1)),
        strategy="s0",
    )
    assert result.trades.item(0, "quantity") == 1000
    assert result.nav.get_column("equity").to_list() == [10000.0, 10000.0]
    assert result.nav.item(1, "cash") == 1000.0


def test_cost_model_applies_slippage_and_minimum_commission() -> None:
    costs = EtfCostModel(0.0001, 5.0, 0.001, dt.date(2026, 1, 1))
    assert costs.execution_price(10.0, "BUY") == pytest.approx(10.01)
    assert costs.execution_price(10.0, "SELL") == pytest.approx(9.99)
    assert costs.fee(1000.0, dt.date(2026, 1, 2)) == 5.0


def test_dividend_cash_is_available_for_same_open_rebalance() -> None:
    dates = [dt.date(2026, 1, 5), dt.date(2026, 1, 6)]
    bars = pl.DataFrame({
        "symbol": ["510300.SH", "510300.SH"],
        "trade_date": dates,
        "open": [10.0, 9.0],
        "high": [10.0, 9.0],
        "low": [10.0, 9.0],
        "close": [10.0, 9.0],
        "volume": [1000.0, 1000.0],
        "amount": [10000.0, 9000.0],
        "adj_factor": [1.0, 1.0],
        "source": ["fixture", "fixture"],
    })
    research = pl.DataFrame({
        "symbol": ["510300.SH", "510300.SH"],
        "trade_date": dates,
        "adjusted_close": [10.0, 10.0],
        "adjustment_method": ["TOTAL_RETURN_DIVIDEND"] * 2,
        "source": ["fixture", "fixture"],
    })
    targets = pl.DataFrame({
        "as_of": [dt.date(2026, 1, 2), dates[0]],
        "strategy": ["s0", "s0"],
        "strategy_version": ["1", "1"],
        "symbol": ["510300.SH", "510300.SH"],
        "weight": [1.0, 1.0],
        "execution_date": dates,
    })
    instruments = pl.DataFrame({
        "symbol": ["510300.SH"],
        "market": ["SH"],
        "name": ["ETF"],
        "instrument_type": ["ETF"],
        "currency": ["CNY"],
        "list_date": [dt.date(2012, 1, 1)],
        "delist_date": [None],
        "board_lot": [100],
        "status": ["LISTED"],
    })

    result = simulate_etf_targets(
        bars=bars,
        research_prices=research,
        scheduled_targets=targets,
        instruments=instruments,
        initial_cash=10000.0,
        costs=EtfCostModel(0.0, 0.0, 0.0, dt.date(2026, 1, 1)),
        strategy="s0",
    )

    assert result.trades.select("date", "side", "quantity").rows() == [
        (dates[0], "BUY", 1000),
        (dates[1], "BUY", 100),
    ]
    assert result.nav.item(1, "cash") == pytest.approx(100.0)
    assert result.nav.item(1, "equity") == pytest.approx(10000.0)


def test_two_etf_rebalance_preserves_sell_before_buy_and_cash_boundary() -> None:
    dates = [dt.date(2026, 1, 5), dt.date(2026, 1, 6)]
    symbols = ["510300.SH", "510500.SH"]
    bars = pl.DataFrame({
        "symbol": symbols * 2,
        "trade_date": [dates[0]] * 2 + [dates[1]] * 2,
        "open": [10.0, 4.0, 10.0, 4.0],
        "high": [10.0, 4.0, 10.0, 4.0],
        "low": [10.0, 4.0, 10.0, 4.0],
        "close": [10.0, 4.0, 10.0, 4.0],
        "volume": [1000.0] * 4,
        "amount": [10000.0, 4000.0, 10000.0, 4000.0],
        "adj_factor": [1.0] * 4,
        "source": ["fixture"] * 4,
    })
    research = pl.DataFrame({
        "symbol": symbols * 2,
        "trade_date": [dates[0]] * 2 + [dates[1]] * 2,
        "adjusted_close": [10.0, 4.0, 10.0, 4.0],
        "adjustment_method": ["TOTAL_RETURN_DIVIDEND"] * 4,
        "source": ["fixture"] * 4,
    })
    targets = pl.DataFrame({
        "as_of": [dt.date(2026, 1, 2)] * 2 + [dates[0]] * 2,
        "strategy": ["s0"] * 4,
        "strategy_version": ["1"] * 4,
        "symbol": symbols * 2,
        "weight": [1.0, 0.0, 0.0, 1.0],
        "execution_date": [dates[0]] * 2 + [dates[1]] * 2,
    })
    instruments = pl.DataFrame({
        "symbol": symbols,
        "market": ["SH", "SH"],
        "name": ["ETF300", "ETF500"],
        "instrument_type": ["ETF", "ETF"],
        "currency": ["CNY", "CNY"],
        "list_date": [dt.date(2012, 1, 1)] * 2,
        "delist_date": [None, None],
        "board_lot": [100, 100],
        "status": ["LISTED", "LISTED"],
    })

    result = simulate_etf_targets(
        bars=bars,
        research_prices=research,
        scheduled_targets=targets,
        instruments=instruments,
        initial_cash=10025.0,
        costs=EtfCostModel(0.0, 5.0, 0.0, dt.date(2026, 1, 1)),
        strategy="s0",
    )

    assert result.trades.select("date", "symbol", "side", "quantity").rows() == [
        (dates[0], "510300.SH", "BUY", 1000),
        (dates[1], "510300.SH", "SELL", 1000),
        (dates[1], "510500.SH", "BUY", 2500),
    ]
    assert result.nav.select("cash", "cumulative_fees").row(1) == pytest.approx(
        (10.0, 15.0)
    )


def test_legacy_etf_entrypoint_signature_and_result_shape_are_stable() -> None:
    assert tuple(inspect.signature(simulate_etf_targets).parameters) == (
        "bars",
        "research_prices",
        "scheduled_targets",
        "instruments",
        "initial_cash",
        "costs",
        "strategy",
    )
    assert all(
        parameter.kind is inspect.Parameter.KEYWORD_ONLY
        for parameter in inspect.signature(
            simulate_etf_targets
        ).parameters.values()
    )
    assert tuple(SimulationResult.__dataclass_fields__) == ("nav", "trades")
