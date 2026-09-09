import datetime as dt

import polars as pl
import pytest

from quant.data.stock_execution_inputs import resolve_same_day_dividends


@pytest.mark.parametrize("symbol,date,amounts,expected,shares", [
    ("002352.SZ", "2024-11-07", [.4, 1., 1.4], 1.4, 0.),
    ("300760.SZ", "2025-05-29", [.56, 1.41], 1.97, 0.),
    ("300760.SZ", "2026-05-28", [.31, 1.25], 1.56, 0.),
    ("600188.SH", "2023-07-17", [1.23, 3.07], 4.3, .5),
    ("600600.SH", "2023-07-14", [.5, 1.8], 1.8, 0.),
    ("600720.SH", "2024-06-13", [.1104, .257], .3674, 0.),
    ("600989.SH", "2024-07-24", [.265, .3158], .3158, 0.),
    ("603259.SH", "2025-05-21", [.35, .98169], 1.33169, 0.),
])
def test_resolves_issuer_verified_dividend_implementations(symbol, date, amounts, expected, shares):
    ex = dt.date.fromisoformat(date)
    rows = [{"symbol": symbol, "ex_date": ex, "ann_date": ex - dt.timedelta(days=7),
        "record_date": ex - dt.timedelta(days=1), "pay_date": ex, "div_cash": cash,
        "share_ratio": shares if i == len(amounts) - 1 else 0.,
        "share_list_date": ex if shares and i == len(amounts) - 1 else None}
        for i, cash in enumerate(amounts)]
    result = resolve_same_day_dividends(pl.DataFrame(rows))
    assert result.height == 1
    assert result["div_cash"][0] == pytest.approx(expected)
    assert result["share_ratio"][0] == shares
    if shares:
        assert result["share_list_date"][0] == ex
    changed = pl.DataFrame(rows).with_columns((pl.col("div_cash") + .01).alias("div_cash"))
    with pytest.raises(ValueError, match="Unexpected dividend"):
        resolve_same_day_dividends(changed)
