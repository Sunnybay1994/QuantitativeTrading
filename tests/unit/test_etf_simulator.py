import datetime as dt

import polars as pl
import pytest

from quant.backtest import EtfCostModel, simulate_etf_targets


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
