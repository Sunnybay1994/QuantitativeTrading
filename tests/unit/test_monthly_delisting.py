import datetime as dt

import polars as pl
import pytest

from quant.backtest.rules import DailyMarketState
from quant.research.classic_monthly_baseline import replay


def test_unsold_delisted_holding_is_written_down_without_sale_proceeds():
    first, second = dt.date(2026, 1, 5), dt.date(2026, 1, 6)
    symbol = "600000.SH"
    bars = pl.DataFrame({"symbol": [symbol] * 2, "trade_date": [first, second],
        "open": [10.] * 2, "high": [10.] * 2, "low": [10.] * 2, "close": [10.] * 2,
        "volume": [10000.] * 2, "amount": [100000.] * 2, "adj_factor": [1.] * 2, "source": ["fixture"] * 2})
    calendar = pl.DataFrame({"market": ["SH"] * 2, "date": [first, second], "is_open": [True] * 2,
        "is_connect_open": [False] * 2, "is_half_day": [False] * 2})
    instruments = pl.DataFrame({"symbol": [symbol], "market": ["SH"], "name": ["fixture"],
        "instrument_type": ["STOCK"], "currency": ["CNY"], "list_date": [dt.date(2000, 1, 1)],
        "delist_date": [first], "board_lot": [100], "status": ["DELISTED"]})
    targets = pl.DataFrame({"as_of": [first - dt.timedelta(days=3)], "execution_date": [first],
        "symbol": [symbol], "weight": [.5], "strategy": ["fixture"], "strategy_version": ["v1"]})
    dividends = pl.DataFrame(schema={"symbol": pl.String, "ex_date": pl.Date})
    common = {"commission_rate": 0., "commission_min": 0., "slippage": 0., "effective_from": dt.date(2020, 1, 1)}
    config = {"portfolio": {"initial_cash": 10000., "delisted_holding_recovery": 0.},
        "costs": {"etf": common, "a_share": {**common, "stamp_tax_sell": 0., "transfer_fee": 0.}}}
    nav, trades, _ = replay(bars=bars, calendar=calendar, instruments=instruments,
        targets=targets, dividends=dividends, market_states={(first, symbol): DailyMarketState()},
        config=config, sessions=[first, second], name="fixture")
    assert nav["equity"].to_list() == pytest.approx([10000., 5000.])
    assert nav["cash"].to_list() == pytest.approx([5000., 5000.])
    assert nav["delisting_writeoff"].to_list() == [0., 5000.]
    assert nav["delisted_symbols"][1] == symbol
    assert trades.height == 1
    cash_nav, cash_trades, _ = replay(bars=bars, calendar=calendar, instruments=instruments,
        targets=targets.with_columns(pl.lit(0.).alias("weight")), dividends=dividends,
        market_states={(first, symbol): DailyMarketState()}, config=config, sessions=[first, second], name="fixture")
    assert cash_nav["missing_target_positions"][0] == 0
    assert cash_trades.is_empty()
    assert cash_nav["equity"].to_list() == [10000., 10000.]
