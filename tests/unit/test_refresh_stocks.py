import datetime as dt

import polars as pl
import pytest

from quant.data.refresh_stocks import normalize_day

DATE = dt.date(2026, 9, 8)


def frames() -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    daily = pl.DataFrame({"ts_code": ["000001.SZ"], "trade_date": ["20260908"],
                          "open": [10.0], "high": [11.0], "low": [9.0], "close": [10.5],
                          "vol": [100.0], "amount": [105.0]})
    factors = pl.DataFrame({"ts_code": ["000001.SZ"], "trade_date": ["20260908"],
                            "adj_factor": [2.5]})
    basic = pl.DataFrame({"ts_code": ["000001.SZ"], "trade_date": ["20260908"],
                         "close": [10.5], "turnover_rate": [1.0], "turnover_rate_f": [2.0],
                         "volume_ratio": [1.1], "pe": [-3.0], "pe_ttm": [None], "pb": [1.2],
                         "ps": [1.0], "ps_ttm": [1.0], "dv_ratio": [0.5], "dv_ttm": [0.5],
                         "total_share": [100.0], "float_share": [80.0], "free_share": [50.0],
                         "total_mv": [1050.0], "circ_mv": [840.0]})
    return daily, factors, basic


def test_unit_conversion_and_exact_adjustment_join():
    result = normalize_day(*frames(), date=DATE)
    bar = result["bar_1d"].row(0, named=True)
    assert (bar["volume"], bar["amount"], bar["adj_factor"]) == (10000, 105000, 2.5)
    basic = result["daily_basic"].row(0, named=True)
    assert basic["total_shares"] == 1_000_000
    assert basic["total_market_value"] == 10_500_000
    assert basic["turnover_rate_free"] == 2.0
    assert basic["pe"] == -3.0 and basic["pe_ttm"] is None
    assert result["adjust_factor"]["effective_date"][0] == DATE


def test_missing_factor_wrong_day_duplicate_or_close_mismatch_fail():
    daily, factors, basic = frames()
    with pytest.raises(ValueError, match="missing adjustment"):
        normalize_day(daily, factors.with_columns(pl.lit("000002.SZ").alias("ts_code")),
                      basic, date=DATE)
    with pytest.raises(ValueError, match="date differs"):
        normalize_day(daily, factors, basic, date=DATE - dt.timedelta(days=1))
    with pytest.raises(ValueError, match="duplicate stock"):
        normalize_day(pl.concat([daily, daily]), factors, basic, date=DATE)
    with pytest.raises(ValueError, match="close differs"):
        normalize_day(daily, factors, basic.with_columns(pl.lit(10.6).alias("close")), date=DATE)


def test_suspended_stock_factor_is_preserved_without_inventing_bar():
    daily, factors, basic = frames()
    factors = pl.concat([factors, factors.with_columns(pl.lit("000002.SZ").alias("ts_code"))])
    result = normalize_day(daily, factors, basic, date=DATE)
    assert result["bar_1d"].height == 1
    assert result["adjust_factor"].height == 2


def test_inconsistent_optional_free_float_is_missing_not_fabricated():
    daily, factors, basic = frames()
    basic = basic.with_columns(pl.lit(90.0).alias("free_share"))
    result = normalize_day(daily, factors, basic, date=DATE)
    assert result["daily_basic"]["free_float_shares"][0] is None
    assert result["daily_basic"]["turnover_rate_free"][0] is None
    assert result["daily_basic"]["float_shares"][0] == 800_000
