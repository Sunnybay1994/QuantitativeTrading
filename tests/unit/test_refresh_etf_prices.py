import datetime as dt

import polars as pl
import pytest

from quant.data.refresh_etf_prices import build_prices, join_seam


def daily() -> pl.DataFrame:
    return pl.DataFrame({
        "ts_code": ["510300.SH"] * 4,
        "trade_date": ["20260707", "20260708", "20260709", "20260710"],
        "close": [10.0, 9.0, 9.9, 10.8],
    })


def dividends() -> pl.DataFrame:
    return pl.DataFrame({
        "ts_code": ["510300.SH"] * 3,
        "div_proc": ["实施", "实施", "预案"],
        "ex_date": ["20260708", "20260708", "20260709"],
        "div_cash": [1.0, 1.0, 8.0],
    })


def test_cash_dividend_reinvested_once_and_seam_is_anchored_once():
    candidate = build_prices(daily(), dividends())
    assert candidate["adjusted_close"].to_list() == pytest.approx([10, 10, 11, 12])
    old = candidate.head(3).with_columns(pl.col("adjusted_close") * 2)
    incoming, checks = join_seam(candidate, old, minimum_overlap=3)
    assert incoming["trade_date"].to_list() == [dt.date(2026, 7, 10)]
    assert incoming["adjusted_close"].to_list() == pytest.approx([24])
    assert checks[0]["max_relative_error"] < 1e-12
    bad = old.with_columns(pl.when(pl.col("trade_date") == dt.date(2026, 7, 8))
                           .then(21).otherwise(pl.col("adjusted_close")).alias("adjusted_close"))
    with pytest.raises(ValueError, match="seam mismatch"):
        join_seam(candidate, bad, minimum_overlap=3)


def test_conflicting_dividends_and_duplicate_prices_fail():
    conflict = dividends().with_columns(pl.Series("div_cash", [1.0, 2.0, 8.0]))
    with pytest.raises(ValueError, match="Conflicting dividend"):
        build_prices(daily(), conflict)
    with pytest.raises(ValueError, match="Duplicate ETF"):
        build_prices(pl.concat([daily(), daily().head(1)]), dividends())


def test_no_dividends_and_insufficient_overlap():
    prices = build_prices(daily(), pl.DataFrame())
    assert prices["adjusted_close"].to_list() == pytest.approx([10, 9, 9.9, 10.8])
    with pytest.raises(ValueError, match="Insufficient overlap"):
        join_seam(prices, prices.head(1))
