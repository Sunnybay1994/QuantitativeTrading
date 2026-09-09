import datetime as dt

import polars as pl
import pytest

from quant.data.etf_execution_quotes import execution_bars, quote_quality_errors
from quant.data.etf_paper_inputs import etf_session_states
from quant.research.classic_monthly_baseline import replay
from quant.research.monthly_execution_time import compare_test_results


def test_observed_quote_changes_fill_but_keeps_close_and_limit_rules():
    day, previous = dt.date(2026, 8, 3), dt.date(2026, 7, 31)
    bars = pl.DataFrame({"symbol": ["510300.SH"], "trade_date": [day], "open": [10.], "close": [12.],
        "high": [12.], "low": [9.], "volume": [100000.], "amount": [1100000.], "adj_factor": [1.], "source": ["fixture"]})
    quotes = pl.DataFrame({"symbol": ["510300.SH"] * 2, "trade_date": [day] * 2,
        "time": ["09:30", "09:35"], "open": [10., 11.], "volume": [1000., 1000.]})
    calendar = pl.DataFrame({"date": [previous, day], "market": ["SH"] * 2, "is_open": [True] * 2,
        "is_connect_open": [False] * 2, "is_half_day": [False] * 2})
    instruments = pl.DataFrame({"symbol": ["510300.SH"], "market": ["SH"], "name": ["fixture"],
        "instrument_type": ["ETF"], "currency": ["CNY"], "list_date": [dt.date(2010, 1, 1)],
        "delist_date": [None], "board_lot": [100], "status": ["LISTED"]}).with_columns(pl.col("delist_date").cast(pl.Date))
    targets = pl.DataFrame({"symbol": ["510300.SH"], "as_of": [previous], "execution_date": [day],
        "weight": [1.], "strategy": ["fixture"], "strategy_version": ["v1"]})
    dividends = pl.DataFrame(schema={"symbol": pl.String, "ann_date": pl.Date, "record_date": pl.Date,
        "ex_date": pl.Date, "pay_date": pl.Date, "div_cash": pl.Float64})
    limits = pl.DataFrame({"symbol": ["510300.SH"], "trade_date": [day], "up_limit": [15.], "down_limit": [5.]})
    costs = {"commission_rate": 0., "commission_min": 0., "slippage": 0., "effective_from": previous}
    config = {"portfolio": {"initial_cash": 10000.}, "costs": {
        "etf": costs, "a_share": {**costs, "stamp_tax_sell": 0., "transfer_fee": 0.}}}
    def account(time, selected=quotes):
        observed = execution_bars(bars, selected, time, .001)
        assert observed["close"].to_list() == [12.]
        states = etf_session_states(observed, dividends, official_limits=limits)
        return replay(bars=observed, calendar=calendar, instruments=instruments, targets=targets,
            dividends=dividends, market_states=states, config=config, sessions=[day], name="fixture")
    assert account("09:30")[0]["equity"][0] == pytest.approx(12000.)
    assert account("09:35")[0]["equity"][0] == pytest.approx(10900.)
    dead = quotes.with_columns(pl.lit(0.).alias("volume"))
    assert len(quote_quality_errors(dead)) == 2
    assert quote_quality_errors(quotes) == []
    assert account("09:35", dead)[1].is_empty()
    assert bars["open"][0] == 10.
    with pytest.raises(ValueError, match="outside"):
        execution_bars(bars, quotes.with_columns(pl.lit(20.).alias("open")), "09:35", .001)


def test_test_only_decision_requires_both_allocations_and_all_costs():
    rows = [{"period": "test", "allocation": a, "time": t, "cost_multiplier": c,
             "total_return": .02 if t == "09:35" else .01, "max_drawdown": -.01}
            for a in ("inverse_volatility", "equal_weight") for t in ("09:30", "09:35") for c in (.5, 1., 2.)]
    assert compare_test_results(rows)["conclusion"] == "RESEARCH_ONLY"
    rows[-1]["total_return"] = 0.
    assert compare_test_results(rows)["conclusion"] == "REJECTED"
